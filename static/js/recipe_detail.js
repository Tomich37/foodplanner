(function () {
    "use strict";

    const detailPage = document.querySelector(".recipe-detail");
    if (!detailPage) {
        return;
    }

    const stepImages = detailPage.querySelectorAll(".recipe-step-item__image");
    const modalTemplate = `
        <div class="image-modal" id="image-modal">
            <button class="image-modal__close" aria-label="Закрыть">&times;</button>
            <img src="" alt="Просмотр изображения" />
        </div>
    `;
    let modal;

    const getModal = () => {
        if (modal) {
            return modal;
        }
        document.body.insertAdjacentHTML("beforeend", modalTemplate);
        modal = document.getElementById("image-modal");
        modal.addEventListener("click", (event) => {
            if (
                event.target === modal ||
                event.target.classList.contains("image-modal__close")
            ) {
                modal.classList.remove("image-modal--visible");
            }
        });
        return modal;
    };

    const openModal = (src) => {
        const modalEl = getModal();
        const img = modalEl.querySelector("img");
        img.src = src;
        modalEl.classList.add("image-modal--visible");
    };

    stepImages.forEach((img) => {
        img.style.cursor = "zoom-in";
        img.addEventListener("click", () => openModal(img.dataset.full));
    });

    const toggleInput = document.getElementById("toggle-view");
    const toggleLabel = detailPage.querySelector(".toggle__label");
    const toggleWrapper = toggleInput?.closest(".checkbox-ios");

    window.addEventListener("keyup", (event) => {
        if (event.key === "Tab" && document.activeElement === toggleInput && toggleWrapper) {
            toggleWrapper.classList.add("focused");
        }
    });
    toggleInput?.addEventListener("focusout", () => toggleWrapper?.classList.remove("focused"));

    const updateToggleText = () => {
        if (!toggleLabel || !toggleInput) return;
        toggleLabel.textContent = toggleInput.checked
            ? "Показать все изображения"
            : "Минималистичный вид";
    };
    updateToggleText();

    toggleInput?.addEventListener("change", () => {
        updateToggleText();
        toggleInput.closest("form")?.submit();
    });
})();

