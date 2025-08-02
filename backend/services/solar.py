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
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for server environments

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

def show_rgb_image(rgb_url, headers=None, save_path=None):
    """Display and optionally save the original RGB satellite image"""
    try:
        response = requests.get(rgb_url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to download RGB image: {response.status_code}")
            return None
            
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp_file:
            tmp_file.write(response.content)
            tmp_path = tmp_file.name

        with rasterio.open(tmp_path) as src:
            rgb = src.read([1, 2, 3])  # R, G, B
            rgb = np.transpose(rgb, (1, 2, 0))  # CHW → HWC
            rgb = rgb / 255.0  # Normalize to 0-1 range

        plt.figure(figsize=(10, 8))
        plt.imshow(rgb)
        plt.title("Original RGB Satellite Image")
        plt.axis("off")
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"RGB image saved to: {save_path}")
        else:
            plt.show()
        
        plt.close()
        os.remove(tmp_path)
        return rgb
        
    except Exception as e:
        print(f"Error showing RGB image: {str(e)}")
        return None

def visualize_mask_processing(mask, binary, contours, save_path=None):
    """Visualize mask processing steps and contour detection"""
    try:
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        
        # Original mask
        axes[0, 0].imshow(mask, cmap="gray")
        axes[0, 0].set_title("Raw Mask")
        axes[0, 0].axis("off")
        
        # Binary mask
        axes[0, 1].imshow(binary, cmap="gray")
        axes[0, 1].set_title("Binary Mask")
        axes[0, 1].axis("off")
        
        # Contour overlay on binary mask
        contour_overlay = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(contour_overlay, contours, -1, (0, 255, 0), 2)  # Green outlines
        contour_overlay = cv2.cvtColor(contour_overlay, cv2.COLOR_BGR2RGB)
        axes[1, 0].imshow(contour_overlay)
        axes[1, 0].set_title(f"Contour Overlay ({len(contours)} contours)")
        axes[1, 0].axis("off")
        
        # Contour overlay on original mask
        mask_overlay = cv2.cvtColor(mask.astype(np.uint8), cv2.COLOR_GRAY2BGR)
        cv2.drawContours(mask_overlay, contours, -1, (0, 255, 0), 2)  # Green outlines
        mask_overlay = cv2.cvtColor(mask_overlay, cv2.COLOR_BGR2RGB)
        axes[1, 1].imshow(mask_overlay)
        axes[1, 1].set_title("Contours on Original Mask")
        axes[1, 1].axis("off")
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Mask processing visualization saved to: {save_path}")
        else:
            plt.show()
        
        plt.close()
        
    except Exception as e:
        print(f"Error visualizing mask processing: {str(e)}")

def estimate_gutter_length(solar_data, auth_headers=None, max_area_m2=None, save_visualizations=False):

    try:
        # Get the mask URL from the response
        mask_url = solar_data.get("maskUrl")
        rgb_url = solar_data.get("rgbUrl")
        
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
            
            # Visualize the processing steps if requested
            if save_visualizations:
                # Create output directory if it doesn't exist
                os.makedirs("visualizations", exist_ok=True)
                
                # Show RGB image if available
                if rgb_url:
                    rgb_path = "visualizations/rgb_image.png"
                    show_rgb_image(rgb_url, auth_headers, rgb_path)
                
                # Show mask processing steps
                mask_path = "visualizations/mask_processing.png"
                visualize_mask_processing(mask, binary, contours, mask_path)
            
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
            
            result = {
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
            
            # Add visualization paths if images were saved
            if save_visualizations:
                result["visualizations"] = {
                    "rgb_image": "visualizations/rgb_image.png" if rgb_url else None,
                    "mask_processing": "visualizations/mask_processing.png"
                }
            
            return result
            
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                
    except Exception as e:
        return {"error": f"Failed to analyze roof mask: {str(e)}"}

def estimator(address, save_visualizations=False):
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

    # Try buildingInsights first (more precise for single buildings)
    if place_id:
        print(f"Trying buildingInsights with place_id: {place_id}")
        
        # Try buildingInsights with bearer token authentication
        building_url = f"https://solar.googleapis.com/v1/buildingInsights/{place_id}"
        building_response = requests.get(building_url, headers=headers)
        
        if building_response.status_code == 200:
            building_data = building_response.json()
            print(f"Building insights found: {json.dumps(building_data, indent=2)}")
            
            # Extract measurements from building insights
            building_measurements = extract_building_measurements(building_data)
            
            return {
                "solar_data": building_data,
                "gutter_estimate": building_measurements,
                "method": "buildingInsights"
            }
        else:
            print(f"Building insights not available for this address (404 is normal)")
    
    # Fallback to dataLayers method (satellite imagery analysis)
    print("Using dataLayers method (satellite imagery analysis)")
    url = (
        "https://solar.googleapis.com/v1/dataLayers:get"
        f"?location.latitude={latitude}"
        f"&location.longitude={longitude}"
        "&radius_meters=20"  # Reduced radius for more precision
        "&required_quality=HIGH"
    )
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        return {"error": f"Failed to retrieve data from Google Solar API: {response.status_code}"}
    
    data = response.json()
    print(f"Solar API response: {json.dumps(data, indent=2)}")
    
    # Estimate gutter length from the solar data with authentication headers and better filtering
    gutter_estimate = estimate_gutter_length(data, auth_headers=headers, max_area_m2=None, save_visualizations=save_visualizations)
    
    return {
        "solar_data": data,
        "gutter_estimate": gutter_estimate,
        "method": "dataLayers"
    }

def extract_building_measurements(building_data):
    try:
        # Extract roof segments from building insights
        roof_segments = building_data.get("roofSegmentStats", [])
        
        total_area_m2 = 0
        total_perimeter_m = 0
        
        for segment in roof_segments:
            # Convert square feet to square meters (1 sq ft = 0.092903 sq m)
            area_sqft = segment.get("groundAreaMeters2", 0)
            total_area_m2 += area_sqft
            
            # Calculate perimeter from area (approximation for rectangular segments)
            # Assuming roughly square segments, perimeter ≈ 4 * sqrt(area)
            if area_sqft > 0:
                perimeter_m = 4 * (area_sqft ** 0.5)
                total_perimeter_m += perimeter_m
        
        # Calculate cost estimation
        cost_per_meter = 20
        estimated_cost = total_perimeter_m * cost_per_meter
        
        return {
            "summary": {
                "total_roof_area_m2": round(total_area_m2, 2),
                "total_gutter_length_m": round(total_perimeter_m, 2),
                "estimated_cost_usd": round(estimated_cost, 2),
                "cost_per_meter_usd": cost_per_meter
            },
            "technical_details": {
                "num_roof_segments": len(roof_segments),
                "method": "buildingInsights"
            },
            "roof_segments": roof_segments
        }
        
    except Exception as e:
        return {"error": f"Failed to extract building measurements: {str(e)}"}