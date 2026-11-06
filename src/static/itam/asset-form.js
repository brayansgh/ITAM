document.addEventListener('DOMContentLoaded', () => {
  const group = document.getElementById('id_group');
  const category = document.getElementById('id_category');
  if (!group || !category) return;
  let version = 0;
  group.addEventListener('change', async () => {
    const selectedVersion = ++version;
    category.replaceChildren(new Option('Selecciona un tipo de activo', ''));
    category.disabled = true;
    try {
      const endpoint = document.getElementById('itam-category-endpoint');
      if (!endpoint) return;
      const response = await fetch(endpoint.dataset.url + '?group=' + encodeURIComponent(group.value), {credentials:'same-origin'});
      if (!response.ok) throw new Error('No se pudieron cargar los tipos');
      const data = await response.json();
      if (selectedVersion !== version) return;
      data.results.forEach(item => category.add(new Option(item.name, item.id)));
    } catch (error) {
      if (selectedVersion === version) category.replaceChildren(new Option('No se pudo cargar. Recarga la página.', ''));
    } finally {
      if (selectedVersion === version) category.disabled = false;
    }
  });
});
