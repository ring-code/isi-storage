/**
 * A universal library for dynamically rendering all cards related to
 * Product SKUs and Product Units.
 *
 * It uses the DynamicInputs.js library for rendering individual input types.
 */
const ProductFormManager = {
    // Stores the data fetched from the API
    data: {},
    // Stores references to the DOM container elements
    containers: {},
    // Stores existing values for pre-filling fields in edit mode
    existingValues: {},
    // Stores the ID of the current entity being edited/created (e.g., product_id, category_id)
    currentEntityId: null,

    /**
     * Initializes the manager for forms where a select element triggers the load.
     * @param {string} urlTemplate - The URL template for the API endpoint (e.g., /api/category/{ID}, /api/product/{ID}).
     * @param {string} idPlaceholder - The placeholder in the URL template (e.g., 'CATEGORY_ID', 'PRODUCT_ID').
     * @param {string} triggerElementId - The ID of the <select> element that triggers the AJAX call.
     * @param {object} containerIds - A map of card names to their container element IDs.
     * @param {object} existingValues - A map of existing values for edit forms.
     * @param {string} dynamicRootContainerId - The ID of the main container that holds all dynamic fields.
     */
    init: function(urlTemplate, idPlaceholder, triggerElementId, containerIds, existingValues = {}, dynamicRootContainerId) {
        this.urlTemplate = urlTemplate;
        this.idPlaceholder = idPlaceholder;
        this.containers = containerIds;
        this.existingValues = existingValues;
        this.containers.dynamicRoot = dynamicRootContainerId; // Ensure dynamicRoot is set

        const triggerElement = document.getElementById(triggerElementId);
        if (triggerElement) {
            triggerElement.addEventListener('change', async () => {
                const selectedId = triggerElement.value;
                this.currentEntityId = selectedId;
                if (selectedId && selectedId !== '__None') {
                    const finalUrl = this.urlTemplate.replace(this.idPlaceholder, selectedId);
                    await this.fetchAndRender(finalUrl);
                } else {
                    this.hideAll();
                }
            });
        }
        // If an initial value is already selected (e.g., on page load for a dropdown)
        if (triggerElement && triggerElement.value && triggerElement.value !== '__None') {
            this.currentEntityId = triggerElement.value;
            const finalUrl = this.urlTemplate.replace(this.idPlaceholder, this.currentEntityId);
            this.fetchAndRender(finalUrl);
        }
    },
    
    /**
     * Initializes the manager for forms that load data directly on page load (e.g., SKU edit page).
     * @param {string} initialDataUrl - The direct URL to fetch initial data.
     * @param {object} containerIds - A map of card names to their container element IDs.
     * @param {object} existingValues - A map of existing values for edit forms.
     * @param {string} dynamicRootContainerId - The ID of the main container that holds all dynamic fields.
     */
    initOnLoad: async function(initialDataUrl, containerIds, existingValues = {}, dynamicRootContainerId) {
        this.containers = containerIds;
        this.existingValues = existingValues;
        this.containers.dynamicRoot = dynamicRootContainerId; // Ensure dynamicRoot is set
        await this.fetchAndRender(initialDataUrl);
    },

    /**
     * Fetches data from the API and calls the master render function.
     */
    fetchAndRender: async function(url) {
        const dynamicRootEl = document.getElementById(this.containers.dynamicRoot);
        if (dynamicRootEl) dynamicRootEl.style.display = 'none'; // Hide while loading

        // Clear any previous error messages
        if (this.containers.messageContainer) {
            const msgContainer = document.getElementById(this.containers.messageContainer);
            if (msgContainer) msgContainer.innerHTML = '';
        }
        
        try {
            const response = await fetch(url);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || 'Network response was not ok');
            }
            this.data = await response.json();
            
            // Show the container and render all the cards
            if (dynamicRootEl) dynamicRootEl.style.display = 'block';
            this.renderAll();

        } catch (error) {
            console.error("Failed to fetch details:", error);
            if (this.containers.messageContainer) {
                const msgContainer = document.getElementById(this.containers.messageContainer);
                if (msgContainer) {
                    msgContainer.innerHTML = `<div class="alert alert-danger mt-3">Error loading details: ${error.message || 'Please try again.'}</div>`;
                }
            }
            this.hideAll(); // Ensure dynamic fields are hidden on error
        }
    },

    /**
     * Master render function that calls all individual card renderers.
     */
    renderAll: function() {
        // Core Details (product_create/edit SKU form)
        if (this.containers.coreDetails) this.renderCoreDetails();
        
        // Serial Numbers (batch/single unit create form)
        if (this.containers.serialNumbers) { 
            this.renderSerialNumbers();
            this.updateSerialPreview(); 
        }

        // Production cost(all forms)
        if (this.containers.financials) this.renderFinancials();
        
        // Specifications (product_create/edit SKU & single unit create)
        if (this.containers.specifications) this.renderSpecifications();
        
        // Attributes (product_create/edit SKU & single unit create)
        if (this.containers.attributes) this.renderAttributes();
        
        // Commercial Grades (batch/single unit create/edit form)
        if (this.containers.commercialGrades && this.existingValues.isUnitCreate) {
            this.renderCommercialGrades();
        }
        
        // --- Live preview updates for serial numbers ---
        this.updateSerialPreview();
    },

    /**
     * Hides all dynamic containers.
     */
    hideAll: function() {
        const dynamicRootEl = document.getElementById(this.containers.dynamicRoot);
        if (dynamicRootEl) dynamicRootEl.style.display = 'none';
        // Clear any previous error messages
        if (this.containers.messageContainer) {
            const msgContainer = document.getElementById(this.containers.messageContainer);
            if (msgContainer) msgContainer.innerHTML = '';
        }
    },

    // --- INDIVIDUAL CARD RENDERERS ---

    // This section is primarily for the create/edit SKU page's "Core Details"
    renderCoreDetails: function() {
        // Name field for new SKUs
        const nameInput = document.getElementById(this.containers.coreDetails.name);
        if (nameInput && !this.existingValues.name && this.data.category_name) {
            // Suggest a name based on category if creating a new product
            nameInput.value = this.data.category_name;
        }
    },

    // This section is for batch/single unit creation forms (Serial Number Details)
    renderSerialNumbers: function() {
        const prefixInput = document.getElementById(this.containers.serialNumbers.prefix);
        const suffixInput = document.getElementById(this.containers.serialNumbers.suffix);
        const startNumberInput = document.getElementById(this.containers.serialNumbers.startNumber); // Batch create
        const valueInput = document.getElementById(this.containers.serialNumbers.value); // Single create
        const serialPreviewEl = document.getElementById(this.containers.serialNumbers.preview);

        if (prefixInput) prefixInput.value = this.data.serial_number_prefix || '';

        // For batch create, suggest the next available serial number part
        if (startNumberInput) {
            startNumberInput.value = this.data.next_serial_suggestion ? this.data.next_serial_suggestion.split(/[-_]/).pop() : '1';
        }
        // For single create, clear the value input
        if (valueInput) valueInput.value = '';

        // Ensure listeners are attached for live preview
        if (suffixInput && !suffixInput.__listenerAdded) {
            suffixInput.addEventListener('input', () => this.updateSerialPreview());
            suffixInput.__listenerAdded = true;
        }
        if (startNumberInput && !startNumberInput.__listenerAdded) {
            startNumberInput.addEventListener('input', () => this.updateSerialPreview());
            startNumberInput.__listenerAdded = true;
        }
        if (valueInput && !valueInput.__listenerAdded) {
            valueInput.addEventListener('input', () => this.updateSerialPreview());
            valueInput.__listenerAdded = true;
        }
    },

    renderFinancials: function() {
        const costInput = document.getElementById(this.containers.financials.cost);
        if (costInput && this.data.standard_production_cost !== undefined) {
            costInput.value = this.data.standard_production_cost;
        }
    },

    renderSpecifications: function() {
        const container = document.getElementById(this.containers.specifications);
        if (!container) return;
        container.innerHTML = '';

        if (!this.data.specifications || this.data.specifications.length === 0) {
            container.innerHTML = '<p class="text-muted"><em>No specifications defined.</em></p>';
            return;
        }

        this.data.specifications.forEach(spec => {
            
            let currentValue;
            const overrideValue = this.existingValues.specs?.[spec.id]; // The override for this entity (SKU or Unit)

            if (overrideValue !== undefined) {
                // Priority 1: ALWAYS use a specific override if it exists.
                // This applies to both Edit SKU and Edit Unit.
                currentValue = overrideValue;
            } else if (this.existingValues.isUnitCreate) {
                // Priority 2: On Unit CREATE page, inherit from the parent SKU's final value.
                currentValue = spec.value;
            } else {
                // Priority 3: On SKU CREATE/EDIT pages, inherit from the category's default.
                currentValue = spec.default_value;
            }

            const isAbstract = spec.is_abstract;
            const isLocked = (overrideValue !== undefined);

            // The "default" to revert to is always the direct parent's value.
            // For a Unit, that's the SKU's value. For a SKU, that's the Category's value.
            const defaultValueForRevert = this.existingValues.isUnitCreate ? spec.value : spec.default_value;
            const defaultValueAttribute = `data-default-value='${JSON.stringify(defaultValueForRevert)}'`;
            
            const group = document.createElement('div');
            group.className = 'form-group';
            group.innerHTML = `
                <label class="form-label">${spec.name} ${isAbstract && this.existingValues.isUnitCreate ? '<span class="text-danger">*</span>' : ''}</label>
                <div class="d-flex align-items-center">
                    <div class="flex-grow-1" id="spec-input-${spec.id}"></div>
                    ${!spec.is_final ? `
                        <input type="hidden" name="spec_lock_${spec.id}" value="${isLocked ? 'locked' : 'unlocked'}">
                        <span class="lock-icon ${isLocked ? 'locked' : ''}" 
                            data-spec-id="${spec.id}" 
                            ${defaultValueAttribute}
                            title="${isLocked ? 'Specific override. Click to revert to inherited value.' : 'Inherited value. Click to set a specific override.'}">
                            ${isLocked ? '🔒' : '🔓'}
                        </span>
                    ` : ''}
                </div>
                ${spec.is_final ? '<small class="text-warning">Value is final and cannot be changed.</small>' : ''}
            `;
            container.appendChild(group);

            const inputContainer = document.getElementById(`spec-input-${spec.id}`);
            if (spec.option_list) {
                DynamicInputs.renderFromOptionList(inputContainer, spec.option_list, currentValue, `spec_${spec.id}`);
            } else if (spec.data_type) {
                DynamicInputs.renderSingleInput(inputContainer, spec.data_type, currentValue, `spec_${spec.id}`);
            }
            
            if (spec.is_final) {
                inputContainer.querySelectorAll('input, select, textarea').forEach(el => el.disabled = true);
            }
            if (isAbstract && this.existingValues.isUnitCreate) {
                inputContainer.querySelectorAll('input, select, textarea').forEach(el => el.required = true);
            }
        });

        if (!container.__lockListenerAdded) {
            container.addEventListener('click', (e) => this.handleSpecLockToggle(e));
            container.__lockListenerAdded = true;
        }
    },


    renderAttributes: function() {
        const container = document.getElementById(this.containers.attributes);
        if (!container) return;
        container.innerHTML = '';

        // The API sends 'unlinked_attributes' for unit creation and 'attributes' for SKU creation.
        // We need to handle both possibilities.
        const attributesToRender = this.data.unlinked_attributes || this.data.attributes;

        if (!attributesToRender || attributesToRender.length === 0) {
            container.innerHTML = '<p class="text-muted"><em>No attributes available.</em></p>';
            return;
        }

        attributesToRender.forEach(attr => {
            const currentValue = this.existingValues.attrs?.[attr.id] || '';
            const group = document.createElement('div');
            group.className = 'form-group';
            group.innerHTML = `<label class="form-label">${attr.name}</label>`;
            
            // This is the div that will hold the actual input/select/radio
            const inputContainer = document.createElement('div');
            group.appendChild(inputContainer);
            
            // Append the whole group to the main container
            container.appendChild(group);

            // Check if the attribute has an option_list and call the correct renderer.
            if (attr.option_list) {
                 DynamicInputs.renderFromOptionList(inputContainer, attr.option_list, currentValue, `attr_${attr.id}`);
            } else if (attr.data_type) {
                 DynamicInputs.renderSingleInput(inputContainer, attr.data_type, currentValue, `attr_${attr.id}`);
            }
        });
    },
    
    renderCommercialGrades: function() {
        const rentalSelect = document.getElementById(this.containers.commercialGrades.rental);
        const saleSelect = document.getElementById(this.containers.commercialGrades.sale);

        if (rentalSelect) this.updateSelectOptions(rentalSelect, this.data.available_rental_grades, '-- Not a Rental Unit --', this.existingValues.rental_grade_id);
        if (saleSelect) this.updateSelectOptions(saleSelect, this.data.available_sale_grades, '-- Not a Sale Unit --', this.existingValues.sale_grade_id);
    },


    /**
     * Updates a select dropdown with new options and pre-selects a value.
     * @param {HTMLSelectElement} selectElement - The dropdown to update.
     * @param {Array} options - An array of objects [{id: 1, name: 'Option A'}].
     * @param {string} blankText - The text for the initial blank option.
     * @param {string|number} selectedValue - The ID of the option to pre-select.
     */
    updateSelectOptions: function(selectElement, options, blankText, selectedValue = '') {
        if (!selectElement) return;
        selectElement.innerHTML = '';
        selectElement.add(new Option(blankText, ''));

        if (options?.length > 0) {
            options.forEach(opt => {
                const option = new Option(opt.name, opt.id);
                if (String(opt.id) === String(selectedValue)) {
                    option.selected = true;
                }
                selectElement.add(option);
            });
        }
    },

    /**
     * Handles the lock/unlock toggle for specification overrides with live update.
     */
    handleSpecLockToggle: function(e) {
        const lockIcon = e.target;
        if (lockIcon && lockIcon.classList.contains('lock-icon') && !lockIcon.classList.contains('final')) {
            const specId = lockIcon.dataset.specId;
            const hiddenInput = document.querySelector(`input[name="spec_lock_${specId}"]`);
            const inputContainer = document.getElementById(`spec-input-${specId}`);

            if (hiddenInput.value === 'unlocked') {
                // --- LOCKING ---
                hiddenInput.value = 'locked';
                lockIcon.innerHTML = '🔒';
                lockIcon.classList.add('locked');
                lockIcon.title = 'Value is a locked override. Click to unlock.';
            } else {
                // --- UNLOCKING ---
                hiddenInput.value = 'unlocked';
                lockIcon.innerHTML = '🔓';
                lockIcon.classList.remove('locked');
                lockIcon.title = 'Value is inherited. Click to lock and create an override.';

                // Find the original specification data from the master 'this.data' object
                const specData = this.data.specifications.find(s => s.id == specId);
                if (!specData) return; // Safety check

                // Get the default value we stored on the icon
                const defaultValue = JSON.parse(lockIcon.dataset.defaultValue);
                
                // Use DynamicInputs to re-render the input with the default value
                if (specData.option_list) {
                    DynamicInputs.renderFromOptionList(inputContainer, specData.option_list, defaultValue, `spec_${specData.id}`);
                } else if (specData.data_type) {
                    DynamicInputs.renderSingleInput(inputContainer, specData.data_type, defaultValue, `spec_${specData.id}`);
                }
            }
        }
    },

    /**
     * Updates the serial number preview based on input fields.
     */
    updateSerialPreview: function() {
        if (!this.containers.serialNumbers) {
            return;
        }
        const prefixInput = document.getElementById(this.containers.serialNumbers.prefix);
        const suffixInput = document.getElementById(this.containers.serialNumbers.suffix);
        const startNumberInput = document.getElementById(this.containers.serialNumbers.startNumber); // Batch create
        const valueInput = document.getElementById(this.containers.serialNumbers.value); // Single create
        const serialPreviewEl = document.getElementById(this.containers.serialNumbers.preview);

        if (!serialPreviewEl) return;

        const prefix = prefixInput ? prefixInput.value || '' : '';
        const suffix = suffixInput ? suffixInput.value || '' : '';
        let mainValue = '';

        if (startNumberInput) { // Batch create
            mainValue = startNumberInput.value || '';
            serialPreviewEl.textContent = `Preview of first serial: ${[prefix, suffix, mainValue].filter(Boolean).join('-')}`;
        } else if (valueInput) { // Single create
            mainValue = valueInput.value || '';
            serialPreviewEl.textContent = `Full Serial Number Preview: ${[prefix, suffix, mainValue].filter(p => p && p.trim() !== '').join('-')}`;
        } else {
            serialPreviewEl.textContent = ''; // No serial fields to preview
        }
    },


    /**
     * Renders a dynamic, colored info box with details about a selected commercial grade.
     * @param {HTMLElement} displayContainer - The div to render the info box into.
     * @param {object} selectedGradeDetails - The grade details object from a map.
     * @param {string} selectedGradeName - The text name of the selected grade.
     */
    renderGradeInfo: function(displayContainer, selectedGradeDetails, selectedGradeName) {
        if (!displayContainer) return;

        if (selectedGradeDetails) {
            const details = selectedGradeDetails;
            
            // 1. Set background color and text color for contrast
            if (details.color) {
                displayContainer.style.backgroundColor = details.color;
                if (this._isDarkColor(details.color)) {
                    displayContainer.classList.add('text-white');
                } else {
                    displayContainer.classList.remove('text-white');
                }
            } else {
                displayContainer.style.backgroundColor = '';
                displayContainer.classList.remove('text-white');
            }

            // 2. Build the HTML
            let html = `<strong>${selectedGradeName} (${details.type})</strong><br>`;
            if (details.price2) { // It's a rental grade
                html += `Price: ${details.price1} (First Day), ${details.price2} (Next Day)<br>`;
            } else { // It's a sale grade
                html += `Price: ${details.price1}<br>`;
            }
            html += `Tax Rate: ${details.tax}`;
            
            displayContainer.innerHTML = html;
            displayContainer.style.display = 'block';
        } else {
            // Reset and hide the display
            displayContainer.style.display = 'none';
            displayContainer.style.backgroundColor = '';
            displayContainer.classList.remove('text-white');
        }
    },

    /**
     * (Private Helper) Determines if a hex color is "dark".
     * @private
     */
    _isDarkColor: function(hexColor) {
        if (!hexColor || hexColor.length !== 7) return false;
        try {
            const r = parseInt(hexColor.substr(1, 2), 16);
            const g = parseInt(hexColor.substr(3, 2), 16);
            const b = parseInt(hexColor.substr(5, 2), 16);
            const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b);
            return luminance < 140;
        } catch (e) {
            return false;
        }
    }

};

