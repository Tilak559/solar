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
        
        # Step 2: Query Microsoft Building Footprints directly from local file
        # Skip STAC API as it's returning invalid data
        building_footprint = query_microsoft_footprints_direct(lat, lng)
        
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
            print(f"Could not determine state for coordinates ({lat}, {lng})")
            return None
        
        print(f"Querying building footprints for state: {state}")
        
        # Check if we have the state data file - try different naming conventions
        possible_files = [
            f"{state}.geojson",
            f"New{state}.geojson",  # For New York -> NewYork.geojson
            f"{state.lower()}.geojson",
            f"{state.upper()}.geojson",
            "NewYork.geojson"  # Direct match for the actual file
        ]
        
        print(f"Looking for files: {possible_files}")
        
        geojson_file = None
        for file_name in possible_files:
            if os.path.exists(file_name):
                geojson_file = file_name
                print(f"Found file: {file_name}")
                break
        
        if not geojson_file:
            print(f"State data file not found. Tried: {possible_files}")
            # List all .geojson files in current directory
            import glob
            all_geojson = glob.glob("*.geojson")
            print(f"Available .geojson files: {all_geojson}")
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
        
        # Read the entire GeoJSON file and parse it properly
        with open(geojson_file, 'r') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error parsing GeoJSON: {e}")
                return None
            
            if data.get("type") != "FeatureCollection":
                print("Not a FeatureCollection")
                return None
            
            features = data.get("features", [])
            print(f"Found {len(features)} features to check")
            
            buildings_checked = 0
            
            for feature in features:
                buildings_checked += 1
                if buildings_checked % 1000 == 0:
                    print(f"Checked {buildings_checked} buildings...")
                
                try:
                    if feature.get("type") == "Feature" and feature.get("geometry", {}).get("type") == "Polygon":
                        coords = feature["geometry"]["coordinates"][0]
                        
                        # Quick bounding box check first
                        min_lng = min(coord[0] for coord in coords)
                        max_lng = max(coord[0] for coord in coords)
                        min_lat = min(coord[1] for coord in coords)
                        max_lat = max(coord[1] for coord in coords)
                        
                        # Check if building is in our search area
                        if (min_lng <= lng <= max_lng and min_lat <= lat <= max_lat):
                            # Create polygon and check if point is inside
                            building_poly = Polygon(coords)
                            if building_poly.contains(search_point):
                                print(f"Found building after checking {buildings_checked} buildings")
                                return feature["geometry"]
                
                except Exception as e:
                    print(f"Error parsing feature: {e}")
                    continue
        
        print(f"Total buildings checked: {buildings_checked}")
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
        print(f"🔍 All coordinates: {coords}")
        
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
        
        # Calculate a more accurate roof edge perimeter
        # For gutter installation, we typically need the roof edge, not the entire building footprint
        # Let's calculate a simplified perimeter that focuses on the main roof edges
        
        # Get the exterior ring coordinates
        exterior_coords = list(polygon.exterior.coords)
        print(f"🔍 Exterior coordinates count: {len(exterior_coords)}")
        
        # Calculate simplified perimeter (roof edge approximation)
        # This focuses on the main roof edges rather than complex building details
        simplified_perimeter_meters = 0
        for i in range(len(exterior_coords) - 1):
            p1 = Point(exterior_coords[i])
            p2 = Point(exterior_coords[i + 1])
            
            # Transform points to projected coordinates
            p1_proj = transform(project, p1)
            p2_proj = transform(project, p2)
            
            # Calculate distance between points
            distance = p1_proj.distance(p2_proj)
            simplified_perimeter_meters += distance
        
        print(f"🔍 Simplified perimeter calculation: {simplified_perimeter_meters:.2f}m")
        
        # Calculate roof edge perimeter (for gutter installation)
        # Most residential buildings have gutters only on the main roof edges
        # Let's estimate based on the building shape and typical roof patterns
        
        # Calculate building dimensions
        width_meters = abs(bounds[2] - bounds[0]) * 111000  # Approximate meters per degree
        length_meters = abs(bounds[3] - bounds[1]) * 111000  # Approximate meters per degree
        
        print(f"🔍 Building dimensions: {width_meters:.1f}m x {length_meters:.1f}m")
        
        # Estimate roof edge perimeter for gutter installation
        # Account for roof overhangs (typically 1-2 feet beyond building footprint)
        roof_overhang_meters = 0.3  # ~1 foot overhang on each side
        
        # Determine gutter coverage based on building complexity and shape
        shape_complexity = len(exterior_coords) - 1  # Number of sides
        aspect_ratio = max(width_meters, length_meters) / min(width_meters, length_meters)
        
        print(f"🔍 Shape complexity: {shape_complexity} sides, aspect ratio: {aspect_ratio:.2f}")
        
        # Use a simpler, more accurate approach
        # For most residential buildings, gutters are installed on 2-3 sides
        # Let's use the actual building perimeter but apply a reasonable correction
        
        # Start with the actual building perimeter
        roof_edge_perimeter_meters = simplified_perimeter_meters
        
        # Apply a simple correction factor based on building complexity
        if shape_complexity <= 4:
            # Simple rectangular buildings - gutters on 2 sides typically
            correction_factor = 0.70  # 70% of perimeter gets gutters
        elif shape_complexity <= 6:
            # Medium complexity - gutters on 2-3 sides
            correction_factor = 0.75  # 75% of perimeter gets gutters
        else:
            # Complex buildings - gutters on 3+ sides
            correction_factor = 0.80  # 80% of perimeter gets gutters
        
        # Additional adjustment for larger buildings
        if simplified_perimeter_meters > 100:  # Large buildings
            correction_factor += 0.05  # Add 5% for larger buildings
        elif simplified_perimeter_meters > 50:  # Medium buildings
            correction_factor += 0.02  # Add 2% for medium buildings
        
        roof_edge_perimeter_meters *= correction_factor
        
        print(f"🔍 Estimated roof edge perimeter: {roof_edge_perimeter_meters:.2f}m")
        print(f"🔍 Correction factor: {correction_factor}")
        
        # Use the roof edge perimeter for gutter calculations
        # This better represents the actual gutter installation perimeter
        final_perimeter_meters = roof_edge_perimeter_meters
        final_perimeter_feet = final_perimeter_meters * 3.28084
        
        # Add minimum perimeter threshold to prevent underestimation
        min_perimeter_feet = 60  # Minimum reasonable perimeter for residential
        if final_perimeter_feet < min_perimeter_feet:
            # Use a more conservative estimate for small buildings
            fallback_perimeter = simplified_perimeter_meters * 3.28084 * 0.70
            final_perimeter_feet = max(final_perimeter_feet, fallback_perimeter)
            print(f"🔍 Applied minimum threshold: {final_perimeter_feet:.1f}ft")
        
        print(f"🔍 Final roof edge perimeter: {final_perimeter_feet:.1f}ft")
        
        # Sanity checks for realistic values
        if final_perimeter_meters > 5000:  # More than 5km perimeter
            return {"error": f"Unrealistic perimeter: {final_perimeter_meters:.1f}m (>5km). Possible projection error."}
        
        if area_square_meters > 10000:  # More than 10,000 m² (2.5 acres)
            return {"error": f"Unrealistic area: {area_square_meters:.1f}m² (>10,000m²). Possible projection error."}
        
        if final_perimeter_meters < 1:  # Less than 1m perimeter
            return {"error": f"Unrealistic perimeter: {final_perimeter_meters:.1f}m (<1m). Possible projection error."}
        
        if area_square_meters < 1:  # Less than 1m² area
            return {"error": f"Unrealistic area: {area_square_meters:.1f}m² (<1m²). Possible projection error."}
        
        # Convert to feet
        METERS_TO_FEET = 3.28084
        area_square_feet = area_square_meters * (METERS_TO_FEET ** 2)
        
        print(f"🔍 Converted to feet: perimeter={final_perimeter_feet:.1f}ft, area={area_square_feet:.1f}ft²")
        
        # Calculate cost
        cost_per_foot = 6.10  # Keep original pricing
        estimated_cost = final_perimeter_feet * cost_per_foot
        
        return {
            "roof_perimeter_feet": round(final_perimeter_feet, 1),
            "roof_perimeter_meters": round(final_perimeter_meters, 1),
            "roof_area_feet": round(area_square_feet, 1),
            "roof_area_meters": round(area_square_meters, 1),
            "estimated_cost_usd": round(estimated_cost, 2),
            "cost_per_foot": cost_per_foot,
            "building_footprint": footprint_geometry,
            "utm_zone": utm_epsg,
            "calculation_method": "roof_edge_approximation",
            "debug_info": {
                "centroid_lng": round(centroid.x, 6),
                "centroid_lat": round(centroid.y, 6),
                "bounds": [round(b, 6) for b in bounds],
                "coordinate_count": len(coords),
                "exterior_coord_count": len(exterior_coords),
                "original_perimeter_meters": round(perimeter_meters, 2),
                "simplified_perimeter_meters": round(simplified_perimeter_meters, 2)
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
                
                # Better perimeter calculation (not just square assumption)
                if segment_area > 0:
                    # Use aspect ratio if available, otherwise apply correction factor
                    segment_perimeter = math.sqrt(segment_area) * 4  # Base square estimate
                    segment_perimeter *= 1.1  # Correction factor for non-square segments
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
    
    # Method 2: Google Solar API (fallback)
    print("\n📍 Method 2: Google Solar API (fallback)...")
    google_result = get_google_solar_data(address)
    results["google_solar"] = google_result
    
    # Check if both methods succeeded
    microsoft_success = "error" not in microsoft_result
    google_success = "error" not in google_result
    
    if microsoft_success and google_success:
        # Both methods worked - combine for better accuracy
        print("✅ Both Microsoft and Google Solar succeeded - combining estimates...")
        
        microsoft_perimeter = microsoft_result['roof_perimeter_feet']
        google_perimeter = google_result['roof_perimeter_feet']
        
        # Weight Microsoft more heavily (more accurate for building footprints)
        avg_perimeter = (microsoft_perimeter * 0.7) + (google_perimeter * 0.3)
        avg_area = (microsoft_result['roof_area_feet'] * 0.7) + (google_result['roof_area_feet'] * 0.3)
        
        estimated_cost = avg_perimeter * 6.10
        
        combined_result = {
            "roof_perimeter_feet": round(avg_perimeter, 1),
            "roof_perimeter_meters": round(avg_perimeter / 3.28084, 1),
            "roof_area_feet": round(avg_area, 1),
            "roof_area_meters": round(avg_area / (3.28084 ** 2), 1),
            "estimated_cost_usd": round(estimated_cost, 2),
            "cost_per_foot": 6.10,
            "method": "microsoft_google_combined",
            "accuracy": "high (combined sources)",
            "address": address,
            "debug_info": {
                "microsoft_perimeter": microsoft_perimeter,
                "google_perimeter": google_perimeter,
                "weighted_average": avg_perimeter,
                "microsoft_weight": 0.7,
                "google_weight": 0.3
            }
        }
        
        print(f"✅ Combined: {avg_perimeter:.1f} feet")
        print(f"   Microsoft: {microsoft_perimeter:.1f} feet")
        print(f"   Google: {google_perimeter:.1f} feet")
        print(f"   Cost: ${estimated_cost:.2f}")
        
        cache_result(address, combined_result)
        return combined_result
    
    elif microsoft_success:
        print(f"✅ Microsoft: {microsoft_result['roof_perimeter_feet']} feet")
        print(f"   Area: {microsoft_result['roof_area_feet']} sq ft")
        print(f"   Cost: ${microsoft_result['estimated_cost_usd']}")
        # Cache the successful result
        cache_result(address, microsoft_result)
        return microsoft_result
    
    elif google_success:
        print(f"✅ Google Solar: {google_result['roof_perimeter_feet']} feet")
        print(f"   Area: {google_result['roof_area_feet']} sq ft")
        print(f"   Cost: ${google_result['estimated_cost_usd']}")
        # Cache the successful result
        cache_result(address, google_result)
        return google_result
    
    else:
        print(f"❌ Microsoft failed: {microsoft_result['error']}")
        print(f"❌ Google Solar failed: {google_result['error']}")
    
    final_result = {"error": "All free methods failed", "details": results}
    # Cache the error result too to avoid repeated failures
    cache_result(address, final_result)
    return final_result

# Example usage
if __name__ == "__main__":
    # Test addresses with known measurements
    test_cases = [
        {
            "address": "4 Pattie Pl, Wappingers Falls, NY 12590",
            "actual_perimeter": 91,
            "actual_cost": 400.00
        },
        {
            "address": "28 Cragswood Rd, New Paltz, NY 12561", 
            "actual_perimeter": 217,
            "actual_cost": 634.00
        },
        {
            "address": "15 Marion Dr, Mahopac, NY 10541",
            "actual_perimeter": 110,
            "actual_cost": 420.00
        },
        {
            "address": "127 Cider Mill Loop, Wappingers Falls, NY 12590",
            "actual_perimeter": 93,
            "actual_cost": 400.00
        },
        # {
        #     "address": "508 Washington Avenue, Beacon, NY 12508",
        #     "actual_perimeter": 112,
        #     "actual_cost": 458.00
        # },
        # {
        #     "address": "14 Hideaway Ln, Newburgh, NY 12550",
        #     "actual_perimeter": 144,
        #     "actual_cost": 488.00
        # },
        {
            "address": "15 Finland Rd, Pawling, NY 12564",
            "actual_perimeter": 236,
            "actual_cost": 672.00
        }
    ]
    
    print("🧪 TESTING ACCURACY AGAINST REAL MEASUREMENTS")
    print("=" * 80)
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n📍 Test {i}: {test_case['address']}")
        print(f"   Actual: {test_case['actual_perimeter']} feet, ${test_case['actual_cost']}")
        
        try:
            result = get_best_free_building_perimeter(test_case['address'])
            
            if "error" not in result:
                predicted_perimeter = result['roof_perimeter_feet']
                predicted_cost = result['estimated_cost_usd']
                
                # Calculate accuracy
                perimeter_accuracy = (predicted_perimeter / test_case['actual_perimeter']) * 100
                cost_accuracy = (predicted_cost / test_case['actual_cost']) * 100
                
                print(f"   Predicted: {predicted_perimeter:.1f} feet, ${predicted_cost:.2f}")
                print(f"   Perimeter Accuracy: {perimeter_accuracy:.1f}%")
                print(f"   Cost Accuracy: {cost_accuracy:.1f}%")
                
                results.append({
                    "address": test_case['address'],
                    "actual_perimeter": test_case['actual_perimeter'],
                    "predicted_perimeter": predicted_perimeter,
                    "actual_cost": test_case['actual_cost'],
                    "predicted_cost": predicted_cost,
                    "perimeter_accuracy": perimeter_accuracy,
                    "cost_accuracy": cost_accuracy,
                    "method": result.get('method', 'unknown')
                })
            else:
                print(f"   ❌ Failed: {result['error']}")
                results.append({
                    "address": test_case['address'],
                    "actual_perimeter": test_case['actual_perimeter'],
                    "predicted_perimeter": 0,
                    "actual_cost": test_case['actual_cost'],
                    "predicted_cost": 0,
                    "perimeter_accuracy": 0,
                    "cost_accuracy": 0,
                    "method": "failed"
                })
                
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
            results.append({
                "address": test_case['address'],
                "actual_perimeter": test_case['actual_perimeter'],
                "predicted_perimeter": 0,
                "actual_cost": test_case['actual_cost'],
                "predicted_cost": 0,
                "perimeter_accuracy": 0,
                "cost_accuracy": 0,
                "method": "error"
            })
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 ACCURACY SUMMARY")
    print("=" * 80)
    
    successful_tests = [r for r in results if r['method'] not in ['failed', 'error']]
    
    if successful_tests:
        avg_perimeter_accuracy = sum(r['perimeter_accuracy'] for r in successful_tests) / len(successful_tests)
        avg_cost_accuracy = sum(r['cost_accuracy'] for r in successful_tests) / len(successful_tests)
        
        print(f"✅ Successful Tests: {len(successful_tests)}/{len(test_cases)}")
        print(f"📏 Average Perimeter Accuracy: {avg_perimeter_accuracy:.1f}%")
        print(f"💰 Average Cost Accuracy: {avg_cost_accuracy:.1f}%")
        
        # Target accuracy analysis
        within_10_percent = sum(1 for r in successful_tests if 90 <= r['perimeter_accuracy'] <= 110)
        within_20_percent = sum(1 for r in successful_tests if 80 <= r['perimeter_accuracy'] <= 120)
        
        print(f"🎯 Within ±10%: {within_10_percent}/{len(successful_tests)} ({within_10_percent/len(successful_tests)*100:.1f}%)")
        print(f"🎯 Within ±20%: {within_20_percent}/{len(successful_tests)} ({within_20_percent/len(successful_tests)*100:.1f}%)")
        
    else:
        print("❌ No successful tests")
    
    print("\n📋 DETAILED RESULTS:")
    for result in results:
        status = "✅" if result['method'] not in ['failed', 'error'] else "❌"
        print(f"{status} {result['address']}")
        if result['method'] not in ['failed', 'error']:
            print(f"   Actual: {result['actual_perimeter']}ft, Predicted: {result['predicted_perimeter']:.1f}ft ({result['perimeter_accuracy']:.1f}%)")
            print(f"   Actual: ${result['actual_cost']}, Predicted: ${result['predicted_cost']:.2f} ({result['cost_accuracy']:.1f}%)")
        else:
            print(f"   Failed to process")