from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import sys

# Add the backend directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.solar import estimator

app = Flask(__name__)
CORS(app)

@app.route('/api/solar/estimate', methods=['POST'])
def solar_estimate():
    """Estimate solar roof gutter length with optional visualization"""
    try:
        data = request.get_json()
        address = data.get('address')
        save_visualizations = data.get('save_visualizations', False)
        
        if not address:
            return jsonify({"error": "Address is required"}), 400
        
        # Run the estimator
        result = estimator(address, save_visualizations=save_visualizations)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/solar/visualization/<image_type>')
def get_visualization(image_type):
    """Serve visualization images"""
    try:
        if image_type == 'rgb':
            file_path = "visualizations/rgb_image.png"
        elif image_type == 'mask':
            file_path = "visualizations/mask_processing.png"
        else:
            return jsonify({"error": "Invalid image type"}), 400
        
        if not os.path.exists(file_path):
            return jsonify({"error": "Visualization not found. Run analysis with save_visualizations=True first"}), 404
        
        return send_file(file_path, mimetype='image/png')
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/solar/health')
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "solar-analysis"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000) 