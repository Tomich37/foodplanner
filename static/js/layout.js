(function () {
    "use strict";

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
})();

