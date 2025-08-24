import math
import logging
from typing import TypedDict, List, Dict, Any, Optional, Tuple
import statistics
from dataclasses import dataclass

# Set up logging
logger = logging.getLogger(__name__)

class GutterEstimate(TypedDict):
    eave_length_ft: float      # main ridge one side, before waste
    total_gutter_ft: int       # summed ridges after coverage + waste, rounded up
    waste_factor: float        # e.g., 0.02
    warnings: List[str]

class RidgeInfo(TypedDict):
    azimuth: float             # representative azimuth (area-weighted)
    eave_ft: float            # eave length in feet
    area_m2: float            # total area of ridge
    coverage: float           # coverage factor (0.4, 0.65, or 1.0)
    contrib_ft: float         # contribution to total gutter

class DetailedGutterEstimate(GutterEstimate):
    ridges: List[RidgeInfo]   # detailed breakdown by ridge

# Configurable constants
MIN_PLANE_AREA = 15.0
AZIMUTH_BIN_DEG = 10.0
SPATIAL_JOIN_M = 7.0
SECONDARY_COVERAGE = 0.65
TINY_COVERAGE = 0.4


def calculate_meters_per_degree(latitude: float) -> tuple[float, float]:
    """Calculate meters per degree at given latitude"""
    lat_rad = math.radians(latitude)
    meters_per_deg_lon = 111320 * math.cos(lat_rad)
    meters_per_deg_lat = 111132
    return meters_per_deg_lon, meters_per_deg_lat


def calculate_segment_dimensions(
    bounding_box: Dict[str, Dict[str, float]], 
    meters_per_deg_lon: float, 
    meters_per_deg_lat: float
) -> tuple[float, float, tuple[float, float]]:
    """
    Calculate segment dimensions and center from bounding box
    
    Returns:
        eave_m: longer dimension (runs along longer plan-view edge)
        depth_m: shorter dimension (roof depth)
        center_m: center point in meters (x, y)
    """
    sw = bounding_box['sw']
    ne = bounding_box['ne']
    
    # Calculate spans in degrees
    lon_span = abs(ne['longitude'] - sw['longitude'])
    lat_span = abs(ne['latitude'] - sw['latitude'])
    
    # Convert to meters
    width_m = lon_span * meters_per_deg_lon
    depth_m = lat_span * meters_per_deg_lat
    
    # Eave length is the longer dimension
    eave_m = max(width_m, depth_m)
    depth_m = min(width_m, depth_m)
    
    # Calculate center in meters (project lat/lon deltas)
    center_lon = (sw['longitude'] + ne['longitude']) / 2
    center_lat = (sw['latitude'] + ne['latitude']) / 2
    
    # Convert center to meters relative to sw corner
    center_x = (center_lon - sw['longitude']) * meters_per_deg_lon
    center_y = (center_lat - sw['latitude']) * meters_per_deg_lat
    
    return eave_m, depth_m, (center_x, center_y)


def derive_azimuth_from_bbox(bounding_box: Dict[str, Dict[str, float]]) -> float:
    """Derive azimuth from bounding box if not provided"""
    sw = bounding_box['sw']
    ne = bounding_box['ne']
    
    # Calculate the long edge direction
    lon_delta = ne['longitude'] - sw['longitude']
    lat_delta = ne['latitude'] - sw['latitude']
    
    # Use atan2 to get angle, convert to degrees, normalize to [0, 360)
    azimuth = math.degrees(math.atan2(lat_delta, lon_delta))
    if azimuth < 0:
        azimuth += 360
    
    return azimuth


def spatial_distance(center1: tuple[float, float], center2: tuple[float, float]) -> float:
    """Calculate Euclidean distance between two centers in meters"""
    dx = center1[0] - center2[0]
    dy = center1[1] - center2[1]
    return math.sqrt(dx*dx + dy*dy)


def cluster_by_proximity(segments: List[Dict], max_distance_m: float) -> List[List[Dict]]:
    """
    Cluster segments by spatial proximity using union-find approach
    
    Args:
        segments: List of segment records with 'center_m' key
        max_distance_m: Maximum distance for clustering
    
    Returns:
        List of clusters (each cluster is a list of segments)
    """
    if len(segments) <= 1:
        return [segments]
    
    # Union-find implementation
    parent = list(range(len(segments)))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    
    def union(x, y):
        parent[find(x)] = find(y)
    
    # Check all pairs and union if within distance
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            if spatial_distance(segments[i]['center_m'], segments[j]['center_m']) <= max_distance_m:
                union(i, j)
    
    # Group by root
    clusters = {}
    for i in range(len(segments)):
        root = find(i)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(segments[i])
    
    return list(clusters.values())


def tukey_bounds(values: List[float]) -> tuple[float, float]:
    """Calculate Tukey outlier bounds using IQR method"""
    if len(values) < 4:
        return (min(values), max(values))
    qs = statistics.quantiles(values, n=4, method="inclusive")
    q1, q3 = qs[0], qs[2]
    iqr = q3 - q1
    return (q1 - 1.5 * iqr, q3 + 1.5 * iqr)


def validate_with_area_check(
    eave_length_m: float,
    ground_area_m2: float,
    segment_depths: List[float]
) -> List[str]:
    """Validate eave length against ground area"""
    warnings = []
    
    if not segment_depths:
        return warnings
    
    # Use median depth for more robust calculation
    median_depth = statistics.median(segment_depths)
    
    if median_depth > 0:
        # Calculate implied width from area
        width_from_area = ground_area_m2 / median_depth
        
        # Check if there's significant discrepancy
        discrepancy_ratio = abs(width_from_area - eave_length_m) / eave_length_m
        
        if discrepancy_ratio > 0.25:
            warnings.append(
                f"Area-based width ({width_from_area:.1f}m) differs significantly "
                f"from coordinate-based eave length ({eave_length_m:.1f}m). "
                f"Consider manual verification."
            )
    
    return warnings


def estimate_gutter_feet(
    data: Dict[str, Any], 
    waste_factor: float = 0.02,
    min_plane_area: float = MIN_PLANE_AREA,
    azimuth_bin_deg: float = AZIMUTH_BIN_DEG,
    spatial_join_m: float = SPATIAL_JOIN_M,
    secondary_coverage: float = SECONDARY_COVERAGE,
    tiny_coverage: float = TINY_COVERAGE
) -> GutterEstimate:
    """
    Estimate gutter requirements for multi-ridge roofs
    
    Uses ridge detection with azimuth clustering and spatial proximity to identify
    separate roof sections and calculate appropriate coverage factors.
    """
    warnings = []
    
    try:
        logger.info(f"Starting multi-ridge gutter estimation with data keys: {list(data.keys())}")
        
        # Extract roof segments
        roof_segments = data.get('roofSegmentStats', [])
        logger.info(f"Found {len(roof_segments)} roof segments")
        
        if not roof_segments:
            logger.warning("No roof segments found in data")
            return {
                "eave_length_ft": 0.0,
                "total_gutter_ft": 0,
                "waste_factor": waste_factor,
                "warnings": ["No roof segments found in data"]
            }
        
        # Get building center latitude for coordinate calculations
        building_center = data.get('raw', {}).get('center', {})
        logger.info(f"Building center: {building_center}")
        
        if not building_center:
            # Fallback: use average of segment centers
            segment_centers = []
            for segment in roof_segments:
                if 'center' in segment:
                    segment_centers.append(segment['center']['latitude'])
            
            if segment_centers:
                building_lat = statistics.mean(segment_centers)
                logger.info(f"Using average segment center latitude: {building_lat}")
            else:
                # Last resort: use first segment's bounding box center
                first_box = roof_segments[0].get('boundingBox', {})
                if first_box and 'sw' in first_box and 'ne' in first_box:
                    building_lat = (first_box['sw']['latitude'] + first_box['ne']['latitude']) / 2
                    logger.info(f"Using bounding box center latitude: {building_lat}")
                else:
                    building_lat = 40.0  # Default fallback
                    warnings.append("Using default latitude (40.0°) for calculations")
                    logger.warning("Using default latitude (40.0°) for calculations")
        else:
            building_lat = building_center['latitude']
            logger.info(f"Using building center latitude: {building_lat}")
        
        # Calculate meters per degree at the building latitude
        meters_per_deg_lon, meters_per_deg_lat = calculate_meters_per_degree(building_lat)
        logger.info(f"Meters per degree - lon: {meters_per_deg_lon:.2f}, lat: {meters_per_deg_lat:.2f}")
        
        # Collect segment records with detailed information
        seg_records = []
        tiny_segments = []
        
        for i, segment in enumerate(roof_segments):
            bounding_box = segment.get('boundingBox')
            if bounding_box and 'sw' in bounding_box and 'ne' in bounding_box:
                eave_m, depth_m, center_m = calculate_segment_dimensions(
                    bounding_box, meters_per_deg_lon, meters_per_deg_lat
                )
                
                # Get area and azimuth
                stats = segment.get('stats', {})
                area_m2 = stats.get('groundAreaMeters2') or stats.get('areaMeters2') or 0.0
                az = segment.get('azimuthDegrees')
                
                if az is None:
                    az = derive_azimuth_from_bbox(bounding_box)
                    logger.info(f"Derived azimuth {az:.1f}° for segment {i} from bounding box")
                
                seg_record = {
                    "eave_m": eave_m, 
                    "depth_m": depth_m, 
                    "area_m2": area_m2, 
                    "az": float(az),
                    "center_m": center_m,
                    "segment_id": i
                }
                
                # Separate tiny segments
                if area_m2 >= min_plane_area:
                    seg_records.append(seg_record)
                    logger.info(f"Segment {i}: eave={eave_m:.2f}m, depth={depth_m:.2f}m, area={area_m2:.2f}m², az={az:.1f}°")
                else:
                    tiny_segments.append(seg_record)
                    logger.info(f"Tiny segment {i}: eave={eave_m:.2f}m, depth={depth_m:.2f}m, area={area_m2:.2f}m², az={az:.1f}° (ignored)")
            else:
                logger.warning(f"Segment {i} missing or invalid bounding box: {bounding_box}")
        
        if not seg_records:
            logger.error("No valid segments >= minimum area found")
            return {
                "eave_length_ft": 0.0,
                "total_gutter_ft": 0,
                "waste_factor": waste_factor,
                "warnings": ["No valid segments >= minimum area found"]
            }
        
        # 1. Pre-filter small planes (already done above)
        logger.info(f"Processing {len(seg_records)} main segments, {len(tiny_segments)} tiny segments")
        
        # 2. Ridge detection with azimuth clustering
        # Map azimuth into [0, 180) because opposing planes share one ridge
        for r in seg_records:
            r["az_half"] = r["az"] % 180.0
        
        # Bin by azimuth with configurable band width
        azimuth_bins = {}
        for seg in seg_records:
            bin_key = int(seg["az_half"] / azimuth_bin_deg) * azimuth_bin_deg
            if bin_key not in azimuth_bins:
                azimuth_bins[bin_key] = []
            azimuth_bins[bin_key].append(seg)
        
        logger.info(f"Azimuth bins: {list(azimuth_bins.keys())}")
        
        # 3. Spatial clustering within each azimuth bin
        ridges = []
        for bin_key, bin_segments in azimuth_bins.items():
            logger.info(f"Processing azimuth bin {bin_key}° with {len(bin_segments)} segments")
            
            # Cluster by spatial proximity within this azimuth bin
            spatial_clusters = cluster_by_proximity(bin_segments, spatial_join_m)
            logger.info(f"  Formed {len(spatial_clusters)} spatial clusters")
            
            for cluster in spatial_clusters:
                if len(cluster) == 0:
                    continue
                
                # Calculate ridge properties
                total_area = sum(s["area_m2"] for s in cluster)
                
                # Area-weighted azimuth
                weighted_az = sum(s["az"] * s["area_m2"] for s in cluster) / total_area
                
                # Outlier trim within ridge, then area-weighted mean eave
                eaves = [s["eave_m"] for s in cluster]
                lo, hi = tukey_bounds(eaves)
                trimmed_cluster = [s for s in cluster if lo <= s["eave_m"] <= hi]
                
                if not trimmed_cluster:
                    trimmed_cluster = cluster
                
                # Area-weighted eave length
                num = sum(s["eave_m"] * s["area_m2"] for s in trimmed_cluster)
                den = sum(s["area_m2"] for s in trimmed_cluster)
                ridge_eave_m = num / den
                
                ridge_info = {
                    "azimuth": weighted_az,
                    "eave_m": ridge_eave_m,
                    "area_m2": total_area,
                    "segments": cluster,
                    "az_bin": bin_key
                }
                
                ridges.append(ridge_info)
                logger.info(f"  Ridge: az={weighted_az:.1f}°, eave={ridge_eave_m:.2f}m, area={total_area:.2f}m², segments={len(cluster)}")
        
        if len(ridges) > 4:
            warnings.append(f"Found {len(ridges)} ridges - roof may be over-segmented")
        
        # 4. Coverage heuristic
        main_area = max(r["area_m2"] for r in ridges) if ridges else 0
        
        for ridge in ridges:
            if ridge["area_m2"] >= 0.40 * main_area:
                ridge["coverage"] = 1.0
            elif ridge["area_m2"] >= min_plane_area:
                ridge["coverage"] = secondary_coverage
            else:
                ridge["coverage"] = 0.0
        
        # Handle tiny segments if configured
        if tiny_coverage > 0 and tiny_segments:
            logger.info(f"Including {len(tiny_segments)} tiny segments with coverage {tiny_coverage}")
            for tiny in tiny_segments:
                tiny_ridge = {
                    "azimuth": tiny["az"],
                    "eave_m": tiny["eave_m"],
                    "area_m2": tiny["area_m2"],
                    "segments": [tiny],
                    "az_bin": int((tiny["az"] % 180.0) / azimuth_bin_deg) * azimuth_bin_deg,
                    "coverage": tiny_coverage
                }
                ridges.append(tiny_ridge)
        
        # 5. Total gutter computation
        total_gutter_m = 0
        main_ridge_eave_m = 0
        
        for ridge in ridges:
            if ridge["coverage"] > 0:
                ridge_contribution_m = 2 * ridge["eave_m"] * ridge["coverage"]
                total_gutter_m += ridge_contribution_m
                
                # Track main ridge for return value
                if ridge["area_m2"] >= 0.40 * main_area:
                    main_ridge_eave_m = ridge["eave_m"]
                
                logger.info(f"Ridge contribution: {ridge_contribution_m:.2f}m (eave={ridge['eave_m']:.2f}m, coverage={ridge['coverage']})")
        
        # Convert to feet and apply waste factor
        main_ridge_eave_ft = main_ridge_eave_m * 3.28084
        total_gutter_ft_raw = total_gutter_m * 3.28084
        
        # Apply waste factor and round up
        total_gutter_with_waste = total_gutter_ft_raw * (1 + waste_factor)
        total_gutter_ft = math.ceil(total_gutter_with_waste)
        
        logger.info(f"Main ridge eave: {main_ridge_eave_ft:.2f}ft")
        logger.info(f"Total gutter with waste: {total_gutter_ft}ft")
        
        # 6. Area sanity check
        whole_roof_stats = data.get('wholeRoofStats', {})
        ground_area = whole_roof_stats.get('groundAreaMeters2')
        logger.info(f"Ground area: {ground_area}m²")
        
        if ground_area and main_ridge_eave_m > 0:
            # Use depths from main ridge segments
            main_ridge_depths = []
            for ridge in ridges:
                if ridge["area_m2"] >= 0.40 * main_area:
                    main_ridge_depths.extend([s["depth_m"] for s in ridge["segments"]])
            
            if main_ridge_depths:
                area_warnings = validate_with_area_check(
                    main_ridge_eave_m, ground_area, main_ridge_depths
                )
                warnings.extend(area_warnings)
                logger.info(f"Area validation warnings: {area_warnings}")
        
        return {
            "eave_length_ft": round(main_ridge_eave_ft, 2),
            "total_gutter_ft": total_gutter_ft,
            "waste_factor": waste_factor,
            "warnings": warnings
        }
        
    except Exception as e:
        logger.error(f"Error during gutter estimation: {str(e)}", exc_info=True)
        return {
            "eave_length_ft": 0.0,
            "total_gutter_ft": 0,
            "waste_factor": waste_factor,
            "warnings": [f"Error during calculation: {str(e)}"]
        }


def estimate_gutter_feet_detailed(
    data: Dict[str, Any], 
    waste_factor: float = 0.02,
    include_breakdown: bool = False,
    **kwargs
) -> DetailedGutterEstimate:
    """
    Detailed gutter estimation with ridge breakdown
    
    Args:
        data: Building data dictionary
        waste_factor: Waste factor for calculations
        include_breakdown: Whether to include detailed ridge breakdown
        **kwargs: Additional parameters for estimate_gutter_feet
    
    Returns:
        DetailedGutterEstimate with ridge information
    """
    # For now, return the basic estimate
    # TODO: Implement detailed breakdown when needed
    basic_result = estimate_gutter_feet(data, waste_factor, **kwargs)
    
    # Convert to detailed format
    detailed_result = DetailedGutterEstimate(
        eave_length_ft=basic_result["eave_length_ft"],
        total_gutter_ft=basic_result["total_gutter_ft"],
        waste_factor=basic_result["waste_factor"],
        warnings=basic_result["warnings"],
        ridges=[]  # Placeholder for now
    )
    
    return detailed_result


def get_gutter_estimate_from_solar_data(solar_data: Dict[str, Any], waste_factor: float = 0.02) -> GutterEstimate:
    """Get gutter estimate from solar data with proper data extraction"""
    logger.info(f"Processing solar data for gutter estimation")
    logger.info(f"Solar data keys: {list(solar_data.keys())}")
    
    if "error" in solar_data:
        logger.error(f"Solar data contains error: {solar_data['error']}")
        return {
            "eave_length_ft": 0.0,
            "total_gutter_ft": 0,
            "waste_factor": waste_factor,
            "warnings": [f"Solar data error: {solar_data['error']}"]
        }
    
    # Extract the raw API response
    raw_data = solar_data.get("raw_api_response", {})
    logger.info(f"Raw API response keys: {list(raw_data.keys())}")
    
    if not raw_data:
        logger.error("No raw API response found in solar data")
        return {
            "eave_length_ft": 0.0,
            "total_gutter_ft": 0,
            "waste_factor": waste_factor,
            "warnings": ["No raw API response found in solar data"]
        }
    
    # Add the raw data to the input for the estimator
    data_with_raw = {"raw": raw_data}
    
    # Look for roof data in the correct location (under solarPotential)
    solar_potential = raw_data.get("solarPotential", {})
    logger.info(f"Solar potential keys: {list(solar_potential.keys())}")
    
    # Copy over roof segment stats and whole roof stats from solarPotential
    if "roofSegmentStats" in solar_potential:
        data_with_raw["roofSegmentStats"] = solar_potential["roofSegmentStats"]
        logger.info(f"Added {len(solar_potential['roofSegmentStats'])} roof segments to data")
    else:
        logger.warning("No 'roofSegmentStats' found in solarPotential")
    
    if "wholeRoofStats" in solar_potential:
        data_with_raw["wholeRoofStats"] = solar_potential["wholeRoofStats"]
        logger.info(f"Added whole roof stats to data")
    else:
        logger.warning("No 'wholeRoofStats' found in solarPotential")
    
    # Also check if there are any roof-related fields at the top level (fallback)
    if "roofSegmentStats" not in data_with_raw and "roofSegmentStats" in raw_data:
        data_with_raw["roofSegmentStats"] = raw_data["roofSegmentStats"]
        logger.info(f"Added {len(raw_data['roofSegmentStats'])} roof segments from top level")
    
    if "wholeRoofStats" not in data_with_raw and "wholeRoofStats" in raw_data:
        data_with_raw["wholeRoofStats"] = raw_data["wholeRoofStats"]
        logger.info(f"Added whole roof stats from top level")
    
    logger.info(f"Final data structure for estimator: {list(data_with_raw.keys())}")
    
    return estimate_gutter_feet(data_with_raw, waste_factor)


# Self-test block
if __name__ == "__main__":
    import json
    import sys
    
    if len(sys.argv) > 1:
        json_path = sys.argv[1]
        try:
            with open(json_path, 'r') as f:
                test_data = json.load(f)
            
            print(f"Testing gutter estimator with: {json_path}")
            result = estimate_gutter_feet({"raw": test_data})
            
            print(f"\nResults:")
            print(f"  Main ridge eave: {result['eave_length_ft']:.2f} ft")
            print(f"  Total gutter: {result['total_gutter_ft']} ft")
            print(f"  Waste factor: {result['waste_factor']}")
            
            if result['warnings']:
                print(f"  Warnings: {result['warnings']}")
                
        except Exception as e:
            print(f"Error testing: {e}")
    else:
        print("Usage: python gutter_estimator.py <json_file_path>")
        print("Or import and use estimate_gutter_feet() function")
