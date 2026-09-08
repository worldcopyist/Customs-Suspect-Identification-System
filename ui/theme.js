// Run before CSS and application startup to avoid a wrong-theme first frame.
(() => {
  const key = 'customs-ui-theme';
  const modes = ['system', 'light', 'dark'];
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { preference = localStorage.getItem(key) || 'system'; } catch {}
  if (!modes.includes(preference)) preference = 'system';
  function apply() {
    const theme = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const select = document.getElementById('theme-select');
    if (select) select.value = preference;
  }
  apply();
  system.addEventListener('change', apply);
  document.addEventListener('DOMContentLoaded', apply);
  document.addEventListener('change', event => {
    if (event.target.id !== 'theme-select' || !modes.includes(event.target.value)) return;
    preference = event.target.value;
    try { localStorage.setItem(key, preference); } catch {}
    apply();
  });
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    preference = modes.includes(event.newValue) ? event.newValue : 'system';
    apply();
  });
})();
