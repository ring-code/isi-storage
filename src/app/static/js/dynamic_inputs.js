/**
 * A library for dynamically rendering form input types based on DataType objects.
 */
const DynamicInputs = {
    /**
     * Applies HTML5 validation attributes to an input element based on a rules object.
     * @param {HTMLElement} inputElement - The input element to modify.
     * @param {object} rules - The validation_rules object from the DataType.
     */
    applyValidationRules: function(inputElement, rules) {
        if (!rules) return;
        inputElement.removeAttribute('min');
        inputElement.removeAttribute('max');
        inputElement.removeAttribute('minlength');
        inputElement.removeAttribute('maxlength');
        inputElement.removeAttribute('pattern');
        
        if (rules.min !== undefined) inputElement.setAttribute('min', rules.min);
        if (rules.max !== undefined) inputElement.setAttribute('max', rules.max);
        if (rules.min_length !== undefined) inputElement.setAttribute('minlength', rules.min_length);
        if (rules.max_length !== undefined) inputElement.setAttribute('maxlength', rules.max_length);
        if (rules.regex !== undefined) inputElement.setAttribute('pattern', rules.regex);
    },

    /**
     * Renders a single, simple input field (for specifications, etc.).
     * @param {HTMLElement} container - The container div to render into.
     * @param {object} dataType - The DataType object for the input.
     * @param {string} value - The existing value.
     * @param {string} fieldName - The base name for the field (e.g., 'default_values-0-value').
     */
    renderSingleInput: function(container, dataType, value = '', fieldName = 'default_values-0-value') {
        if (!dataType) {
            container.innerHTML = '';
            return;
        }

        if (dataType.display_type === 'color') {
            const hasValue = value && value.trim() !== '';
            const isChecked = hasValue ? 'checked' : '';
            const isDisabled = hasValue ? '' : 'disabled';
            const displayValue = hasValue ? value : '#cccccc'; // A neutral grey for disabled state

            // We use a hidden input to hold the TRUE value that gets submitted.
            // The checkbox and color picker are just for UI control.
            container.innerHTML = `
                <div class="d-flex align-items-center">
                    <div class="form-check mr-3">
                        <input type="checkbox" class="form-check-input" id="enable-${fieldName}" ${isChecked}>
                        <label class="form-check-label" for="enable-${fieldName}">Set Value</label>
                    </div>
                    <input type="color" class="form-control" id="picker-${fieldName}" value="${displayValue}" ${isDisabled}>
                    <input type="hidden" name="${fieldName}" id="hidden-${fieldName}" value="${value || ''}">
                </div>
            `;

            // Now, add event listeners to make it interactive
            const enableCheckbox = container.querySelector(`#enable-${fieldName}`);
            const colorPicker = container.querySelector(`#picker-${fieldName}`);
            const hiddenInput = container.querySelector(`#hidden-${fieldName}`);

            enableCheckbox.addEventListener('change', function() {
                if (this.checked) {
                    colorPicker.disabled = false;
                    // If unlocking, and the value was black, set it. Otherwise, default.
                    hiddenInput.value = hiddenInput.value || '#000000'; 
                    colorPicker.value = hiddenInput.value;
                } else {
                    colorPicker.disabled = true;
                    hiddenInput.value = ''; // This is the key: set value to empty string
                    colorPicker.value = '#cccccc'; // Visual cue
                }
            });

            colorPicker.addEventListener('input', function() {
                // When the user picks a color, update the hidden input that actually gets submitted.
                hiddenInput.value = this.value;
            });

            // No need to apply validation rules for this special case
            return; // Exit the function here
        }

        // --- All other types ---
        let stepAttribute = '';
        if (dataType.display_type === 'float') {
            stepAttribute = 'step="any"';
        }

        const inputTypeMap = { 'integer': 'number', 'float': 'number', 'color': 'color', 'date': 'date', 'datetime-local': 'datetime-local', 'email': 'email', 'month': 'month', 'range': 'range', 'tel': 'tel', 'time': 'time', 'url': 'url', 'week': 'week' };
        const inputType = inputTypeMap[dataType.display_type] || 'text';
        
        let inputHtml = `<input type="${inputType}" name="${fieldName}" class="form-control" value="${value || ''}" ${stepAttribute}>`;
        
        if (dataType.display_type === 'boolean') {
            const isChecked = value === '1' || value === true ? 'checked' : '';
            inputHtml = `
                <div class="form-check">
                    <input type="hidden" name="${fieldName}" value="0">
                    <input type="checkbox" name="${fieldName}" class="form-check-input" value="1" ${isChecked}>
                </div>`;
        }
        container.innerHTML = inputHtml;
        const inputEl = container.querySelector("input:not([type='hidden'])");
        if(inputEl) this.applyValidationRules(inputEl, dataType.validation_rules);
    },

    /**
     * Renders a dynamic list of inputs for OptionList pages.
     * @param {HTMLElement} container - The container div to render into.
     * @param {object | null} itemDataType - The DataType for the list items.
     * @param {Array} existingItems - Array of existing items, e.g., [{id: 1, value: 'Red'}].
     * @param {boolean} isEditMode - True if on the edit page, which locks existing items.
     * @param {string} fieldName - The base name for the FieldList (e.g., 'items').
     */
    renderListOfInputs: function(container, itemDataType, existingItems = [], isEditMode = false, fieldName = 'items') {
        if (!itemDataType) {
            container.innerHTML = `<p class="text-muted"><em>Please select a Data Type for the items first.</em></p>`;
            return;
        }

        container.innerHTML = `
            <div id="dynamic-list-items"></div>
            <button type="button" id="add-list-item-btn" class="btn btn-sm btn-success mt-2">+ Add New Item</button>
        `;

        const listContainer = container.querySelector('#dynamic-list-items');
        
        function getHtmlInputType(dataType) {
            if (!dataType) return 'text';
            const typeMap = { 'integer': 'number', 'float': 'number', 'color': 'color', 'date': 'date', 'datetime-local': 'datetime-local', 'email': 'email', 'month': 'month', 'range': 'range', 'tel': 'tel', 'time': 'time', 'url': 'url', 'week': 'week' };
            return typeMap[dataType.display_type] || 'text';
        }
        
        const addItem = (itemData = {id: '', value: ''}) => {
            const index = listContainer.children.length;
            const itemDiv = document.createElement('div');
            itemDiv.className = 'input-group mb-2';

            const isExisting = isEditMode && itemData.id;
            const inputType = getHtmlInputType(itemDataType);
            const itemValue = itemData.value || '';

            let stepAttribute = '';
            if (itemDataType.display_type === 'float') {
                stepAttribute = 'step="any"';
            }

            let inputHtml;
            if (isExisting) {
                inputHtml = `
                    <input type="${inputType}" class="form-control" value="${itemValue} ${stepAttribute}" disabled title="Existing items cannot be edited.">
                    <input type="hidden" name="${fieldName}-${index}-value" value="${itemValue}">
                `;
            } else {
                inputHtml = `<input type="${inputType}" name="${fieldName}-${index}-value" class="form-control" value="${itemValue}" ${stepAttribute}>`;
            }

            itemDiv.innerHTML = `
                <input type="hidden" name="${fieldName}-${index}-id" value="${itemData.id || ''}">
                ${inputHtml}
                <div class="input-group-append">
                    ${!isExisting ? `<button type="button" class="btn btn-sm btn-danger remove-list-item-btn">&times;</button>` : ''}
                </div>
            `;

            const valueInput = itemDiv.querySelector(`input[name$="-value"]:not([type="hidden"])`);
            if (valueInput) {
                this.applyValidationRules(valueInput, itemDataType.validation_rules);
            }
            listContainer.appendChild(itemDiv);
        }

        // Render existing items from the server
        if (existingItems && existingItems.length > 0) {
            existingItems.forEach(item => addItem(item));
        }

        // On the CREATE page, if there are no existing items, add one blank item to start.
        if (!isEditMode && existingItems.length === 0) {
            addItem();
        }

        // Add event listeners for the "Add" and "Remove" buttons
        container.querySelector('#add-list-item-btn').addEventListener('click', () => addItem());

        listContainer.addEventListener('click', (e) => {
            if (e.target && e.target.classList.contains('remove-list-item-btn')) {
                e.target.closest('.input-group').remove();
                // Re-index all items to ensure sequential names for the form
                const items = listContainer.querySelectorAll('.input-group');
                items.forEach((item, newIndex) => {
                    item.querySelectorAll('input').forEach(input => {
                        if (input.name) {
                            input.name = input.name.replace(new RegExp(`${fieldName}-\\d+-`), `${fieldName}-${newIndex}-`);
                        }
                    });
                });
            }
        });
    },


    /**
     * Renders a UI (dropdown, radios, or checkboxes) from a predefined OptionList.
     * @param {HTMLElement} container - The container div to render into.
     * @param {object} optionList - The full OptionList object.
     * @param {string|Array} currentValue - The existing single value or array of values.
     * @param {string} fieldName - The base name for the field (e.g., 'default_value').
     */
    renderFromOptionList: function(container, optionList, currentValue, fieldName = 'default_value') {
        container.innerHTML = '';
        if (!optionList || !optionList.items) return;

        const isMulti = optionList.allow_multiple_selections;
        const hint = optionList.display_hint;
        const itemDataType = optionList.item_data_type;
        let html = '';

        // Standardize currentValue to always be an array for easier checking
        let currentValues = [];
        if (currentValue) {
            try {
                // Try to parse it as JSON first (for multi-select values)
                const parsed = JSON.parse(currentValue);
                currentValues = Array.isArray(parsed) ? parsed : [currentValue];
            } catch (e) {
                // If it's not JSON, treat it as a single string value
                currentValues = [currentValue];
            }
        }
        
        // --- Helper to generate a color swatch if needed ---
        const renderColorSwatch = (item) => {
            return itemDataType && itemDataType.display_type === 'color'
                ? `<span class="color-swatch" style="background-color:${item.value};"></span>`
                : '';
        };

        if (isMulti) { // Checkboxes
            optionList.items.forEach((item, index) => {
                const isChecked = currentValues.includes(item.value) ? 'checked' : '';
                html += `
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" name="${fieldName}" value="${item.value}" id="cb-default-${index}" ${isChecked}>
                        <label class="form-check-label" for="cb-default-${index}">
                            ${renderColorSwatch(item)}
                            ${item.value}
                        </label>
                    </div>`;
            });
        } else if (hint === 'radio') { // Radio Buttons
            optionList.items.forEach((item, index) => {
                const isChecked = currentValues.includes(item.value) ? 'checked' : '';
                html += `
                    <div class="form-check">
                        <input class="form-check-input" type="radio" name="${fieldName}" value="${item.value}" id="radio-default-${index}" ${isChecked}>
                        <label class="form-check-label" for="radio-default-${index}">
                            ${renderColorSwatch(item)}
                            ${item.value}
                        </label>
                    </div>`;
            });
        } else { // Dropdown (default for single-choice)
            html = `<select name="${fieldName}" class="form-control"><option value="">-- No Default --</option>`;
            optionList.items.forEach(item => {
                const isSelected = currentValues.includes(item.value) ? 'selected' : '';
                html += `<option value="${item.value}" ${isSelected}>${item.value}</option>`;
            });
            html += `</select>`;
        }
        container.innerHTML = html;
    }
}