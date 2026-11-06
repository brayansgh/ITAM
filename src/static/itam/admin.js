document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-itam-filter]').forEach(select => select.addEventListener('change', () => {
    window.location.assign(select.value);
  }));
  const toggle = document.querySelector('.itam-menu-toggle');
  if (toggle && window.matchMedia('(max-width: 767px)').matches) {
    document.body.classList.add('itam-nav-collapsed');
    toggle.setAttribute('aria-expanded', 'false');
  }
  if (toggle) toggle.addEventListener('click', () => {
    const collapsed = document.body.classList.toggle('itam-nav-collapsed');
    toggle.setAttribute('aria-expanded', String(!collapsed));
  });
  document.querySelectorAll('[data-itam-tab]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-itam-tab]').forEach(tab => tab.setAttribute('aria-selected', String(tab === button)));
    document.querySelectorAll('[data-itam-panel]').forEach(panel => { panel.hidden = panel.id !== button.dataset.itamTab; });
  }));
  document.querySelectorAll('form').forEach(form => {
    const status = form.querySelector('#id_status');
    if (status && form.id === 'maintenancerecord_form') form.addEventListener('submit', event => {
      if (['COMPLETED', 'CANCELLED'].includes(status.value)) {
        const message = status.value === 'CANCELLED'
          ? '¿Cancelar el ticket? Sus datos y evidencias quedarán de solo consulta.'
          : '¿Completar el ticket? Sus datos y evidencias quedarán de solo consulta. Si es una baja, el activo quedará dado de baja.';
        if (!window.confirm(message)) event.preventDefault();
      }
    });
    if (['asset_form', 'employee_form', 'maintenancerecord_form'].includes(form.id)) {
      let changed = false;
      form.addEventListener('change', () => { changed = true; });
      form.addEventListener('submit', event => { if (!event.defaultPrevented) changed = false; });
      window.addEventListener('beforeunload', event => {
        if (changed) { event.preventDefault(); event.returnValue = ''; }
      });
      form.querySelectorAll('.itam-cancel').forEach(link => link.addEventListener('click', event => {
        if (changed && !window.confirm('Hay cambios sin guardar. ¿Deseas descartarlos?')) event.preventDefault();
        else changed = false;
      }));
    }
  });
});
