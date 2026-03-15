from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from .services import mock_data

app = FastAPI(title="GaiaNet Earth API", description="Backend data gateway for Digital Twin of the Planet")

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "online", "message": "GaiaNet Earth API is running."}

@app.get("/environment")
def get_environment_data(lat: float = Query(..., description="Latitude"), lon: float = Query(..., description="Longitude")):
    # Combine some basic data for a specific point
    weather = mock_data.generate_weather_data(lat, lon)
    return {
        "location": {"lat": lat, "lon": lon},
        "temperature_c": weather["temperature_c"],
        "air_quality_index": mock_data.random.randint(20, 300),
        "co2_ppm": mock_data.random.randint(380, 450)
    }

@app.get("/weather")
def get_weather(lat: float = Query(..., description="Latitude"), lon: float = Query(..., description="Longitude")):
    return mock_data.generate_weather_data(lat, lon)

@app.get("/vegetation")
def get_vegetation():
    return mock_data.generate_vegetation_data()

@app.get("/wildfires")
def get_wildfires():
    return mock_data.generate_wildfire_data()

@app.get("/climate")
def get_climate(lat: float = Query(..., description="Latitude"), lon: float = Query(..., description="Longitude")):
    return mock_data.generate_climate_data(lat, lon)

@app.get("/prediction")
def get_prediction(scenario: str = Query(..., description="Scenario ID (e.g., temp_increase_1_5)"), lat: float = Query(..., description="Latitude"), lon: float = Query(..., description="Longitude")):
    return mock_data.generate_prediction_data(scenario, lat, lon)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)