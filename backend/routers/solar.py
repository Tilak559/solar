import pandas as pd
from fastapi import APIRouter
import requests
import numpy as np
import matplotlib.pyplot as plt
import logging
from ..services.solar import get_google_solar_data, get_state_from_coords, geocode_address
from ..services.gutter_estimator import get_gutter_estimate_from_solar_data

# Set up logging
logger = logging.getLogger(__name__)

solar = APIRouter()

@solar.get("/coordinates")
async def get_coordinates(address: str):
    lat, lng = geocode_address(address)
    if lat and lng:
        state = get_state_from_coords(lat, lng)
        return {"latitude": lat, "longitude": lng, "state": state}
    else:
        return {"error": "Failed to geocode address"}

@solar.get("/measurements")
async def get_measurements(address: str):
    measurements = get_google_solar_data(address)
    print(measurements)
    return measurements

@solar.get("/gutter-estimate")
async def get_gutter_estimate(address: str, waste_factor: float = 0.02):
    """
    Get gutter length estimate for a gable roof using Google Solar API geometry.
    
    Args:
        address: Building address to analyze
        waste_factor: Waste factor as decimal (default 0.02 = 2%)
        
    Returns:
        Gutter estimate with dimensions and warnings
    """
    logger.info(f"Getting gutter estimate for address: {address}")
    
    # Get solar data first
    solar_data = get_google_solar_data(address)
    logger.info(f"Solar data response keys: {list(solar_data.keys())}")
    
    if "error" in solar_data:
        logger.error(f"Solar data error: {solar_data['error']}")
        return {
            "address": address,
            "gutter_estimate": {
                "eave_length_ft": 0.0,
                "total_gutter_ft": 0,
                "waste_factor": waste_factor,
                "warnings": [f"Solar data error: {solar_data['error']}"]
            },
            "solar_data_summary": {
                "has_data": False,
                "roof_segments": 0,
                "total_area_m2": None
            }
        }
    
    # Log the raw API response structure
    raw_response = solar_data.get("raw_api_response", {})
    logger.info(f"Raw API response keys: {list(raw_response.keys())}")
    
    if 'roofSegmentStats' in raw_response:
        logger.info(f"Found {len(raw_response['roofSegmentStats'])} roof segments in raw response")
        for i, segment in enumerate(raw_response['roofSegmentStats']):
            logger.info(f"  Raw segment {i} keys: {list(segment.keys())}")
    else:
        logger.warning("No roofSegmentStats found in raw API response")
    
    # Calculate gutter estimate
    gutter_estimate = get_gutter_estimate_from_solar_data(solar_data, waste_factor)
    logger.info(f"Gutter estimate result: {gutter_estimate}")
    
    return {
        "address": address,
        "gutter_estimate": gutter_estimate,
        "solar_data_summary": {
            "has_data": "error" not in solar_data,
            "roof_segments": len(solar_data.get("raw_api_response", {}).get("solarPotential", {}).get("roofSegmentStats", [])),
            "total_area_m2": solar_data.get("raw_api_response", {}).get("solarPotential", {}).get("wholeRoofStats", {}).get("groundAreaMeters2")
        }
    }
