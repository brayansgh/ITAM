document.addEventListener('DOMContentLoaded', () => {
  function linkSelects(sourceId, targetId, endpointId, param, placeholder) {
    const source = document.getElementById(sourceId);
    const target = document.getElementById(targetId);
    const endpoint = document.getElementById(endpointId);
    if (!source || !target || !endpoint) return;

    let version = 0;
    source.addEventListener('change', async () => {
      const selectedVersion = ++version;
      target.replaceChildren(new Option(placeholder, ''));
      target.disabled = false;
      if (!source.value) return;

      target.disabled = true;
      try {
        const query = new URLSearchParams({[param]: source.value});
        const response = await fetch(endpoint.dataset.url + '?' + query, {credentials: 'same-origin'});
        if (!response.ok) throw new Error('No se pudieron cargar las opciones');
        const data = await response.json();
        if (selectedVersion !== version) return;
        data.results.forEach(item => target.add(new Option(item.name, item.id)));
      } catch (error) {
        if (selectedVersion === version) {
          target.replaceChildren(new Option('No se pudo cargar. Recarga la página.', ''));
        }
      } finally {
        if (selectedVersion === version) target.disabled = false;
      }
    });
  }

  linkSelects('id_group', 'id_category', 'itam-category-endpoint', 'group', 'Selecciona un tipo de activo');
  const status = document.getElementById('id_status');
  const assignment = document.querySelector('.itam-registration-assignment');
  if (status && assignment) {
    const updateAssignment = () => {
      const assigning = status.value === 'ASSIGNED';
      assignment.hidden = !assigning;
      assignment.disabled = !assigning;
    };
    status.addEventListener('change', updateAssignment);
    updateAssignment();
  }

  const catalog = document.getElementById('itam-model-catalog');
  const brand = document.getElementById('id_brand');
  const model = document.getElementById('id_model');
  if (!catalog || !brand || !model) return;

  const models = JSON.parse(catalog.textContent);
  const addModel = document.getElementById('add_id_model');
  const addUrl = addModel && new URL(addModel.href);
  let selectedBrand;
  let popupBrand;

  function showModels(selectedModel) {
    const options = models.filter(item => item.brand_id === brand.value);
    let placeholder = 'Selecciona una marca primero';
    if (brand.value) {
      placeholder = options.length ? 'Selecciona un modelo' : 'Esta marca no tiene modelos asociados';
    }
    model.replaceChildren(new Option(placeholder, ''));
    options.forEach(item => model.add(new Option(item.name, item.id)));
    if (options.some(item => item.id === selectedModel)) model.value = selectedModel;
  }

  function updateBrand() {
    if (selectedBrand === brand.value) return;
    const initialModel = selectedBrand === undefined ? model.value : '';
    selectedBrand = brand.value;
    showModels(initialModel);
    if (addModel) {
      addModel.hidden = !selectedBrand;
      addUrl.searchParams.set('brand', selectedBrand);
      addModel.href = addUrl;
    }
  }

  // Django uses jQuery events when a related-object popup returns a selection.
  django.jQuery(brand).on('change', updateBrand);
  updateBrand();

  if (addModel) {
    addModel.title = 'Crear un modelo para esta marca';
    addModel.setAttribute('aria-label', addModel.title);
    addModel.addEventListener('click', () => { popupBrand = brand.value; });
    django.jQuery(model).on('change', () => {
      const option = model.selectedOptions[0];
      if (!popupBrand || !option?.value || models.some(item => item.id === option.value)) return;
      models.push({id: option.value, name: option.text, brand_id: popupBrand});
      popupBrand = undefined;
      showModels(option.value);
    });
  }
});
