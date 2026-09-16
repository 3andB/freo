/* Runs before CSS paints; stays mounted while Freo replaces page content. */
(() => {
  if (window.FreoTheme) { window.FreoTheme.sync(); return; }
  const key = 'freo.appearance';
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const valid = value => ['day', 'night', 'system'].includes(value) ? value : 'system';
  const read = () => { try { return valid(localStorage.getItem(key)); } catch (_) { return 'system'; } };
  let preference = read();
  function sync() {
    document.querySelectorAll('[data-appearance]').forEach(select => { select.value = preference; });
  }
  function apply() {
    const theme = preference === 'system' ? (system.matches ? 'night' : 'day') : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme === 'night' ? 'dark' : 'light';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'night' ? '#101f29' : '#f7f8f4');
    sync();
    window.dispatchEvent(new CustomEvent('freo:themechange', {detail: {theme, preference}}));
  }
  window.FreoTheme = {sync};
  document.addEventListener('change', event => {
    if (!event.target.matches('[data-appearance]')) return;
    preference = valid(event.target.value);
    try { localStorage.setItem(key, preference); } catch (_) { /* Session choice still works. */ }
    apply();
  });
  system.addEventListener('change', () => { if (preference === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) { preference = read(); apply(); }
  });
  document.addEventListener('DOMContentLoaded', sync);
  apply();
})();
