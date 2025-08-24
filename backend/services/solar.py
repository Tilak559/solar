import requests
import json
import math
import os
import logging
from shapely.geometry import Point, Polygon
from shapely.ops import transform
import pyproj
from functools import partial
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def geocode_address(address):

    try:
        from backend.services.config import config
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"address": address, "key": config.google_api_key}
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("results"):
                location = data["results"][0]["geometry"]["location"]
                return location["lat"], location["lng"]
        return None, None
    except Exception:
        return None, None




def get_state_from_coords(lat, lng):
    """
    Determine US state from coordinates using reverse geocoding
    """
    try:
        from backend.services.config import config
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "latlng": f"{lat},{lng}",
            "key": config.google_api_key
        }
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("results"):
                # Extract state from address components
                for component in data["results"][0]["address_components"]:
                    if "administrative_area_level_1" in component["types"]:
                        return component["short_name"]
        
        return None
        
    except Exception:
        return None



def get_google_solar_data(address):
    """
    Get building data using Google Solar API
    """
    try:
        from backend.services.config import config
        
        # First geocode the address
        lat, lng = geocode_address(address)
        if not lat or not lng:
            return {"error": "Failed to geocode address"}
        
        # Query Google Solar API
        url = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
        params = {
            "location.latitude": lat,
            "location.longitude": lng,
            "key": config.google_api_key
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            return {"error": f"Google Solar API error: {response.status_code}"}
        
        data = response.json()
        
        if "name" not in data:
            return {"error": "No building data found"}
        
        # Log the structure of the response for debugging
        logger.info(f"Google Solar API response structure:")
        logger.info(f"  Top-level keys: {list(data.keys())}")
        
        if 'roofSegmentStats' in data:
            logger.info(f"  Found {len(data['roofSegmentStats'])} roof segments")
            for i, segment in enumerate(data['roofSegmentStats']):
                logger.info(f"    Segment {i}: {list(segment.keys())}")
                if 'boundingBox' in segment:
                    logger.info(f"      Bounding box: {segment['boundingBox']}")
        else:
            logger.info("  No 'roofSegmentStats' found in response")
            
        if 'wholeRoofStats' in data:
            logger.info(f"  Whole roof stats: {list(data['wholeRoofStats'].keys())}")
        else:
            logger.info("  No 'wholeRoofStats' found in response")
            
        if 'center' in data:
            logger.info(f"  Building center: {data['center']}")
        else:
            logger.info("  No 'center' found in response")
        
        # Check for solarPotential structure
        if 'solarPotential' in data:
            solar_potential = data['solarPotential']
            logger.info(f"  Solar potential keys: {list(solar_potential.keys())}")
            
            if 'roofSegmentStats' in solar_potential:
                logger.info(f"  Found {len(solar_potential['roofSegmentStats'])} roof segments in solarPotential")
                for i, segment in enumerate(solar_potential['roofSegmentStats']):
                    logger.info(f"    Solar segment {i}: {list(segment.keys())}")
                    if 'boundingBox' in segment:
                        logger.info(f"      Solar segment {i} bounding box: {segment['boundingBox']}")
            
            if 'wholeRoofStats' in solar_potential:
                logger.info(f"  Whole roof stats in solarPotential: {list(solar_potential['wholeRoofStats'].keys())}")
                if 'groundAreaMeters2' in solar_potential['wholeRoofStats']:
                    logger.info(f"    Ground area: {solar_potential['wholeRoofStats']['groundAreaMeters2']} m²")
        else:
            logger.info("  No 'solarPotential' found in response")
        
        # Return the raw API response
        return {
            "raw_api_response": data,
            "address": address,
            "latitude": lat,
            "longitude": lng
        }
        
    except Exception as e:
        logger.error(f"Google Solar API failed: {str(e)}")
        return {"error": f"Google Solar API failed: {str(e)}"}

