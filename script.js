const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

if (!reduceMotion) document.documentElement.classList.add('motion-ready');

const navToggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('#primary-nav');

if (navToggle && nav) {
  document.documentElement.classList.add('nav-ready');

  const closeNav = () => {
    navToggle.setAttribute('aria-expanded', 'false');
    navToggle.setAttribute('aria-label', 'Open navigation');
    nav.classList.remove('is-open');
  };

  navToggle.addEventListener('click', () => {
    const isOpen = navToggle.getAttribute('aria-expanded') === 'true';
    navToggle.setAttribute('aria-expanded', String(!isOpen));
    navToggle.setAttribute('aria-label', isOpen ? 'Open navigation' : 'Close navigation');
    nav.classList.toggle('is-open', !isOpen);
  });

  nav.addEventListener('click', (event) => {
    if (event.target.closest('a')) closeNav();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeNav();
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 860) closeNav();
  });
}

const reveals = [...document.querySelectorAll('.reveal')];

if ('IntersectionObserver' in window && !reduceMotion) {
  reveals.forEach((element) => element.classList.add('reveal-pending'));

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;

      const siblings = [...entry.target.parentElement.querySelectorAll('.reveal-pending:not(.visible)')];
      const index = Math.max(0, siblings.indexOf(entry.target));

      window.setTimeout(() => entry.target.classList.add('visible'), index * 80);
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

  reveals.forEach((element) => observer.observe(element));
}

const themeToggle = document.querySelector('.theme-toggle');

if (themeToggle) {
  const root = document.documentElement;
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

  const activeTheme = () =>
    root.getAttribute('data-theme') || (systemDark.matches ? 'dark' : 'light');

  const describe = () => {
    const dark = activeTheme() === 'dark';
    themeToggle.setAttribute('aria-pressed', String(dark));
    themeToggle.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  };

  describe();

  themeToggle.addEventListener('click', () => {
    const next = activeTheme() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (error) { /* private mode */ }
    describe();
  });

  // Follow the OS while the visitor has not made an explicit choice
  systemDark.addEventListener('change', describe);
}
