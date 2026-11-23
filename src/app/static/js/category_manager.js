// static/js/category_manager.js

document.addEventListener('DOMContentLoaded', function () {
    const STORAGE_KEY = 'openCategories';
    const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

    // --- 1. Restore Accordion State on Page Load ---
    function restoreState() {
        const openIds = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        openIds.forEach(id => {
            const collapseElement = document.getElementById(`collapse-${id}`);
            if (collapseElement) {
                // Using Bootstrap's JS API to show the collapse element
                $(collapseElement).collapse('show');
            }
        });
    }

    // --- 2. Save Accordion State on Change ---
    // Use jQuery's Bootstrap events for reliability
    $('.collapse').on('shown.bs.collapse', function () {
        const id = this.id.replace('collapse-', '');
        let openIds = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        if (!openIds.includes(id)) {
            openIds.push(id);
            localStorage.setItem(STORAGE_KEY, JSON.stringify(openIds));
        }
    });

    $('.collapse').on('hidden.bs.collapse', function () {
        const id = this.id.replace('collapse-', '');
        let openIds = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        const index = openIds.indexOf(id);
        if (index > -1) {
            openIds.splice(index, 1);
            localStorage.setItem(STORAGE_KEY, JSON.stringify(openIds));
        }
    });

    // --- 3. Inline Category Name Editing ---
    document.querySelectorAll('.js-edit-cat-name').forEach(button => {
        button.addEventListener('click', async function(e) {
            e.preventDefault();
            const catId = this.dataset.id;
            const currentName = this.dataset.currentName;
            const newName = prompt('Enter the new category name:', currentName);

            if (newName && newName.trim() && newName !== currentName) {
                try {
                    const response = await fetch(`/api/categories/${catId}/rename`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken 
                        },
                        body: JSON.stringify({ name: newName.trim() })
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.message);
                    
                    document.getElementById(`category-name-${catId}`).textContent = data.newName;
                    this.dataset.currentName = data.newName; // Update for next edit
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }
        });
    });


    // finalize logic
    document.querySelectorAll('.js-finalize-spec').forEach(button => {
        button.addEventListener('click', async function() {
            if (!confirm("Are you sure you want to finalize this spec? Its value will be locked for all children.")) {
                return;
            }

            const catId = this.dataset.catId;
            const defId = this.dataset.defId;

            this.textContent = '...';
            this.disabled = true;

            try {
                const response = await fetch(`/api/categories/${catId}/finalize-spec/${defId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
                });

                const data = await response.json();
                if (!response.ok) throw new Error(data.message);
                
                location.reload();

            } catch (error) {
                alert('Error: ' + error.message);
                this.textContent = 'Finalize'; // Revert text on error
                this.disabled = false;
            }
        });
    });


    // --- Un-Finalize Specification Button Logic ---
    document.querySelectorAll('.js-unfinalize-spec').forEach(button => {
        button.addEventListener('click', async function() {
            if (!confirm("Are you sure you want to un-finalize this spec? The value will remain but will become editable.")) {
                return;
            }

            const catId = this.dataset.catId;
            const defId = this.dataset.defId;
            
            this.textContent = '...';
            this.disabled = true;

            try {
                const response = await fetch(`/api/categories/${catId}/unfinalize-spec/${defId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
                });

                const data = await response.json();
                if (!response.ok) throw new Error(data.message);
                
                // Success! Reload the page to see the new state.
                location.reload();

            } catch (error) {
                alert('Error: ' + error.message);
                this.textContent = 'Un-Finalize';
                this.disabled = false;
            }
        });
    });
    restoreState();
});