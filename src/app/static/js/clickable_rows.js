/**
 * Makes table rows with a 'data-href' attribute clickable and handles form
 * confirmations directly to avoid issues with event bubbling conflicts.
 * 
 * @param {string} tableSelector - A CSS selector for the table(s) to apply this to.
 */
function initializeClickableRows(tableSelector) {
    
    // --- 1. Handle Delete Form Confirmation ---
    // This is the most reliable method. We listen for the 'submit' event
    // directly on any form that needs confirmation.
    const deleteForms = document.querySelectorAll(`${tableSelector} .js-delete-form`);

    deleteForms.forEach(form => {
        form.addEventListener('submit', function(event) {
            // ALWAYS prevent the form from submitting initially.
            event.preventDefault(); 
            
            const confirmMessage = form.dataset.confirmMessage || 'Are you sure you want to delete this? This cannot be undone.';

            // Show the confirmation dialog.
            if (window.confirm(confirmMessage)) {
                // If the user clicks "OK", we submit the form for real.
                // This programmatic submission does NOT trigger this listener again.
                form.submit();
            }
            // If the user clicks "Cancel", nothing happens.
        });
    });

    // --- 2. Handle the Row Click Navigation ---
    // We attach a click listener to each individual row.
    const rows = document.querySelectorAll(`${tableSelector} tr[data-href]`);

    rows.forEach(row => {
        row.addEventListener('click', function(event) {
            // Check if the element that was actually clicked (the event.target)
            // is an interactive element or is inside one.
            const interactiveElement = event.target.closest('a, button, input, select, form');
            console.log("Clicked on:", event.target);
            console.log("Found interactive parent:", interactiveElement);

            // If the click was NOT on an interactive element, then navigate.
            if (!interactiveElement) {
                console.log("Navigating to:", row.dataset.href);
                window.location.href = row.dataset.href;
            }
            // If it WAS on an interactive element, do nothing and let the
            // browser handle the default action (like submitting the Edit form).

            
        });
    });
}