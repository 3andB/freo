/* Runs before CSS paints; stays mounted while Freo replaces page content. */
(() => {
  if (window.FreoTheme) { window.FreoTheme.sync(); return; }
  const key = 'freo.appearance';
  const valid = value => value === 'night' ? 'night' : 'day';
  const read = () => { try { return valid(localStorage.getItem(key)); } catch (_) { return 'day'; } };
  let preference = read();
  function sync() {
    document.querySelectorAll('[data-appearance]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.appearance === preference));
    });
  }
  function apply() {
    const theme = preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme === 'night' ? 'dark' : 'light';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'night' ? '#101f29' : '#f7f8f4');
    sync();
    window.dispatchEvent(new CustomEvent('freo:themechange', {detail: {theme, preference}}));
  }
  window.FreoTheme = {sync};
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-appearance]');
    if (!button) return;
    preference = valid(button.dataset.appearance);
    try { localStorage.setItem(key, preference); } catch (_) { /* Session choice still works. */ }
    apply();
  });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) { preference = read(); apply(); }
  });
  document.addEventListener('DOMContentLoaded', sync);
  apply();
})();
