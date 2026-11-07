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
  const returnPdfKey = 'itam-return-pdf';
  const pendingPdfTab = sessionStorage.getItem(returnPdfKey);
  if (pendingPdfTab) {
    sessionStorage.removeItem(returnPdfKey);
    const pdfLink = document.querySelector('[data-itam-return-pdf]');
    const tab = window.open(pdfLink?.href || '', pendingPdfTab);
    if (tab && !pdfLink) tab.close();
  }
  const tokenEndpoint = document.querySelector('meta[name="itam-form-token-url"]')?.content;
  document.querySelectorAll('form').forEach(form => {
    const trackChanges = ['asset_form', 'employee_form', 'maintenancerecord_form'].includes(form.id);
    let changed = false;
    let refreshing = false;
    let refreshed = false;
    if (trackChanges) {
      form.addEventListener('change', () => { changed = true; });
      window.addEventListener('beforeunload', event => {
        if (changed) { event.preventDefault(); event.returnValue = ''; }
      });
      form.querySelectorAll('.itam-cancel').forEach(link => link.addEventListener('click', event => {
        if (changed && !window.confirm('Hay cambios sin guardar. ¿Deseas descartarlos?')) event.preventDefault();
        else changed = false;
      }));
    }
    form.addEventListener('submit', async event => {
      if (event.defaultPrevented) return;
      if (refreshed) { refreshed = false; changed = false; return; }
      if (refreshing) { event.preventDefault(); return; }
      const status = form.querySelector('#id_status');
      const completingDecommission = status?.value === 'COMPLETED' && form.querySelector('[data-itam-decommission]');
      if (status && form.id === 'maintenancerecord_form' && !completingDecommission && ['COMPLETED', 'CANCELLED'].includes(status.value)) {
        const message = status.value === 'CANCELLED'
          ? '¿Cancelar el ticket? Sus datos y evidencias quedarán de solo consulta.'
          : '¿Completar el ticket? Sus datos y evidencias quedarán de solo consulta. Si es una baja, el activo quedará dado de baja.';
        if (!window.confirm(message)) { event.preventDefault(); return; }
      }
      let returnTab;
      if (form.hasAttribute('data-itam-return-form')) {
        const name = 'itam-return-' + Date.now();
        returnTab = window.open('', name);
        if (returnTab) {
          returnTab.document.body.textContent = 'Generando el acta de devolución…';
          sessionStorage.setItem(returnPdfKey, name);
        }
      }
      const tokens = form.querySelectorAll('input[name="csrfmiddlewaretoken"]');
      if (!tokenEndpoint || form.method.toLowerCase() !== 'post' || !tokens.length || new URL(form.action, location.href).origin !== location.origin) {
        changed = false;
        return;
      }
      event.preventDefault();
      refreshing = true;
      form.setAttribute('aria-busy', 'true');
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 10000);
      let ready = false;
      try {
        const response = await fetch(tokenEndpoint, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
        if (!response.ok || response.redirected) throw new Error('Sesión no disponible');
        const data = await response.json();
        if (typeof data.csrfToken !== 'string' || !/^[a-zA-Z0-9]{64}$/.test(data.csrfToken)) throw new Error('Token no válido');
        tokens.forEach(token => { token.value = data.csrfToken; });
        form.querySelector('.itam-csrf-error')?.remove();
        ready = true;
      } catch (error) {
        let notice = form.querySelector('.itam-csrf-error');
        if (!notice) {
          notice = document.createElement('p');
          notice.className = 'errornote itam-csrf-error';
          notice.setAttribute('role', 'alert');
          form.prepend(notice);
        }
        notice.textContent = 'No se pudo validar la sesión. Tus datos siguen en el formulario. Si la sesión terminó, inicia sesión en otra pestaña y vuelve a pulsar Guardar.';
        notice.scrollIntoView({block: 'nearest'});
      } finally {
        window.clearTimeout(timeout);
        refreshing = false;
        form.removeAttribute('aria-busy');
        if (!ready && returnTab) {
          returnTab.close();
          sessionStorage.removeItem(returnPdfKey);
        }
      }
      if (ready) {
        refreshed = true;
        if (event.submitter) form.requestSubmit(event.submitter);
        else form.requestSubmit();
        // Si la validación nativa impidió el envío, no reutilizar el token después.
        refreshed = false;
      }
    });
  });
});
