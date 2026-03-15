document.addEventListener('DOMContentLoaded', async () => {
    // Initialize Globe
    window.globe = new GlobeManager();

    // Trigger default state
    setTimeout(() => {
        // Load initial sensors
        document.getElementById('layer-sensors').dispatchEvent(new Event('change'));
        
        // Load initial analytics for center point India
        globe.loadLocationAnalytics(CONFIG.DEFAULT_COORDINATES.lat, CONFIG.DEFAULT_COORDINATES.lon);
    }, 1000);
});
