(function () {
    "use strict";

    const stepsWrapper = document.getElementById("steps-wrapper");
    const addStepBtn = document.getElementById("add-step-btn");
    const ingredientsWrapper = document.getElementById("ingredients-wrapper");
    const addIngredientBtn = document.getElementById("add-ingredient-btn");
    const tagButtons = document.querySelectorAll("[data-tag-toggle]");
    const tagDropdown = document.querySelector("[data-tag-dropdown]");
    const tagDropdownToggle = tagDropdown?.querySelector("[data-tag-dropdown-toggle]");
    const tagDropdownPanel = tagDropdown?.querySelector("[data-tag-dropdown-panel]");
    const tagDropdownClose = tagDropdown?.querySelector("[data-tag-dropdown-close]");
    const tagDropdownCount = tagDropdown?.querySelector("[data-tag-dropdown-count]");
    const tagDropdownCheckboxes = tagDropdown
        ? Array.from(tagDropdown.querySelectorAll("[data-tag-dropdown-checkbox]"))
        : [];

    if (!stepsWrapper || !ingredientsWrapper) {
        return;
    }

    const isEditForm = Boolean(
        document.querySelector("input[name='existing_step_images']")
    );
    let stepCount = stepsWrapper.querySelectorAll(".recipe-step").length || 0;

    const createStepTemplate = (index) => {
        const existingHidden = isEditForm
            ? `<input type="hidden" name="existing_step_images" value="" />`
            : "";
        return `
            <div class="form-group">
                <label>Шаг ${index}</label>
                <textarea name="steps" rows="3" required placeholder="Опишите шаг ${index}"></textarea>
            </div>
            ${existingHidden}
            <div class="form-group">
                <label>Фото шага (опционально)</label>
                <input type="file" name="step_images" accept="image/*" />
            </div>
        `;
    };

    addStepBtn?.addEventListener("click", () => {
        stepCount += 1;
        const stepEl = document.createElement("div");
        stepEl.className = "recipe-step";
        stepEl.dataset.stepIndex = String(stepCount);
        stepEl.innerHTML = createStepTemplate(stepCount);
        stepsWrapper.appendChild(stepEl);
    });

    const attachAutocomplete = (row) => {
        const input = row.querySelector(".ingredient-name");
        const unitSelect = row.querySelector("select[name='ingredient_units']");
        const list = row.querySelector(".autocomplete__list");
        if (!input || !list) return;

        let currentSuggestions = [];

        const hideList = (event) => {
            if (!row.contains(event.target)) {
                list.innerHTML = "";
                list.style.display = "none";
            }
        };

        const applySuggestion = (item) => {
            input.value = item.name;
            if (unitSelect) {
                unitSelect.value = item.unit || "g";
            }
            currentSuggestions = [];
            list.innerHTML = "";
            list.style.display = "none";
        };

        const renderList = () => {
            list.innerHTML = "";
            if (!currentSuggestions.length) {
                list.style.display = "none";
                return;
            }
            currentSuggestions.forEach((item) => {
                const option = document.createElement("button");
                option.type = "button";
                option.textContent = item.name;
                option.dataset.unit = item.unit;
                option.addEventListener("click", () => applySuggestion(item));
                list.appendChild(option);
            });
            list.style.display = "flex";
        };

        input.addEventListener("input", async () => {
            const query = input.value.trim();
            if (query.length < 2) {
                currentSuggestions = [];
                renderList();
                return;
            }
            try {
                const resp = await fetch(`/recipes/ingredients?q=${encodeURIComponent(query)}`);
                const data = await resp.json();
                currentSuggestions = data.items || [];
                renderList();
            } catch (error) {
                currentSuggestions = [];
                renderList();
            }
        });

        input.addEventListener("keydown", (event) => {
            if (event.key === "Tab" && currentSuggestions.length) {
                event.preventDefault();
                applySuggestion(currentSuggestions[0]);
            }
        });

        document.addEventListener("click", hideList);
    };

    document.querySelectorAll(".ingredient-row").forEach(attachAutocomplete);

    addIngredientBtn?.addEventListener("click", () => {
        const row = document.createElement("div");
        row.className = "ingredient-row";
        row.innerHTML = `
            <div class="form-group">
                <label>Продукт</label>
                <div class="autocomplete">
                    <input type="text" name="ingredient_names" class="ingredient-name" required placeholder="Название ингредиента" autocomplete="off" />
                    <div class="autocomplete__list"></div>
                </div>
            </div>
            <div class="form-group">
                <label>Количество</label>
                <input type="number" name="ingredient_amounts" step="0.01" min="0" required placeholder="0" />
            </div>
            <div class="form-group">
                <label>Ед. изм.</label>
                <select name="ingredient_units">
                    <option value="g" selected>граммы</option>
                    <option value="ml">миллилитры</option>
                    <option value="tbsp">ст. л.</option>
                    <option value="tsp">ч. л.</option>
                    <option value="pcs">штуки</option>
                    <option value="taste">по вкусу</option>
                </select>
            </div>
        `;
        ingredientsWrapper.appendChild(row);
        attachAutocomplete(row);
    });

    tagButtons.forEach((button) => {
        const inputId = button.getAttribute("data-target");
        const input = document.getElementById(inputId);
        if (!input) {
            return;
        }
        const syncState = () => {
            button.classList.toggle("tag-button--active", input.checked);
        };
        syncState();
        button.addEventListener("click", () => {
            input.checked = !input.checked;
            syncState();
        });
    });

    const updateTagDropdownCount = () => {
        if (!tagDropdownCount) {
            return;
        }
        const checked = tagDropdownCheckboxes.filter((checkbox) => checkbox.checked).length;
        tagDropdownCount.textContent = checked ? `(${checked})` : "";
    };

    const closeTagDropdown = () => {
        if (!tagDropdown) {
            return;
        }
        tagDropdown.classList.remove("is-open");
        tagDropdownToggle?.setAttribute("aria-expanded", "false");
    };

    const openTagDropdown = () => {
        if (!tagDropdown) {
            return;
        }
        tagDropdown.classList.add("is-open");
        tagDropdownToggle?.setAttribute("aria-expanded", "true");
    };

    tagDropdownToggle?.addEventListener("click", (event) => {
        event.preventDefault();
        const isOpen = tagDropdown.classList.contains("is-open");
        if (isOpen) {
            closeTagDropdown();
        } else {
            openTagDropdown();
        }
    });

    tagDropdownClose?.addEventListener("click", () => {
        closeTagDropdown();
    });

    document.addEventListener("click", (event) => {
        if (!tagDropdown) {
            return;
        }
        if (tagDropdown.contains(event.target)) {
            return;
        }
        closeTagDropdown();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeTagDropdown();
        }
    });

    tagDropdownCheckboxes.forEach((checkbox) => {
        checkbox.addEventListener("change", () => {
            updateTagDropdownCount();
        });
    });

    updateTagDropdownCount();
})();
