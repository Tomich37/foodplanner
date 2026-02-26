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
    const onlyUnfilledCheckbox = page.querySelector("#prices-only-unfilled");
    const normalize = (value) => (value || "").toLowerCase().replace(/\u0451/g, "\u0435").trim();

    const applyFilter = () => {
        const query = normalize(searchInput.value);
        const onlyUnfilled = Boolean(onlyUnfilledCheckbox && onlyUnfilledCheckbox.checked);
        let visibleCount = 0;

        items.forEach((item) => {
            const text = normalize(item.dataset.search || "");
            const matchesSearch = !query || text.includes(query);
            const isFilled = (item.dataset.priceFilled || "0") === "1";
            const matchesFillFilter = !onlyUnfilled || !isFilled;
            const matches = matchesSearch && matchesFillFilter;
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
    if (onlyUnfilledCheckbox) {
        onlyUnfilledCheckbox.addEventListener("change", applyFilter);
    }
    applyFilter();
})();
