(function () {
    "use strict";

    const page = document.querySelector(".admin-users");
    if (!page) {
        return;
    }

    const filterButtons = page.querySelectorAll(".filter-btn");
    const cards = Array.from(page.querySelectorAll(".user-card"));
    const searchInput = page.querySelector("#user-search");

    const applyFilters = () => {
        const active =
            page.querySelector(".filter-btn--active")?.dataset.filter || "all";
        const query = (searchInput?.value || "").toLowerCase().trim();
        cards.forEach((card) => {
            const role = card.dataset.role;
            const text = (card.dataset.search || "").toLowerCase();
            const roleMatch = active === "all" || role === active;
            const textMatch = !query || text.includes(query);
            card.style.display = roleMatch && textMatch ? "" : "none";
        });
    };

    filterButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            filterButtons.forEach((b) => b.classList.remove("filter-btn--active"));
            btn.classList.add("filter-btn--active");
            applyFilters();
        });
    });

    searchInput?.addEventListener("input", applyFilters);
})();

