// This file exports utility functions that can be used throughout the application. 
// It may include functions for formatting data or performing common tasks. 

// Example utility function: 
function formatDate(date) {
    return date.format("YYYY-MM-DD");
}

// Example utility function: 
function capitalizeFirstLetter(string) {
    return string.charAt(0).toUpperCase() + string.slice(1);
}

// Exporting functions
exports.formatDate = formatDate;
exports.capitalizeFirstLetter = capitalizeFirstLetter;