document.addEventListener("DOMContentLoaded", function() {
    const tables = document.querySelectorAll("table");
    tables.forEach(table => {
        let reasonIndex = -1;
        const headers = table.querySelectorAll("th");
        headers.forEach((th, index) => {
            if (th.innerText.trim().toUpperCase() === "CHANGE REASON") {
                reasonIndex = index + 1;
                th.style.display = "none";
            }
        });
        if (reasonIndex !== -1) {
            const rows = table.querySelectorAll("tbody tr");
            rows.forEach(row => {
                const cell = row.querySelector(`td:nth-child(${reasonIndex}), th:nth-child(${reasonIndex})`);
                if (cell) cell.style.display = "none";
            });
        }
    });
});
