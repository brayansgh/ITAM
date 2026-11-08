const passwordToggle = document.querySelector('[data-itam-password-toggle]');

if (passwordToggle) {
  const password = document.getElementById(passwordToggle.getAttribute('aria-controls'));
  if (password) {
    passwordToggle.hidden = false;
    passwordToggle.addEventListener('click', () => {
      const visible = password.type === 'password';
      password.type = visible ? 'text' : 'password';
      passwordToggle.setAttribute('aria-pressed', String(visible));
    });
  }
}
