(() => {
  const key = 'itam-landing-theme';
  const deviceTheme = matchMedia('(prefers-color-scheme: dark)');
  let preference;
  let picker;

  try {
    preference = localStorage.getItem(key);
  } catch {
    // Se puede cambiar de tema durante esta visita sin almacenamiento local.
  }

  function applyTheme() {
    const theme = preference === 'light' || preference === 'dark'
      ? preference
      : (deviceTheme.matches ? 'dark' : 'light');
    document.documentElement.dataset.theme = theme;
    if (picker) picker.setAttribute('aria-checked', String(theme === 'dark'));
  }

  applyTheme();
  deviceTheme.addEventListener('change', applyTheme);
  window.addEventListener('storage', event => {
    if (event.key !== key) return;
    preference = event.newValue;
    applyTheme();
  });

  document.addEventListener('DOMContentLoaded', () => {
    picker = document.getElementById('itam-theme');
    if (!picker) return;
    applyTheme();
    picker.hidden = false;
    picker.addEventListener('click', () => {
      preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      applyTheme();
      try {
        localStorage.setItem(key, preference);
      } catch {
        // El tema seleccionado ya se aplicó a la página.
      }
    });
  });
})();
