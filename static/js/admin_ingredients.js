(function () {
    "use strict";

    const page = document.querySelector(".admin-tags");
    if (!page) {
        return;
    }

    const canonicalInput = page.querySelector("#canonical-name");
    const canonicalList = page.querySelector("#canonical-name-suggestions");
    const canonicalOptionsNode = page.querySelector("#canonical-name-options-source");

    const parseCanonicalOptions = () => {
        if (!canonicalOptionsNode) {
            return [];
        }
        return Array.from(canonicalOptionsNode.querySelectorAll("option"))
            .map((option) => (option.value || "").trim())
            .filter(Boolean);
    };

    const canonicalOptions = parseCanonicalOptions();
    const normalize = (value) => (value || "").toLowerCase().replace(/ё/g, "е").trim();

    const updateCanonicalSuggestions = () => {
        if (!canonicalInput || !canonicalList) {
            return;
        }

        const minChars = Number(canonicalInput.dataset.suggestMin || 2);
        const limit = Number(canonicalInput.dataset.suggestLimit || 12);
        const query = normalize(canonicalInput.value);

        canonicalList.innerHTML = "";
        if (query.length < minChars) {
            return;
        }

        const startsWithMatches = [];
        const containsMatches = [];

        canonicalOptions.forEach((option) => {
            const normalizedOption = normalize(option);
            if (!normalizedOption.includes(query)) {
                return;
            }
            if (normalizedOption.startsWith(query)) {
                startsWithMatches.push(option);
            } else {
                containsMatches.push(option);
            }
        });

        const matched = startsWithMatches.concat(containsMatches).slice(0, limit);
        matched.forEach((name) => {
            const option = document.createElement("option");
            option.value = name;
            canonicalList.appendChild(option);
        });
    };

    canonicalInput?.addEventListener("input", updateCanonicalSuggestions);
    canonicalInput?.addEventListener("focus", updateCanonicalSuggestions);
    canonicalInput?.addEventListener("blur", () => {
        if (canonicalList) {
            canonicalList.innerHTML = "";
        }
    });

    const searchInput = page.querySelector("#catalog-search");
    if (!searchInput) {
        return;
    }

    const items = Array.from(page.querySelectorAll("[data-catalog-item]"));
    const countNode = page.querySelector("#catalog-search-count");
    const emptyNode = page.querySelector("#catalog-empty-message");

    const applyFilter = () => {
        const query = (searchInput.value || "").toLowerCase().replace(/ё/g, "е").trim();
        let visibleCount = 0;

        items.forEach((item) => {
            const text = (item.dataset.search || "").toLowerCase().replace(/ё/g, "е");
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
