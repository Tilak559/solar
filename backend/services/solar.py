import requests
from config import config
from google.oauth2 import service_account
import google.auth.transport.requests
import json
import rasterio
import cv2
import numpy as np
from shapely.geometry import Polygon
import tempfile
import os

def get_access_token():
    try:
        credentials = service_account.Credentials.from_service_account_file(
            config.google_credentials_path,
            scopes=config.google_scopes_list
        )
        
        # Refresh the credentials to get a token
        credentials.refresh(google.auth.transport.requests.Request())
        token = credentials.token
        
        return token
    except FileNotFoundError as e:
        return None
    except Exception as e:
        return None

def estimate_gutter_length(solar_data, auth_headers=None, max_area_m2=None):

    try:
        # Get the mask URL from the response
        mask_url = solar_data.get("maskUrl")
        if not mask_url:
            return {"error": "No mask URL found in solar data"}
        
        # Download the mask file with authentication
        print(f"Downloading mask from: {mask_url}")
        
        if auth_headers:
            response = requests.get(mask_url, headers=auth_headers)
        else:
            response = requests.get(mask_url)
        
        if response.status_code != 200:
            return {"error": f"Failed to download mask: {response.status_code}"}
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp_file:
            tmp_file.write(response.content)
            tmp_file_path = tmp_file.name
        
        try:
            # Load the mask using rasterio
            with rasterio.open(tmp_file_path) as src:
                mask = src.read(1)  # First band
                transform = src.transform
                crs = src.crs
                
                print(f"Mask loaded: shape={mask.shape}, dtype={mask.dtype}")
                print(f"Transform: {transform}")
                print(f"CRS: {crs}")
            
            # Binarize the mask (convert to binary image)
            binary = (mask > 0).astype(np.uint8) * 255
            
            # Find contours (building boundaries)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            print(f"Found {len(contours)} contours")
            
            # Get resolution in meters per pixel
            # For UTM coordinates, transform.a gives meters per pixel
            resolution_meters_per_pixel = abs(transform.a)
            print(f"Resolution: {resolution_meters_per_pixel} meters per pixel")
            
            total_length_m = 0
            total_area_m2 = 0
            contour_details = []
            
            for i, contour in enumerate(contours):
                area_pixels = cv2.contourArea(contour)
                area_meters_sq = area_pixels * (resolution_meters_per_pixel ** 2)
                
                # Skip very small contours (likely noise) and very large ones (likely wrong building)
                if area_meters_sq < 10:
                    print(f"Skipping contour {i}: area {area_meters_sq:.2f} m² (outside range 10-{max_area_m2} m²)")
                    continue
                
                perimeter_pixels = cv2.arcLength(contour, True)
                perimeter_meters = perimeter_pixels * resolution_meters_per_pixel
                total_length_m += perimeter_meters
                total_area_m2 += area_meters_sq
                
                contour_details.append({
                    "contour_index": i,
                    "area_meters_sq": area_meters_sq,
                    "perimeter_meters": perimeter_meters,
                    "num_points": len(contour)
                })
                
                print(f"Contour {i}: {area_meters_sq:.2f} m², {perimeter_meters:.2f} m perimeter")
            
            # Calculate cost estimation (assuming $20 per meter)
            cost_per_meter = 20
            estimated_cost = total_length_m * cost_per_meter
            
            return {
                "summary": {
                    "total_roof_area_m2": round(total_area_m2, 2),
                    "total_gutter_length_m": round(total_length_m, 2),
                    "estimated_cost_usd": round(estimated_cost, 2),
                    "cost_per_meter_usd": cost_per_meter
                },
                "technical_details": {
                    "resolution_meters_per_pixel": resolution_meters_per_pixel,
                    "num_contours_analyzed": len(contour_details),
                    "mask_shape": mask.shape,
                    "mask_dtype": str(mask.dtype),
                    # "max_area_filter_m2": max_area_m2
                },
                "contour_details": contour_details
            }
            
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                
    except Exception as e:
        return {"error": f"Failed to analyze roof mask: {str(e)}"}

def estimator(address):
    # Geocoding API call
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": address,
        "key": config.google_api_key
    }
    
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        return {"error": f"Failed to retrieve data from Google Geocoding API: {response.status_code}"}
    
    data = response.json()
    
    if not data.get("results"):
        return {"error": "No results found for this address"}
    
    result = data["results"][0]
    location = result["geometry"]["location"]
    latitude = location["lat"]
    longitude = location["lng"]
    place_id = result.get("place_id")
    
    print(f"Location found: lat={latitude}, lng={longitude}")
    print(f"Place ID: {place_id}")

    # Get access token for Solar API
    token = get_access_token()
    if not token:
        return {"error": "Failed to get access token for Solar API"}
    
    headers = {
        "Authorization": f"Bearer {token}",
        "x-goog-user-project": config.project_id
    }

    print("Using dataLayers method with improved filtering")
    url = (
        "https://solar.googleapis.com/v1/dataLayers:get"
        f"?location.latitude={latitude}"
        f"&location.longitude={longitude}"
        "&radius_meters=50"  # Reduced radius for more precision
        "&required_quality=HIGH"
    )
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        return {"error": f"Failed to retrieve data from Google Solar API: {response.status_code}"}
    
    data = response.json()
    print(f"Solar API response: {json.dumps(data, indent=2)}")
    
    # Estimate gutter length from the solar data with authentication headers and better filtering
    gutter_estimate = estimate_gutter_length(data, auth_headers=headers, max_area_m2=None)
    
    return {
        "solar_data": data,
        "gutter_estimate": gutter_estimate,
        "method": "dataLayers"
    }

