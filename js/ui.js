class UIManager {
    constructor() {
        this.tempChart = null;
        this.precipChart = null;
        
        this.initEventListeners();
        this.initCharts();
    }

    initEventListeners() {
        // Toggle Scenario Panel
        document.getElementById('scenario-btn').addEventListener('click', () => {
            const panel = document.getElementById('scenario-panel');
            panel.classList.toggle('hidden');
        });

        // Run Scenario
        document.getElementById('run-scenario-btn').addEventListener('click', async () => {
            const scenario = document.getElementById('scenario-select').value;
            if (!scenario) {
                alert("Please select a scenario.");
                return;
            }
            
            const resultsDiv = document.getElementById('simulation-results');
            resultsDiv.innerHTML = '<p style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Running simulation models...</p>';
            
            // Get center coordinates from globe (mocked for now)
            const lat = CONFIG.DEFAULT_COORDINATES.lat; 
            const lon = CONFIG.DEFAULT_COORDINATES.lon;

            const prediction = await api.getPrediction(scenario, lat, lon);
            
            if (prediction) {
                let colorClass = prediction.risk_level === 'Critical' ? 'color: var(--danger);' : 
                                 prediction.risk_level === 'High' ? 'color: var(--warning);' : 'color: var(--success);';
                
                resultsDiv.innerHTML = `
                    <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 6px; font-size: 0.9rem;">
                        <p><strong>Impact:</strong> +${prediction.predicted_temp_change_c}°C</p>
                        <p><strong>Sea Level:</strong> +${prediction.sea_level_rise_cm}cm</p>
                        <p><strong>Risk Level:</strong> <span style="${colorClass} font-weight: bold;">${prediction.risk_level}</span></p>
                    </div>
                `;
                
                // Triger event for globe to show heatmap/effects
                document.dispatchEvent(new CustomEvent('scenarioRan', { detail: prediction }));

            } else {
                resultsDiv.innerHTML = '<p style="color:var(--danger);">Simulation failed to execute.</p>';
            }
        });

        // Close Popup
        document.getElementById('close-popup').addEventListener('click', () => {
            document.getElementById('sensor-popup').classList.remove('active');
        });

        // Timeline playback
        const playBtn = document.getElementById('play-btn');
        let isPlaying = false;
        let playInterval;

        playBtn.addEventListener('click', () => {
            isPlaying = !isPlaying;
            playBtn.innerHTML = isPlaying ? '<i class="fa-solid fa-pause"></i>' : '<i class="fa-solid fa-play"></i>';
            
            if (isPlaying) {
                const slider = document.getElementById('timeline-slider');
                const speedSelect = document.getElementById('speed-select');
                
                playInterval = setInterval(() => {
                    let val = parseInt(slider.value);
                    if (val >= 100) {
                        slider.value = 0; // Loop back
                    } else {
                        slider.value = val + parseInt(speedSelect.value);
                    }
                    this.updateDateDisplay(slider.value);
                }, 100);
            } else {
                clearInterval(playInterval);
            }
        });

        document.getElementById('timeline-slider').addEventListener('input', (e) => {
            this.updateDateDisplay(e.target.value);
        });
    }

    updateDateDisplay(value) {
        // Mock date mapping (0-100 maps to 12 months in past to now)
        const display = document.getElementById('current-date-display');
        const months = ["Apr 2025", "May 2025", "Jun 2025", "Jul 2025", "Aug 2025", "Sep 2025", "Oct 2025", "Nov 2025", "Dec 2025", "Jan 2026", "Feb 2026", "Mar 2026"];
        const index = Math.floor((value / 100) * (months.length - 1));
        display.innerText = months[Math.max(0, Math.min(months.length - 1, index))];
    }

    initCharts() {
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.font.family = 'Inter';

        const ctxTemp = document.getElementById('tempChart').getContext('2d');
        this.tempChart = new Chart(ctxTemp, {
            type: 'line',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                datasets: [{
                    label: 'Avg Temp (°C)',
                    data: [0, 0, 0, 0, 0, 0],
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Temperature Trends', color: '#e2e8f0' }
                },
                scales: {
                    y: { grid: { color: 'rgba(255,255,255,0.05)' } },
                    x: { grid: { display: false } }
                }
            }
        });

        const ctxPrecip = document.getElementById('precipChart').getContext('2d');
        this.precipChart = new Chart(ctxPrecip, {
            type: 'bar',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                datasets: [{
                    label: 'Rainfall (mm)',
                    data: [0, 0, 0, 0, 0, 0],
                    backgroundColor: '#38bdf8',
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Rainfall Patterns', color: '#e2e8f0' }
                },
                scales: {
                    y: { grid: { color: 'rgba(255,255,255,0.05)' } },
                    x: { grid: { display: false } }
                }
            }
        });
    }

    updateAnalyticsPanel(climateData, envData) {
        if (!climateData) return;

        // Update Summary
        document.getElementById('location-summary').innerHTML = `
            <p><i class="fa-solid fa-location-dot"></i> Lat: ${climateData.location.lat.toFixed(2)}°, Lon: ${climateData.location.lon.toFixed(2)}°</p>
            <p><strong>Current Temp:</strong> ${envData ? envData.temperature_c + '°C' : '--'}</p>
        `;

        if (envData) {
            document.getElementById('stat-aqi').innerText = envData.air_quality_index;
            document.getElementById('stat-co2').innerText = envData.co2_ppm;
        }

        // Update Charts
        const history = climateData.historical_trends.slice(0, 6); // Take last 6 entries
        const labels = history.map(h => {
             const [y, m] = h.month.split('-');
             const d = new Date(y, m-1);
             return d.toLocaleString('default', { month: 'short' });
        });
        
        const temps = history.map(h => h.avg_temp_c);
        const precip = history.map(h => h.total_rainfall_mm);

        this.tempChart.data.labels = labels;
        this.tempChart.data.datasets[0].data = temps;
        this.tempChart.update();

        this.precipChart.data.labels = labels;
        this.precipChart.data.datasets[0].data = precip;
        this.precipChart.update();
    }

    showSensorPopup(id, data, x, y) {
        const popup = document.getElementById('sensor-popup');
        const title = document.getElementById('popup-title');
        const content = document.getElementById('popup-content');
        
        let color = data.color || '#38bdf8';
        title.innerHTML = `<i class="fa-solid fa-tower-broadcast" style="color:${color}"></i> ${data.name}`;
        
        let html = '';
        for (const [key, value] of Object.entries(data.details)) {
             html += `
                <div class="popup-detail">
                    <span class="label">${key}</span>
                    <span class="val">${value}</span>
                </div>
             `;
        }
        content.innerHTML = html;
        
        popup.classList.add('active');
    }
}

const ui = new UIManager();
