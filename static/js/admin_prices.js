(function () {
    "use strict";

    const page = document.querySelector(".admin-tags");
    if (!page) {
        return;
    }

    const searchInput = page.querySelector("#prices-search");
    if (!searchInput) {
        return;
    }

    const items = Array.from(page.querySelectorAll("[data-price-item]"));
    const countNode = page.querySelector("#prices-search-count");
    const emptyNode = page.querySelector("#prices-empty-message");
    const normalize = (value) => (value || "").toLowerCase().replace(/ё/g, "е").trim();

    const applyFilter = () => {
        const query = normalize(searchInput.value);
        let visibleCount = 0;

        items.forEach((item) => {
            const text = normalize(item.dataset.search || "");
            const matches = !query || text.includes(query);
            item.style.display = matches ? "" : "none";
            if (matches) {
                visibleCount += 1;
            }
        });

        if (countNode) {
            countNode.textContent = String(visibleCount);
        }
        if (emptyNode) {
            emptyNode.style.display = visibleCount ? "none" : "";
        }
    };

    searchInput.addEventListener("input", applyFilter);
    applyFilter();
})();
