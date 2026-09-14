import json
import os
import subprocess
import tempfile

# Only these three are accepted for export_ratio — deliberately locked down.
RATIO_SPECS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


def _get_video_duration(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", video_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video_path}: {result.stderr.decode(errors='ignore')}")
    return float(json.loads(result.stdout)["format"]["duration"])


def _cut_segment(video_path, start, end, out_path):
    """Cut [start, end) from video_path into out_path. Returns False if the
    requested range is empty/invalid (nothing was written)."""
    duration = end - start
    if duration <= 0.01:
        return False
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        out_path,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed [{start}-{end}] — see ffmpeg output above for details")
    return True


def _concat_clips(clip_paths, out_path, work_dir, tag):
    list_file = os.path.join(work_dir, f"{tag}_concat_list.txt")
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_path]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg concat failed — see ffmpeg output above for details")


def _compute_primary_windows(timestamps, gap, duration):
    """Each headshot's own [start, end) clip window, clipped to video bounds."""
    return [(max(0.0, t), min(duration, t + gap)) for t in timestamps]


def _compute_leftover_gaps(primary_windows, duration):
    """
    Regions of the video NOT covered by any headshot's own primary window —
    i.e. the video's natural gaps. Returned sorted biggest-first, since
    patch footage should be pulled from the biggest natural gap first.
    """
    sorted_windows = sorted(primary_windows, key=lambda w: w[0])
    leftover = []
    cursor = 0.0
    for start, end in sorted_windows:
        if start > cursor:
            leftover.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        leftover.append((cursor, duration))
    leftover.sort(key=lambda w: (w[1] - w[0]), reverse=True)
    return leftover


def _take_from_leftover(leftover_gaps, needed):
    """
    Pull `needed` seconds of segments from the leftover gaps, biggest gap
    first. Does not mutate leftover_gaps, so the same footage can be reused
    as a patch for more than one headshot (repeats are allowed).
    Returns (segments, short_by) — short_by > 0 means there genuinely
    wasn't enough unused footage anywhere to fully cover the deficit.
    """
    segments = []
    remaining = needed
    for g_start, g_end in leftover_gaps:
        if remaining <= 0.01:
            break
        g_size = g_end - g_start
        if g_size <= 0.01:
            continue
        take = min(g_size, remaining)
        segments.append((g_start, g_start + take))
        remaining -= take
    return segments, max(0.0, remaining)


def _apply_export_ratio(input_path, output_path, export_ratio):
    """Center-crop to the target aspect ratio (no stretching/distortion),
    then scale to that ratio's standard resolution."""
    target_w, target_h = RATIO_SPECS[export_ratio]
    vf = (
        f"crop='min(iw,ih*{target_w}/{target_h})':'min(ih,iw*{target_h}/{target_w})',"
        f"scale={target_w}:{target_h}:flags=bicubic,setsar=1"
    )
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac",
        output_path,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg export-ratio step failed — see ffmpeg output above for details")


def build_headshot_highlight(video_path, headshot_timestamps, gap, export_ratio, output_path):
    """
    Build one merged highlight video from a list of headshot timestamps.

    video_path           : source video file
    headshot_timestamps   : list of seconds, e.g. [2, 5.5, 7]
    gap                    : single target clip duration (seconds) applied
                              to every headshot, e.g. 5
    export_ratio           : one of "16:9", "9:16", "1:1" — nothing else
    output_path             : where the final merged, ratio-cropped video is written

    For each headshot: cuts [timestamp, timestamp+gap]. If the video runs
    out before reaching the full gap, the missing seconds are patched in
    from the video's biggest unused ("natural gap") region — footage reuse
    across clips/patches is allowed, so this always tries to hit the full
    gap length rather than leaving clips short.

    Returns {"output_path": ..., "warnings": [...]}. Warnings list any
    headshot where even borrowing from every leftover region in the video
    still couldn't fully cover the requested gap.
    """
    if export_ratio not in RATIO_SPECS:
        raise ValueError(f"export_ratio must be one of {list(RATIO_SPECS)}, got {export_ratio!r}")

    duration = _get_video_duration(video_path)
    timestamps = sorted(t for t in headshot_timestamps if 0 <= t < duration)
    if not timestamps:
        raise ValueError("No valid headshot timestamps within the video's duration.")

    primary_windows = _compute_primary_windows(timestamps, gap, duration)
    leftover_gaps = _compute_leftover_gaps(primary_windows, duration)

    work_dir = tempfile.mkdtemp(prefix="headshot_highlight_")
    warnings = []
    clip_paths = []

    try:
        total = len(timestamps)
        for i, (t, (start, end)) in enumerate(zip(timestamps, primary_windows)):
            print(f"[{i + 1}/{total}] Headshot at {t}s...")
            segment_specs = [(start, end)]
            deficit = gap - (end - start)

            if deficit > 0.01:
                patch_segments, short_by = _take_from_leftover(leftover_gaps, deficit)
                segment_specs.extend(patch_segments)
                print(f"    patching {deficit - short_by:.2f}s from elsewhere in the video")
                if short_by > 0.01:
                    warnings.append(
                        f"Headshot at {t}s: only filled {gap - short_by:.2f}s of the "
                        f"requested {gap}s — not enough unused footage left in the video."
                    )

            piece_paths = []
            for j, (s, e) in enumerate(segment_specs):
                piece_path = os.path.join(work_dir, f"hs{i}_part{j}.mp4")
                if _cut_segment(video_path, s, e, piece_path):
                    piece_paths.append(piece_path)

            if not piece_paths:
                print(f"    skipped — nothing usable for this headshot")
                continue

            if len(piece_paths) == 1:
                clip_paths.append(piece_paths[0])
            else:
                clip_path = os.path.join(work_dir, f"hs{i}_full.mp4")
                _concat_clips(piece_paths, clip_path, work_dir, tag=f"hs{i}")
                clip_paths.append(clip_path)

        if not clip_paths:
            raise RuntimeError("No usable headshot clips were produced from the given timestamps.")

        print("Merging all headshot clips...")
        merged_path = os.path.join(work_dir, "merged.mp4")
        _concat_clips(clip_paths, merged_path, work_dir, tag="merged")

        print(f"Cropping/scaling to {export_ratio}...")
        _apply_export_ratio(merged_path, output_path, export_ratio)
        print(f"Done — saved to {output_path}")

    finally:
        for root, _, files in os.walk(work_dir):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass
        try:
            os.rmdir(work_dir)
        except OSError:
            pass

    return {"output_path": output_path, "warnings": warnings}


def _parse_timestamps(raw):
    """'2,5.5,7' -> [2.0, 5.5, 7.0]"""
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build a merged headshot highlight video.")
    parser.add_argument("video", help="Path to the source video file")
    parser.add_argument("timestamps", help="Comma-separated headshot timestamps, e.g. 2,5.5,7")
    parser.add_argument("gap", type=float, help="Clip duration in seconds applied to every headshot")
    parser.add_argument("ratio", choices=list(RATIO_SPECS), help="Export aspect ratio")
    parser.add_argument("output", help="Path to write the final merged video to")
    args = parser.parse_args()

    result = build_headshot_highlight(
        video_path=args.video,
        headshot_timestamps=_parse_timestamps(args.timestamps),
        gap=args.gap,
        export_ratio=args.ratio,
        output_path=args.output,
    )
    print(result)
