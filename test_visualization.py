from backend.services.solar import estimator

def test_visualization():
    """Test the visualization functionality with a sample address"""
    
    # Use the address from the attached JSON file
    address = "766 E Creekwood Ln, Murray, UT 84107, USA"
    # address = "190 A Brynat lane, new bedford, MA, USA"
    print(f"Testing visualization for address: {address}")
    print("=" * 60)
    
    # Run the estimator with visualization enabled
    result = estimator(address, save_visualizations=True)
    
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    
    # Print the results
    print("\nANALYSIS RESULTS:")
    print("-" * 30)
    
    gutter_estimate = result.get("gutter_estimate", {})
    
    if "summary" in gutter_estimate:
        summary = gutter_estimate["summary"]
        print(f"Total Roof Area: {summary['total_roof_area_m2']} m²")
        print(f"Total Gutter Length: {summary['total_gutter_length_m']} m")
        print(f"Estimated Cost: ${summary['estimated_cost_usd']}")
        print(f"Cost per Meter: ${summary['cost_per_meter_usd']}")
    
    if "technical_details" in gutter_estimate:
        tech = gutter_estimate["technical_details"]
        print(f"\nTECHNICAL DETAILS:")
        print(f"   Resolution: {tech['resolution_meters_per_pixel']} m/pixel")
        print(f"   Contours Analyzed: {tech['num_contours_analyzed']}")
        print(f"   Mask Shape: {tech['mask_shape']}")
    
    if "visualizations" in gutter_estimate:
        viz = gutter_estimate["visualizations"]
        print(f"\nVISUALIZATIONS SAVED:")
        if viz.get("rgb_image"):
            print(f"RGB Image: {viz['rgb_image']}")
        if viz.get("mask_processing"):
            print(f"Mask Processing: {viz['mask_processing']}")
    
    if "contour_details" in gutter_estimate:
        contours = gutter_estimate["contour_details"]
        print(f"\nCONTOUR DETAILS ({len(contours)} contours):")
        for i, contour in enumerate(contours[:5]):  # Show first 5
            print(f"   Contour {contour['contour_index']}: "
                  f"{contour['area_meters_sq']:.1f} m², "
                  f"{contour['perimeter_meters']:.1f} m perimeter")
        if len(contours) > 5:
            print(f"   ... and {len(contours) - 5} more contours")

if __name__ == "__main__":
    test_visualization() 