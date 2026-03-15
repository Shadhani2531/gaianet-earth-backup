class GlobeManager {
    constructor() {
        if (CONFIG.CESIUM_ION_TOKEN) {
            Cesium.Ion.defaultAccessToken = CONFIG.CESIUM_ION_TOKEN;
        }

        this.viewer = new Cesium.Viewer('cesiumContainer', {
            terrain: Cesium.Terrain.fromWorldTerrain(),
            baseLayer: Cesium.ImageryLayer.fromProviderAsync(
                Cesium.createWorldImageryAsync({
                    style: Cesium.IonWorldImageryStyle.AERIAL_WITH_LABELS
                })
            ),
            baseLayerPicker: false,
            animation: false,
            timeline: false,
            homeButton: false,
            infoBox: false,
            selectionIndicator: false,
            navigationHelpButton: false,
            sceneModePicker: false,
            geocoder: false,
            fullscreenButton: false
            // Removed requestRenderMode to restore native smooth zooming/panning
        });

        // Dark sky/space background for aesthetic
        this.viewer.scene.skyAtmosphere.hueShift = -0.5;
        this.viewer.scene.skyAtmosphere.saturationShift = 0.5;
        this.viewer.scene.skyAtmosphere.brightnessShift = -0.3;

        this.layers = {
            temperature: null,
            co2: null,
            pollution: null,
            weather: null,
            ndvi: null,
            wildfires: [],
            sensors: []
        };

        this.initCamera();
        this.initInteraction();
        this.listenForScenarios();
    }

    initCamera() {
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(
                CONFIG.DEFAULT_COORDINATES.lon,
                CONFIG.DEFAULT_COORDINATES.lat,
                CONFIG.DEFAULT_COORDINATES.height
            ),
            duration: 3.0 // Cinematic fly-in
        });
    }

    initInteraction() {
        const handler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
        
        handler.setInputAction((movement) => {
            const pickedObject = this.viewer.scene.pick(movement.position);
            
            if (Cesium.defined(pickedObject) && pickedObject.id) {
                const entity = pickedObject.id;
                if (entity._customData) {
                    ui.showSensorPopup(entity.id, entity._customData, movement.position.x, movement.position.y);
                    
                    // Fetch and update right panel analytics
                    this.loadLocationAnalytics(entity._customData.lat, entity._customData.lon);
                }
            }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

        // Update layers based on UI toggles
        document.getElementById('layer-sensors').addEventListener('change', (e) => this.toggleSensors(e.target.checked));
        document.getElementById('layer-wildfires').addEventListener('change', (e) => this.toggleWildfires(e.target.checked));
        document.getElementById('layer-temp').addEventListener('change', (e) => this.toggleMockHeatmap(e.target.checked, 'temperature'));
        document.getElementById('layer-ndvi').addEventListener('change', (e) => this.toggleMockHeatmap(e.target.checked, 'ndvi'));
    }

    async loadLocationAnalytics(lat, lon) {
        const [climateData, envData] = await Promise.all([
            api.getClimate(lat, lon),
            api.getEnvironment(lat, lon)
        ]);
        
        ui.updateAnalyticsPanel(climateData, envData);
    }

    // LAYER MANAGEMENT
    async toggleSensors(visible) {
        if (!visible) {
            this.layers.sensors.forEach(e => this.viewer.entities.remove(e));
            this.layers.sensors = [];
            return;
        }

        // Mock loading 10 global sensors
        const sensors = [
            { name: "Mauna Loa Obs", lat: 19.5362, lon: -155.5763, val: "420 ppm" },
            { name: "Delhi AirQA", lat: 28.6139, lon: 77.2090, val: "AQI 250" },
            { name: "Amazon Flux", lat: -3.4653, lon: -62.2159, val: "NDVI 0.85" },
            { name: "Arctic Base", lat: 78.2232, lon: 15.6267, val: "-15°C" },
            { name: "Sahara Geo", lat: 23.4162, lon: 25.6628, val: "45°C" },
            { name: "London Station", lat: 51.5074, lon: -0.1278, val: "12°C" },
            { name: "Tokyo Monitor", lat: 35.6762, lon: 139.6503, val: "AQI 45" },
            { name: "Sydney Env", lat: -33.8688, lon: 151.2093, val: "22°C" },
            { name: "NY Climate", lat: 40.7128, lon: -74.0060, val: "AQI 60" },
            { name: "Cape Town Bio", lat: -33.9249, lon: 18.4241, val: "NDVI 0.45" }
        ];

        sensors.forEach((s, idx) => {
            const entity = this.viewer.entities.add({
                name: s.name,
                position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat),
                point: {
                    pixelSize: 12,
                    color: Cesium.Color.fromCssColorString('#38bdf8'),
                    outlineColor: Cesium.Color.WHITE,
                    outlineWidth: 2,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                },
                label: {
                    text: s.name,
                    font: '14pt Inter',
                    style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                    outlineWidth: 2,
                    verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                    pixelOffset: new Cesium.Cartesian2(0, -15),
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                }
            });

            entity._customData = {
                name: s.name,
                lat: s.lat,
                lon: s.lon,
                details: {
                    "Reading": s.val,
                    "Status": "Online",
                    "Latency": "24ms"
                }
            };

            this.layers.sensors.push(entity);
        });
        this.viewer.scene.requestRender();
    }

    async toggleWildfires(visible) {
        if (!visible) {
            this.layers.wildfires.forEach(e => this.viewer.entities.remove(e));
            this.layers.wildfires = [];
            return;
        }

        const data = await api.getWildfires();
        if(!data) return;

        data.fires.forEach((f, idx) => {
            const size = Math.max(10000, f.intensity_frp * 2000); // Scale by intensity
            const entity = this.viewer.entities.add({
                position: Cesium.Cartesian3.fromDegrees(f.lon, f.lat),
                ellipse: {
                    semiMinorAxis: size,
                    semiMajorAxis: size,
                    material: new Cesium.ColorMaterialProperty(Cesium.Color.RED.withAlpha(0.6)),
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                }
            });
            this.layers.wildfires.push(entity);
        });
        this.viewer.scene.requestRender();
    }

    toggleMockHeatmap(visible, type) {
        // Mocking visual heatmaps using large polygons or imagery layers.
        // For testing without real WMS layers, we generate colored primitive ellipses worldwide.
        if (!visible) {
            if (this.layers[type]) {
                this.layers[type].forEach(e => this.viewer.entities.remove(e));
            }
            this.layers[type] = [];
            return;
        }

        this.layers[type] = [];
        const color = type === 'temperature' ? Cesium.Color.ORANGE : Cesium.Color.LIME;
        
        // Random global splats
        for(let i=0; i<30; i++) {
            const lat = (Math.random() - 0.5) * 140;
            const lon = (Math.random() - 0.5) * 360;
            const size = 500000 + Math.random() * 1000000;
            
            const entity = this.viewer.entities.add({
                position: Cesium.Cartesian3.fromDegrees(lon, lat),
                ellipse: {
                    semiMinorAxis: size,
                    semiMajorAxis: size,
                    material: new Cesium.ColorMaterialProperty(color.withAlpha(0.2)),
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                }
            });
            this.layers[type].push(entity);
        }
        this.viewer.scene.requestRender();
    }

    listenForScenarios() {
        document.addEventListener('scenarioRan', (e) => {
            const prediction = e.detail;
            
            // Visual effect: Tint the globe red for high risk, orange for medium
            let tintColor = Cesium.Color.WHITE;
            if(prediction.risk_level === 'Critical') tintColor = Cesium.Color.RED.withAlpha(0.3);
            else if(prediction.risk_level === 'High') tintColor = Cesium.Color.ORANGE.withAlpha(0.3);

            // Adding a massive global semi-transparent layer representation
            if(this.scenarioEffect) {
                this.viewer.entities.remove(this.scenarioEffect);
            }

            this.scenarioEffect = this.viewer.entities.add({
                polygon: {
                    hierarchy: Cesium.Cartesian3.fromDegreesArray([
                        -180, -90,
                        180, -90,
                        180, 90,
                        -180, 90
                    ]),
                    material: new Cesium.ColorMaterialProperty(tintColor),
                     heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                }
            });
            
            this.viewer.camera.flyTo({
                destination: Cesium.Cartesian3.fromDegrees(prediction.location.lon, prediction.location.lat, 15000000),
                duration: 2.0
            });
            
            this.viewer.scene.requestRender();
        });
    }
}
