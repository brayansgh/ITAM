(() => {
    const items = document.getElementById("delivery-items");
    const template = document.getElementById("delivery-item-template");
    const total = document.getElementById("id_activos-TOTAL_FORMS");
    const add = document.getElementById("delivery-add-item");
    const $ = django.jQuery;

    const updateAddButton = () => {
        add.disabled = items.childElementCount >= Number(items.dataset.maxItems);
    };

    add.addEventListener("click", () => {
        let index = 0;
        while (document.getElementById(`id_activos-${index}-asset`)) index += 1;
        items.insertAdjacentHTML("beforeend", template.innerHTML.replaceAll("__prefix__", index));
        total.value = Math.max(Number(total.value), index + 1);
        const select = $(items.lastElementChild).find(".admin-autocomplete");
        select.djangoAdminSelect2();
        select.select2("open");
        updateAddButton();
    });

    items.addEventListener("click", (event) => {
        const remove = event.target.closest("[data-remove-item]");
        if (!remove) return;

        const row = remove.closest("[data-delivery-item]");
        $(row).find(".select2-hidden-accessible").select2("destroy");
        row.remove();
        // Django permite índices vacíos, por lo que conservamos los IDs de los widgets activos.
        while (Number(total.value) > 0
                && !document.getElementById(`id_activos-${Number(total.value) - 1}-asset`)) {
            total.value = Number(total.value) - 1;
        }
        updateAddButton();
        add.focus();
    });

    updateAddButton();
})();
