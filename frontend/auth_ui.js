(() => {
  const apiBaseUrl = window.JAHVI_API_BASE_URL || '';
  window.JAHVI_API_BASE_URL = apiBaseUrl;
  const userKey = 'jahvi_user';
  const auth = {
    uploadLimitBytes: plan => ({
      free: 300 * 1024 * 1024,
      pro: 1024 * 1024 * 1024,
      proplus: 1.5 * 1024 * 1024 * 1024,
    })[String(plan || 'free').toLowerCase().replace(/[_-]/g, '')] || 300 * 1024 * 1024,
    validateProcessingFiles: async files => {
      const user = await auth.loadUserAndCredits();
      if (!user) return 'Please sign in before processing a video.';
      if (Number(user.credits) < 2) return 'You need at least 2 credits to process a video. Please add credits and try again.';
      const limit = auth.uploadLimitBytes(user.plan);
      const limitLabel = limit >= 1024 * 1024 * 1024 ? `${limit / (1024 * 1024 * 1024)} GB` : `${limit / (1024 * 1024)} MB`;
      const oversized = files.find(file => file && file.size > limit);
      return oversized ? `This file is too large for your plan. The maximum upload is ${limitLabel}.` : null;
    },
    clearSession: () => {
      localStorage.removeItem(userKey);
    },
    saveSession: (data) => { if (data.user) localStorage.setItem(userKey, JSON.stringify(data.user)); },
    loadUserAndCredits: async () => {
      const response = await fetch(`${apiBaseUrl}/api/me`, { credentials: 'include' });
      if (response.status === 401) auth.clearSession();
      if (!response.ok) return null;
      const user = await response.json();
      localStorage.setItem(userKey, JSON.stringify(user));
      updateUser(user);
      return user;
    },
    initialize: async () => {
      const raw = localStorage.getItem(userKey);
      if (raw) updateUser(JSON.parse(raw));
      return auth.loadUserAndCredits();
    },
  };
  function updateUser(user) {
    const name = document.getElementById('userName');
    const avatar = document.getElementById('userAvatar');
    const credits = document.getElementById('creditsLeft');
    const creditsFill = document.getElementById('creditsFill');
    const plan = document.getElementById('planLabel');
    if (name) name.textContent = user.full_name || 'Welcome back';
    if (avatar) avatar.textContent = (user.full_name || '--').split(/\s+/).map(part => part[0]).join('').slice(0, 2).toUpperCase();
    if (credits) credits.textContent = user.credits ?? '–';
    if (creditsFill && Number.isFinite(Number(user.credits))) {
      creditsFill.style.setProperty('--fill-percent', `${Math.min(100, Math.max(0, Number(user.credits) * 10))}%`);
    }
    if (plan) plan.textContent = user.plan ? String(user.plan).replace(/(^|[-_])\w/g, value => value.replace(/[-_]/, '').toUpperCase()) : 'Plan';
  }
  document.addEventListener('click', event => {
    const link = event.target.closest?.('.logout');
    if (!link) return;
    event.preventDefault();
    auth.clearSession();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 2000);
    fetch(`${apiBaseUrl}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
      signal: controller.signal,
    }).finally(() => {
      window.clearTimeout(timeout);
      window.location.replace('index.html');
    });
  }, true);
  window.JahviAuth = auth;
})();
