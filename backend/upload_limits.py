from pathlib import Path
import uuid

from fastapi import HTTPException, status


PLAN_UPLOAD_LIMITS = {
    "free": 300 * 1024 * 1024,
    "pro": 1024 * 1024 * 1024,
    "proplus": int(1.5 * 1024 * 1024 * 1024),
}
CHUNK_SIZE = 1024 * 1024
CREDIT_COST = 2


def max_upload_bytes(plan):
    normalized_plan = str(plan or "free").lower().replace("_", "").replace("-", "")
    return PLAN_UPLOAD_LIMITS.get(normalized_plan, PLAN_UPLOAD_LIMITS["free"])


def friendly_size(byte_count):
    if byte_count >= 1024 * 1024 * 1024:
        return f"{byte_count / (1024 * 1024 * 1024):.1f} GB"
    return f"{byte_count / (1024 * 1024):.0f} MB"


def require_processing_credits(db, user):
    locked_user = db.query(type(user)).filter(type(user).id == user.id).with_for_update().one()
    if locked_user.credits < CREDIT_COST:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="You need at least 2 credits to process a video. Please add credits and try again.",
        )
    return locked_user


def save_upload_in_chunks(upload, directory, allowed_extensions, plan):
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(status_code=415, detail="Unsupported upload format")

    limit = max_upload_bytes(plan)
    destination = Path(directory) / f"jahvi_upload_{uuid.uuid4()}{suffix}"
    bytes_written = 0
    try:
        with destination.open("wb") as output:
            while chunk := upload.file.read(CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > limit:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"This file is too large for your {plan} plan. The maximum upload is {friendly_size(limit)}.",
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination