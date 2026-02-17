(function () {
    "use strict";

    const initNavigation = () => {
        const navToggle = document.querySelector("[data-nav-toggle]");
        const navMenu = document.querySelector("[data-nav-menu]");
        if (!navToggle || !navMenu) {
            return;
        }
        navToggle.addEventListener("click", () => {
            navMenu.classList.toggle("is-open");
            navToggle.classList.toggle("is-active");
        });
        window.addEventListener("resize", () => {
            if (window.innerWidth > 768) {
                navMenu.classList.remove("is-open");
                navToggle.classList.remove("is-active");
            }
        });
    };

    const initBannedModal = () => {
        const body = document.body;
        if (!body || !body.dataset.userBanned) {
            return;
        }
        const modal = document.getElementById("banned-modal");
        if (!modal) {
            return;
        }
        const openModal = () => {
            modal.classList.add("is-visible");
            modal.setAttribute("aria-hidden", "false");
        };
        const closeModal = () => {
            modal.classList.remove("is-visible");
            modal.setAttribute("aria-hidden", "true");
        };
        modal.querySelectorAll("[data-banned-modal-close]").forEach((btn) => {
            btn.addEventListener("click", () => closeModal());
        });
        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                closeModal();
            }
        });
        document.querySelectorAll("[data-banned-create]").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                openModal();
            });
        });
    };

    initNavigation();
    initBannedModal();
})();
