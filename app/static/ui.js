/* Перемикач теми, мобільне меню та встановлення застосунку (PWA). */
(function () {
  var KEY = 'santimanos-theme';
  var root = document.documentElement;

  var themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) {
    themeBtn.setAttribute('aria-pressed', root.getAttribute('data-theme') === 'dark' ? 'true' : 'false');
    themeBtn.addEventListener('click', function () {
      var dark = root.getAttribute('data-theme') !== 'dark';
      root.setAttribute('data-theme', dark ? 'dark' : 'light');
      themeBtn.setAttribute('aria-pressed', dark ? 'true' : 'false');
      try { localStorage.setItem(KEY, dark ? 'dark' : 'light'); } catch (e) {}
    });
  }

  var menuBtn = document.getElementById('menu-btn');
  var nav = document.getElementById('nav');
  if (menuBtn && nav) {
    menuBtn.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && nav.classList.contains('open')) {
        nav.classList.remove('open');
        menuBtn.setAttribute('aria-expanded', 'false');
        menuBtn.focus();
      }
    });
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js').catch(function () {}); });
  }

  // Кнопка «Встановити застосунок» з'являється, лише коли браузер дозволяє встановлення.
  var installBtn = document.getElementById('install-btn');
  var installEvent = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    installEvent = e;
    if (installBtn) installBtn.hidden = false;
  });
  if (installBtn) {
    installBtn.addEventListener('click', function () {
      if (!installEvent) return;
      installEvent.prompt();
      installEvent.userChoice.finally(function () { installEvent = null; installBtn.hidden = true; });
    });
  }
  window.addEventListener('appinstalled', function () { if (installBtn) installBtn.hidden = true; });
})();
