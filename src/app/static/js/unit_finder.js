// app/static/js/unit_finder.js

document.addEventListener('DOMContentLoaded', function () {
    const searchInput = document.getElementById('unit-search-input');
    const resultsContainer = document.getElementById('search-results-container');
    
    if (!searchInput || !resultsContainer) {
        return;
    }

    let debounceTimer;

    // --- Helper function for color contrast ---
    /**
     * Determines if a hex color is "dark".
     * @param {string} hexColor - e.g., "#RRGGBB"
     * @returns {boolean} - True if the color is dark.
     */
    function isDarkColor(hexColor) {
        if (!hexColor || hexColor.length !== 7) return false;
        try {
            const r = parseInt(hexColor.substr(1, 2), 16);
            const g = parseInt(hexColor.substr(3, 2), 16);
            const b = parseInt(hexColor.substr(5, 2), 16);
            const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b);
            return luminance < 128;
        } catch (e) {
            return false;
        }
    }

    // --- The main function that handles the search logic ---
    async function handleSearch() {
        const searchTerm = searchInput.value.trim();

        // If the search box is empty, clear the results and stop
        if (searchTerm.length === 0) {
            resultsContainer.innerHTML = '';
            return;
        }

        // Show a loading indicator
        resultsContainer.innerHTML = '<div class="list-group-item">Searching...</div>';

        try {
            // Make the API call
            const response = await fetch(`/api/units/search?q=${encodeURIComponent(searchTerm)}`);
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            const units = await response.json();

            // Clear the loading indicator
            resultsContainer.innerHTML = '';

            // Render the results
            if (units.length === 0) {
                resultsContainer.innerHTML = '<div class="list-group-item">No units found.</div>';
            } else {
                units.forEach(unit => {
                    // Create a link for each result
                    const link = document.createElement('a');
                    link.href = `/internal/units/${unit.unit_id}`; 
                    link.className = 'list-group-item list-group-item-action';

                    if (unit.grade_color) {
                        link.style.backgroundColor = unit.grade_color;
                        
                        // 2. Set text color for contrast if the background is dark
                        if (isDarkColor(unit.grade_color)) {
                            link.classList.add('text-white');
                        }
                    }
                    
                    // Create the content for the link
                    const gradeBadge = unit.grade_name 
                        ? `<span class="badge badge-info ml-2">${unit.grade_name}</span>` 
                        : '';

                    link.innerHTML = `
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <strong>${unit.serial_number}</strong>
                                <br>
                                <small class="text-muted">${unit.product_name}</small>
                            </div>
                            ${gradeBadge}
                        </div>
                    `;
                    resultsContainer.appendChild(link);
                });
            }
        } catch (error) {
            console.error('Search failed:', error);
            resultsContainer.innerHTML = '<div class="list-group-item list-group-item-danger">Search failed. Please try again.</div>';
        }
    }

    // --- The Debounce Mechanism ---
    searchInput.addEventListener('keyup', () => {
        // Clear the previous timer
        clearTimeout(debounceTimer);
        
        // Set a new timer to run the search after 300ms of inactivity
        debounceTimer = setTimeout(() => {
            handleSearch();
        }, 300);
    });
});