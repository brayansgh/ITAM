const actDialog = document.getElementById('act-selector-dialog');

if (actDialog && typeof actDialog.showModal === 'function') {
  const menu = document.getElementById('act-pdf-actions');
  actDialog.append(document.getElementById('act-selector'));
  document.querySelectorAll('[data-open-act-selector]').forEach(link => {
    link.addEventListener('click', event => {
      event.preventDefault();
      if (menu) menu.open = false;
      actDialog.showModal();
    });
  });
  document.getElementById('dismiss-act-selector').addEventListener('click', event => {
    event.preventDefault();
    actDialog.close();
  });
  actDialog.addEventListener('close', () => {
    const trigger = menu?.querySelector('summary') ?? document.querySelector('[data-open-act-selector]');
    trigger?.focus();
  });
  if (actDialog.hasAttribute('data-open-on-load')) actDialog.showModal();
}
