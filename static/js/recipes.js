(function () {
    "use strict";

    const filterButtons = document.querySelectorAll("[data-filter-tag]");
    const resetBtn = document.querySelector("[data-reset-tags]");
    const clearSearchBtn = document.querySelector("[data-clear-search]");
    const searchInput = document.getElementById("recipes-search-input");
    const searchForm = document.querySelector("[data-recipes-search]");
    const resultsContainer = document.querySelector("[data-recipes-results]");
    const searchUrl = searchForm?.dataset.searchUrl || "";
    const extraDropdown = document.querySelector("[data-extra-dropdown]");
    const extraDropdownToggle = extraDropdown?.querySelector("[data-extra-dropdown-toggle]");
    const extraDropdownPanel = extraDropdown?.querySelector("[data-extra-dropdown-panel]");
    const extraApplyBtn = extraDropdown?.querySelector("[data-extra-apply]");
    const extraClearBtn = extraDropdown?.querySelector("[data-extra-clear]");
    const extraCountTarget = extraDropdown?.querySelector("[data-extra-selected-count]");
    const extraTagCheckboxes = extraDropdown
        ? Array.from(extraDropdown.querySelectorAll("[data-extra-tag-checkbox]"))
        : [];
    const extraTagValues = (extraDropdown?.dataset.extraTagValues || "")
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
    let searchController;

    if (!searchForm || !resultsContainer) {
        return;
    }

    const buildTarget = (params) => {
        const query = params.toString();
        const basePath = window.location.pathname;
        return query ? `${basePath}?${query}` : basePath;
    };

    const updateHistory = (params) => {
        const target = buildTarget(params);
        window.history?.replaceState?.({}, "", target);
    };

    const getCurrentTags = () => {
        const params = new URLSearchParams(window.location.search);
        return new Set(params.getAll("tags"));
    };

    const applySelection = (tagsSet) => {
        const params = new URLSearchParams(window.location.search);
        params.delete("tags");
        tagsSet.forEach((value) => params.append("tags", value));
        window.location.href = buildTarget(params);
    };

    const buildSearchParams = () => {
        const params = new URLSearchParams();
        getCurrentTags().forEach((value) => params.append("tags", value));
        return params;
    };

    const debounce = (fn, delay = 250) => {
        let timeoutId;
        return (...args) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn(...args), delay);
        };
    };

    const requestSearch = async () => {
        if (!searchUrl) {
            return;
        }
        const params = buildSearchParams();
        const query = (searchInput?.value || "").trim();
        if (query) {
            params.set("q", query);
        }
        updateHistory(params);
        const requestUrl = params.toString() ? `${searchUrl}?${params}` : searchUrl;
        searchController?.abort();
        searchController = new AbortController();
        try {
            const response = await fetch(requestUrl, {
                headers: { "X-Requested-With": "fetch" },
                signal: searchController.signal,
            });
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            resultsContainer.innerHTML = data.html || "";
        } catch (error) {
            if (error.name !== "AbortError") {
                console.error("Ошибка поиска рецептов", error);
            }
        }
    };

    const debouncedSearch = debounce(requestSearch, 250);

    filterButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const value = button.getAttribute("data-filter-tag");
            const tagsSet = getCurrentTags();
            if (tagsSet.has(value)) {
                tagsSet.delete(value);
            } else {
                tagsSet.add(value);
            }
            applySelection(tagsSet);
        });
    });

    resetBtn?.addEventListener("click", () => {
        const params = new URLSearchParams(window.location.search);
        params.delete("tags");
        window.location.href = buildTarget(params);
    });

    const closeExtraDropdown = () => {
        if (!extraDropdown) {
            return;
        }
        extraDropdown.classList.remove("is-open");
        extraDropdownToggle?.setAttribute("aria-expanded", "false");
    };

    const openExtraDropdown = () => {
        if (!extraDropdown) {
            return;
        }
        extraDropdown.classList.add("is-open");
        extraDropdownToggle?.setAttribute("aria-expanded", "true");
    };

    extraDropdownToggle?.addEventListener("click", (event) => {
        event.preventDefault();
        const isOpen = extraDropdown?.classList.contains("is-open");
        if (isOpen) {
            closeExtraDropdown();
        } else {
            openExtraDropdown();
        }
    });

    document.addEventListener("click", (event) => {
        if (!extraDropdown) {
            return;
        }
        if (extraDropdown.contains(event.target)) {
            return;
        }
        closeExtraDropdown();
    });

    document.addEventListener("keydown", (event) => {
        if (!extraDropdown) {
            return;
        }
        if (event.key === "Escape") {
            closeExtraDropdown();
        }
    });

    const updateExtraCount = () => {
        if (!extraCountTarget) {
            return;
        }
        const selectedCount = extraTagCheckboxes.filter((checkbox) => checkbox.checked).length;
        extraCountTarget.textContent = selectedCount ? `(${selectedCount})` : "";
    };

    const applyExtraTags = () => {
        const tagsSet = getCurrentTags();
        if (extraTagValues.length) {
            extraTagValues.forEach((value) => tagsSet.delete(value));
        }
        extraTagCheckboxes.forEach((checkbox) => {
            const value = checkbox.value;
            if (checkbox.checked && value) {
                tagsSet.add(value);
            }
        });
        applySelection(tagsSet);
    };

    extraTagCheckboxes.forEach((checkbox) => {
        checkbox.addEventListener("change", () => {
            updateExtraCount();
        });
    });

    extraApplyBtn?.addEventListener("click", () => {
        closeExtraDropdown();
        applyExtraTags();
    });

    extraClearBtn?.addEventListener("click", () => {
        extraTagCheckboxes.forEach((checkbox) => {
            checkbox.checked = false;
        });
        updateExtraCount();
        closeExtraDropdown();
        applyExtraTags();
    });

    updateExtraCount();

    clearSearchBtn?.addEventListener("click", () => {
        const params = buildSearchParams();
        updateHistory(params);
        if (searchInput) {
            searchInput.value = "";
        }
        debouncedSearch();
    });

    searchForm.addEventListener("submit", (event) => {
        if (!searchInput) {
            return;
        }
        event.preventDefault();
        searchInput.value = searchInput.value.trim();
        requestSearch();
    });

    searchInput?.addEventListener("input", () => {
        debouncedSearch();
    });
})();
