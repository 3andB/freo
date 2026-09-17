/* Progressive product tour; scoped to the persistent workspace page lifecycle. */
(() => {
  'use strict';
  if (!document.body.classList.contains('project-home')) return;
  const scope = window.FreoPage;
  const nav = document.querySelector('.project-nav');
  const menu = nav.querySelector('.project-menu');
  const links = document.getElementById('project-navigation');
  const dialog = document.getElementById('product-lightbox');
  const cards = [...document.querySelectorAll('[data-product-screen]')];
  const slides = cards.filter((card, i) => cards.findIndex(other => other.dataset.productScreen === card.dataset.productScreen) === i);
  const theme = () => document.documentElement.dataset.theme === 'night' ? 'night' : 'day';
  let active = null, opener = null;

  nav.classList.add('enhanced');
  menu.hidden = false;
  function closeMenu(restore = false) {
    links.classList.remove('is-open');
    menu.setAttribute('aria-expanded', 'false');
    if (restore) menu.focus();
  }
  scope.listen(menu, 'click', () => {
    const open = menu.getAttribute('aria-expanded') !== 'true';
    links.classList.toggle('is-open', open);
    menu.setAttribute('aria-expanded', String(open));
  });
  scope.listen(links, 'click', event => { if (event.target.closest('a')) closeMenu(); });
  scope.listen(document, 'keydown', event => {
    if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') closeMenu(true);
  });

  function paintDialog() {
    if (!active) return;
    const image = dialog.querySelector('.project-lightbox-image img');
    image.src = active.dataset[theme() === 'night' ? 'fullNight' : 'fullDay'];
    image.alt = active.querySelector('img').alt;
    image.dataset.phone = String(active.dataset.productScreen === 'player-mobile');
    document.getElementById('product-lightbox-title').textContent = active.dataset.title;
    document.getElementById('product-lightbox-caption').textContent = active.dataset.caption;
    dialog.querySelector('.project-lightbox-image').scrollTo(0, 0);
  }
  function paintTheme() {
    const night = theme() === 'night';
    for (const card of cards) {
      const image = card.querySelector('img');
      image.srcset = image.dataset[night ? 'srcsetNight' : 'srcsetDay'];
      image.src = image.dataset[night ? 'night' : 'day'];
      card.href = card.dataset[night ? 'fullNight' : 'fullDay'];
    }
    if (dialog.open) paintDialog();
  }
  paintTheme();
  scope.listen(window, 'freo:themechange', paintTheme);
  for (const card of cards) {
    scope.listen(card, 'click', event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !dialog.showModal) return;
      event.preventDefault();
      active = card; opener = card;
      paintDialog(); dialog.showModal();
      dialog.querySelector('.project-lightbox-close').focus();
    });
  }
  function advance(delta) {
    const index = slides.findIndex(card => card.dataset.productScreen === active.dataset.productScreen);
    active = slides[(index + delta + slides.length) % slides.length];
    paintDialog();
  }
  scope.listen(dialog.querySelector('.project-lightbox-close'), 'click', () => dialog.close());
  scope.listen(dialog, 'close', () => { opener?.focus({preventScroll: true}); active = null; });
  scope.listen(dialog, 'click', event => {
    if (event.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    }
  });
  for (const button of dialog.querySelectorAll('[data-screen-step]')) {
    scope.listen(button, 'click', () => advance(Number(button.dataset.screenStep)));
  }
  scope.listen(dialog, 'keydown', event => {
    if (event.target.closest('.project-lightbox-image')) return;
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault(); advance(event.key === 'ArrowRight' ? 1 : -1);
    }
  });
  scope.cleanup(() => { if (dialog.open) dialog.close(); });
})();
