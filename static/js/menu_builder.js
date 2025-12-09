(function () {
    "use strict";

    const pickers = document.querySelectorAll("[data-picker]");
    if (!pickers.length) {
        return;
    }

    pickers.forEach((picker) => {
        const valueInput = picker.querySelector("[data-picker-value]");
        const optionsBox = picker.querySelector("[data-picker-options]");
        const searchInput = picker.querySelector("[data-picker-search]");
        if (!valueInput || !optionsBox) {
            return;
        }

        const setActive = (targetId) => {
            valueInput.value = String(targetId);
            optionsBox
                .querySelectorAll("[data-picker-option]")
                .forEach((btn) => btn.classList.toggle("is-active", btn.dataset.id === String(targetId)));
        };

        optionsBox.querySelectorAll("[data-picker-option]").forEach((btn) => {
            btn.addEventListener("click", () => {
                setActive(btn.dataset.id);
            });
        });

        searchInput?.addEventListener("input", () => {
            const query = searchInput.value.trim().toLowerCase();
            optionsBox.querySelectorAll("[data-picker-option]").forEach((btn) => {
                const title = btn.dataset.title || "";
                btn.style.display = title.includes(query) ? "block" : "none";
            });
        });
    });
})();

