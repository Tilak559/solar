import requests
import json
import math
import os
from shapely.geometry import Point, Polygon
from shapely.ops import transform
import pyproj
from functools import partial
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))


# Simple cache to avoid repeated API calls
_result_cache = {}

def get_cached_result(address):
    """Get cached result for an address"""
    return _result_cache.get(address)

def cache_result(address, result):
    """Cache result for an address"""
    _result_cache[address] = result

def get_building_perimeter_microsoft(address):
    """
    Get accurate building perimeter using Microsoft Building Footprints (FREE)
    This is the most accurate method for building perimeters in the USA
    """
    try:
        # Step 1: Geocode the address
        lat, lng = geocode_address(address)
        if not lat or not lng:
            return {"error": "Failed to geocode address"}
        
        print(f"Location: {lat}, {lng}")
        
        # Step 2: Query Microsoft Building Footprints
        building_footprint = query_microsoft_building_footprints(lat, lng)
        
        if not building_footprint:
            return {"error": "No building footprint found at this location"}
        
        # Step 3: Calculate perimeter from the actual building footprint
        perimeter_result = calculate_building_perimeter(building_footprint)
        
        perimeter_result["address"] = address
        perimeter_result["method"] = "microsoft_building_footprints"
        perimeter_result["accuracy"] = "high"
        
        return perimeter_result
        
    except Exception as e:
        return {"error": f"Failed to get Microsoft building footprint: {str(e)}"}

def geocode_address(address):
    """Geocode address using Google Geocoding API"""
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

def query_microsoft_building_footprints(lat, lng):
    """
    Query Microsoft Building Footprints from Planetary Computer
    This data is completely free and very accurate
    """
    try:
        # Microsoft Building Footprints are available through Planetary Computer
        # Using the STAC API to query building footprints
        
        # Create a small bounding box around the point
        buffer = 0.0005  # ~50 meters
        bbox = [lng - buffer, lat - buffer, lng + buffer, lat + buffer]
        
        # Query Microsoft Planetary Computer STAC API
        stac_url = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
        
        query_params = {
            "collections": ["ms-buildings"],
            "bbox": bbox,
            "limit": 10
        }
        
        headers = {"Content-Type": "application/json"}
        response = requests.post(stac_url, json=query_params, headers=headers)
        
        if response.status_code != 200:
            print(f"STAC API error: {response.status_code}")
            # Fallback to direct GeoJSON approach
            return query_microsoft_footprints_direct(lat, lng)
        
        data = response.json()
        features = data.get("features", [])
        
        if not features:
            print("No features found in STAC, trying direct approach")
            return query_microsoft_footprints_direct(lat, lng)
        
        # Find the building footprint that contains our point
        point = Point(lng, lat)
        
        for feature in features:
            if feature.get("geometry", {}).get("type") == "Polygon":
                coords = feature["geometry"]["coordinates"][0]
                building_poly = Polygon(coords)
                
                if building_poly.contains(point):
                    return feature["geometry"]
        
        return None
        
    except Exception as e:
        print(f"Error querying Microsoft footprints: {str(e)}")
        return query_microsoft_footprints_direct(lat, lng)

def query_microsoft_footprints_direct(lat, lng):
    """
    Direct approach: Query Microsoft Building Footprints from downloaded GeoJSON data
    """
    try:
        # Determine which state the coordinates are in
        state = get_state_from_coords(lat, lng)
        if not state:
            return None
        
        print(f"Querying building footprints for state: {state}")
        
        # Check if we have the state data file
        geojson_file = f"{state}.geojson"
        if not os.path.exists(geojson_file):
            print(f"State data file {geojson_file} not found")
            return None
        
        print(f"Searching in {geojson_file} for building at ({lat}, {lng})")
        
        # Find the building footprint that contains our point
        building_footprint = find_building_in_geojson(geojson_file, lat, lng)
        
        if building_footprint:
            print(f"✅ Found building footprint in {state} data")
            return building_footprint
        else:
            print(f"❌ No building footprint found at this location")
            return None
        
    except Exception as e:
        print(f"Error in direct query: {str(e)}")
        return None

def find_building_in_geojson(geojson_file, lat, lng):
    """
    Efficiently search for a building footprint in a large GeoJSON file
    """
    try:
        import json
        from shapely.geometry import Point, Polygon
        
        # Create a point for our location
        search_point = Point(lng, lat)
        
        # Create a small bounding box around the point for initial filtering
        buffer = 0.001  # ~100 meters
        bbox = [lng - buffer, lat - buffer, lng + buffer, lat + buffer]
        
        print(f"Searching in bounding box: {bbox}")
        
        # Stream through the GeoJSON file to find matching buildings
        with open(geojson_file, 'r') as f:
            # Skip the opening of the FeatureCollection
            line = f.readline()
            if not line.strip().startswith('{"type":"FeatureCollection"'):
                print("Invalid GeoJSON format")
                return None
            
            # Skip the "features": [ line
            line = f.readline()
            
            buildings_checked = 0
            buildings_in_bbox = 0
            
            while True:
                line = f.readline()
                if not line or line.strip() == ']':
                    break
                
                # Skip empty lines and commas
                if not line.strip() or line.strip() == ',':
                    continue
                
                buildings_checked += 1
                if buildings_checked % 1000 == 0:
                    print(f"Checked {buildings_checked} buildings...")
                
                try:
                    # Parse the feature
                    feature = json.loads(line.rstrip(','))
                    
                    if feature.get("type") == "Feature" and feature.get("geometry", {}).get("type") == "Polygon":
                        coords = feature["geometry"]["coordinates"][0]
                        
                        # Quick bounding box check first
                        min_lng = min(coord[0] for coord in coords)
                        max_lng = max(coord[0] for coord in coords)
                        min_lat = min(coord[1] for coord in coords)
                        max_lat = max(coord[1] for coord in coords)
                        
                        # Check if building is in our search area
                        if (min_lng <= lng <= max_lng and min_lat <= lat <= max_lat):
                            buildings_in_bbox += 1
                            
                            # Create polygon and check if point is inside
                            building_poly = Polygon(coords)
                            if building_poly.contains(search_point):
                                print(f"Found building after checking {buildings_checked} buildings")
                                return feature["geometry"]
                
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"Error parsing feature: {e}")
                    continue
        
        print(f"Total buildings checked: {buildings_checked}")
        print(f"Buildings in bounding box: {buildings_in_bbox}")
        return None
        
    except Exception as e:
        print(f"Error reading GeoJSON file: {str(e)}")
        return None

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
        
        # Fallback to approximate bounds if API fails
        return get_state_from_approximate_bounds(lat, lng)
        
    except Exception:
        return get_state_from_approximate_bounds(lat, lng)

def get_state_from_approximate_bounds(lat, lng):
    """
    Fallback method using approximate state boundaries
    """
    # Major US states with approximate bounds
    state_bounds = {
        "NY": {"lat": (40.5, 45.0), "lng": (-79.8, -71.8)},
        "CA": {"lat": (32.5, 42.0), "lng": (-124.5, -114.1)},
        "TX": {"lat": (26.0, 36.7), "lng": (-106.6, -93.5)},
        "FL": {"lat": (24.4, 31.0), "lng": (-87.6, -80.0)},
        "IL": {"lat": (36.9, 42.5), "lng": (-91.5, -87.5)},
        "PA": {"lat": (39.7, 42.3), "lng": (-80.5, -74.7)},
        "OH": {"lat": (38.4, 42.0), "lng": (-84.8, -80.5)},
        "GA": {"lat": (30.3, 35.0), "lng": (-85.6, -80.8)},
        "NC": {"lat": (33.8, 36.6), "lng": (-84.3, -75.5)},
        "MI": {"lat": (41.7, 48.3), "lng": (-90.4, -82.4)}
    }
    
    for state, bounds in state_bounds.items():
        if (bounds["lat"][0] <= lat <= bounds["lat"][1] and 
            bounds["lng"][0] <= lng <= bounds["lng"][1]):
            return state
    
    return "Unknown"

def calculate_building_perimeter(footprint_geometry):
    """
    Calculate accurate building perimeter from Microsoft footprint geometry
    """
    try:
        if not footprint_geometry or footprint_geometry.get("type") != "Polygon":
            return {"error": "Invalid footprint geometry"}
        
        coords = footprint_geometry["coordinates"][0]
        
        # Debug: Log coordinate sample and validate order
        print(f"🔍 Polygon coordinates sample: {coords[:3]}")
        print(f"🔍 Coordinate format check - first coord: lng={coords[0][0]:.6f}, lat={coords[0][1]:.6f}")
        
        # Validate coordinate order is [lng, lat] (GeoJSON standard)
        if len(coords) < 3:
            return {"error": "Invalid polygon: insufficient coordinates"}
        
        # Create shapely polygon
        polygon = Polygon(coords)
        
        # Debug: Log polygon bounds
        bounds = polygon.bounds
        print(f"🔍 Polygon bounds: lng=({bounds[0]:.6f}, {bounds[2]:.6f}), lat=({bounds[1]:.6f}, {bounds[3]:.6f})")
        
        # Validate polygon
        if not polygon.is_valid:
            print("⚠️  Invalid polygon detected, attempting to fix...")
            from shapely.validation import make_valid
            polygon = make_valid(polygon)
            if not polygon.is_valid:
                return {"error": "Could not fix invalid polygon"}
        
        # Check for unrealistic bounds (sanity check)
        if abs(bounds[2] - bounds[0]) > 1.0 or abs(bounds[3] - bounds[1]) > 1.0:
            return {"error": "Polygon bounds too large - possible coordinate error"}
        
        # Get centroid to determine UTM zone
        centroid = polygon.centroid
        print(f"🔍 Centroid: lng={centroid.x:.6f}, lat={centroid.y:.6f}")
        
        # Robust UTM zone calculation with fallback
        try:
            utm_zone = int((centroid.x + 180) / 6) + 1
            # Validate UTM zone is reasonable
            if utm_zone < 1 or utm_zone > 60:
                raise ValueError(f"Invalid UTM zone: {utm_zone}")
            
            utm_epsg = f"EPSG:326{utm_zone:02d}" if centroid.y >= 0 else f"EPSG:327{utm_zone:02d}"
            print(f"🔍 Using UTM zone: {utm_zone}, EPSG: {utm_epsg}")
            
            # Test the transformation
            project = pyproj.Transformer.from_crs("EPSG:4326", utm_epsg, always_xy=True).transform
            
        except Exception as e:
            print(f"⚠️  UTM calculation failed: {e}, falling back to Web Mercator")
            utm_epsg = "EPSG:3857"
            project = pyproj.Transformer.from_crs("EPSG:4326", utm_epsg, always_xy=True).transform
        
        # Transform polygon to projected coordinate system for accurate distance calculation
        polygon_projected = transform(project, polygon)
        
        # Calculate perimeter and area in meters
        perimeter_meters = polygon_projected.length
        area_square_meters = polygon_projected.area
        
        print(f"🔍 Raw calculations: perimeter={perimeter_meters:.2f}m, area={area_square_meters:.2f}m²")
        
        # Sanity checks for realistic values
        if perimeter_meters > 5000:  # More than 5km perimeter
            return {"error": f"Unrealistic perimeter: {perimeter_meters:.1f}m (>5km). Possible projection error."}
        
        if area_square_meters > 10000:  # More than 10,000 m² (2.5 acres)
            return {"error": f"Unrealistic area: {area_square_meters:.1f}m² (>10,000m²). Possible projection error."}
        
        if perimeter_meters < 1:  # Less than 1m perimeter
            return {"error": f"Unrealistic perimeter: {perimeter_meters:.1f}m (<1m). Possible projection error."}
        
        if area_square_meters < 1:  # Less than 1m² area
            return {"error": f"Unrealistic area: {area_square_meters:.1f}m² (<1m²). Possible projection error."}
        
        # Convert to feet
        METERS_TO_FEET = 3.28084
        perimeter_feet = perimeter_meters * METERS_TO_FEET
        area_square_feet = area_square_meters * (METERS_TO_FEET ** 2)
        
        print(f"🔍 Converted to feet: perimeter={perimeter_feet:.1f}ft, area={area_square_feet:.1f}ft²")
        
        # Calculate cost
        cost_per_foot = 6.10
        estimated_cost = perimeter_feet * cost_per_foot
        
        return {
            "roof_perimeter_feet": round(perimeter_feet, 1),
            "roof_perimeter_meters": round(perimeter_meters, 1),
            "roof_area_feet": round(area_square_feet, 1),
            "roof_area_meters": round(area_square_meters, 1),
            "estimated_cost_usd": round(estimated_cost, 2),
            "cost_per_foot": cost_per_foot,
            "building_footprint": footprint_geometry,
            "utm_zone": utm_epsg,
            "calculation_method": "precise_geodetic",
            "debug_info": {
                "centroid_lng": round(centroid.x, 6),
                "centroid_lat": round(centroid.y, 6),
                "bounds": [round(b, 6) for b in bounds],
                "coordinate_count": len(coords)
            }
        }
        
    except Exception as e:
        return {"error": f"Failed to calculate perimeter: {str(e)}"}

def setup_microsoft_footprints_local():
    """
    Instructions for setting up local Microsoft Building Footprints data
    For production use, you'd download and index the state data locally
    """
    instructions = """
    🔧 SETUP INSTRUCTIONS FOR PRODUCTION:
    
    1. Download Microsoft Building Footprints for your state:
       https://github.com/microsoft/USBuildingFootprints
    
    2. Set up local database (PostGIS recommended):
       - Import GeoJSON data into PostGIS
       - Create spatial index for fast queries
    
    3. Alternative: Use Microsoft Planetary Computer API:
       - Register for free access
       - Query building footprints via STAC API
    
    4. For high-volume use:
       - Cache frequently accessed footprints
       - Use spatial indexing for performance
    """
    
    return instructions

# Alternative: Roofr API Integration (if they provide API access)
def query_roofr_api(address):
    """
    Integration with Roofr API (if available)
    Roofr offers free roof measurements
    """
    try:
        # This would require Roofr API credentials
        # Contact Roofr for API access details
        
        # Placeholder implementation
        return {
            "note": "Roofr offers free roof measurements",
            "api_status": "Contact Roofr for API access",
            "website": "https://roofr.com/measurements",
            "features": "Free aerial, satellite, and drone roof measurements"
        }
        
    except Exception as e:
        return {"error": f"Roofr API error: {str(e)}"}

def get_google_solar_data(address):
    """
    Get building data using Google Solar API as fallback
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
        
        # Extract building dimensions
        building_stats = data.get("buildingStats", {})
        roof_segment_stats = data.get("roofSegmentStats", [])
        
        # Calculate perimeter from roof segments
        total_perimeter = 0
        total_area = 0
        
        for segment in roof_segment_stats:
            if "pitchDegrees" in segment:
                # Calculate segment perimeter and area
                segment_area = segment.get("groundAreaMeters2", 0)
                total_area += segment_area
                
                # Approximate perimeter from area (simplified)
                # For rectangular segments, perimeter ≈ 2 * (length + width)
                # Assuming roughly square segments for approximation
                if segment_area > 0:
                    side_length = math.sqrt(segment_area)
                    segment_perimeter = 4 * side_length
                    total_perimeter += segment_perimeter
        
        # Convert to feet
        METERS_TO_FEET = 3.28084
        perimeter_feet = total_perimeter * METERS_TO_FEET
        area_square_feet = total_area * (METERS_TO_FEET ** 2)
        
        # Calculate cost
        cost_per_foot = 6.10
        estimated_cost = perimeter_feet * cost_per_foot
        
        return {
            "roof_perimeter_feet": round(perimeter_feet, 1),
            "roof_perimeter_meters": round(total_perimeter, 1),
            "roof_area_feet": round(area_square_feet, 1),
            "roof_area_meters": round(total_area, 1),
            "estimated_cost_usd": round(estimated_cost, 2),
            "cost_per_foot": cost_per_foot,
            "method": "google_solar_api",
            "accuracy": "medium",
            "address": address
        }
        
    except Exception as e:
        return {"error": f"Google Solar API failed: {str(e)}"}

# Main function to try all free methods
def get_best_free_building_perimeter(address):
    """
    Try all available free methods to get building perimeter
    """
    # Check cache first
    cached_result = get_cached_result(address)
    if cached_result:
        print(f"📋 Using cached result for: {address}")
        return cached_result
    
    results = {}
    
    print(f"🔍 Finding building perimeter for: {address}")
    print("=" * 60)
    
    # Method 1: Microsoft Building Footprints (most accurate)
    print("📍 Method 1: Microsoft Building Footprints (FREE)...")
    microsoft_result = get_building_perimeter_microsoft(address)
    results["microsoft"] = microsoft_result
    
    if "error" not in microsoft_result:
        print(f"✅ Microsoft: {microsoft_result['roof_perimeter_feet']} feet")
        print(f"   Area: {microsoft_result['roof_area_feet']} sq ft")
        print(f"   Cost: ${microsoft_result['estimated_cost_usd']}")
        # Cache the successful result
        cache_result(address, microsoft_result)
        return microsoft_result
    else:
        print(f"❌ Microsoft failed: {microsoft_result['error']}")
    
    # Method 2: Google Solar API (fallback)
    print("\n📍 Method 2: Google Solar API (fallback)...")
    google_result = get_google_solar_data(address)
    results["google_solar"] = google_result
    
    if "error" not in google_result:
        print(f"✅ Google Solar: {google_result['roof_perimeter_feet']} feet")
        print(f"   Area: {google_result['roof_area_feet']} sq ft")
        print(f"   Cost: ${google_result['estimated_cost_usd']}")
        # Cache the successful result
        cache_result(address, google_result)
        return google_result
    else:
        print(f"❌ Google Solar failed: {google_result['error']}")
    
    final_result = {"error": "All free methods failed", "details": results}
    # Cache the error result too to avoid repeated failures
    cache_result(address, final_result)
    return final_result

# Example usage
if __name__ == "__main__":
    # Test address
    test_address = "4 Pattie Pl Wappingers Falls, NY 12590"
    
    result = get_best_free_building_perimeter(test_address)
    
    if "error" not in result:
        print(f"\n🎯 FINAL RESULT (FREE METHOD):")
        print(f"Address: {test_address}")
        print(f"Building Perimeter: {result['roof_perimeter_feet']} feet")
        print(f"Building Area: {result['roof_area_feet']} sq ft")
        print(f"Estimated Gutter Cost: ${result['estimated_cost_usd']}")
        print(f"Method: {result['method']}")
        print(f"Accuracy: {result['accuracy']}")
        
        # Print debug info if available
        if 'debug_info' in result:
            print(f"\n🔍 Debug Information:")
            print(json.dumps(result['debug_info'], indent=2))
    else:
        print(f"❌ All methods failed: {result['error']}")
        if 'details' in result:
            print(f"\n📋 Method Details:")
            print(json.dumps(result['details'], indent=2))
    
    # Print setup instructions
    print(f"\n{setup_microsoft_footprints_local()}")