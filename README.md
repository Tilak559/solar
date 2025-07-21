# Solar Project

A FastAPI-based web application that leverages Google's Solar API to provide solar potential analysis and building measurements for residential and commercial properties.

## 🌟 Overview

This project provides a RESTful API service that analyzes solar potential for any given address. It integrates with Google's Solar API to extract detailed information about building rooftops, estimate gutter lengths, and provide comprehensive solar analysis data.

## 🚀 Features

- **Address-based Solar Analysis**: Input any address to get detailed solar potential analysis
- **Building Measurements**: Automatic extraction of roof segments, areas, and perimeters
- **Gutter Length Estimation**: Advanced contour analysis to estimate gutter lengths from satellite imagery
- **Google Solar API Integration**: Leverages Google's high-quality solar data and building insights
- **FastAPI Backend**: Modern, fast, and auto-documented REST API
- **Geocoding Support**: Automatic address to coordinates conversion


## 📋 Prerequisites

- Python 3.8+
- Google Cloud Platform account
- Google Solar API enabled
- Service account with appropriate permissions

## 🔧 Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Solar
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   Create a `.env` file with:
   ```env
   GOOGLE_API_KEY=your_google_api_key
   GOOGLE_CREDENTIALS_PATH=path/to/service_account.json
   GOOGLE_SCOPES=https://www.googleapis.com/auth/solar
   PROJECT_ID=your_google_cloud_project_id
   ```

5. **Set up Google Service Account**
   - Create a service account in Google Cloud Console
   - Download the JSON key file
   - Enable the Solar API for your project
   - Grant appropriate permissions to the service account

## 🚀 Usage

### Starting the Server

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

### API Endpoints

#### GET `/measurements`
Analyze solar potential for a given address.

**Parameters:**
- `address` (string): The address to analyze

**Example Request:**
```bash
curl "http://localhost:8000/measurements?address=123%20Main%20St,%20New%20York,%20NY"
```

**Response:**
```json
{
  "solar_data": {
    "buildingInsights": {...},
    "roofSegmentStats": [...]
  },
  "gutter_estimate": {
    "total_length_m": 45.2,
    "total_area_m2": 120.5,
    "contour_details": [...]
  },
  "method": "buildingInsights"
}
```

## 🔍 API Documentation

Once the server is running, you can access:
- **Interactive API docs**: `http://localhost:8000/docs`
- **ReDoc documentation**: `http://localhost:8000/redoc`

## 🧪 Core Functionality

### Solar Analysis Service
The main service (`backend/services/solar.py`) provides:

1. **Geocoding**: Converts addresses to coordinates using Google Geocoding API
2. **Building Insights**: Retrieves detailed building data using Google Solar API
3. **Gutter Estimation**: Analyzes satellite imagery to estimate gutter lengths
4. **Contour Analysis**: Uses OpenCV to detect building boundaries and calculate measurements

### Key Functions

- `estimator(address)`: Main function that orchestrates the entire analysis process
- `get_access_token()`: Handles Google OAuth authentication
- `estimate_gutter_length()`: Performs advanced image analysis for building measurements
- `extract_building_measurements()`: Extracts measurements from building insights data

## 🔐 Authentication

The application uses Google Service Account authentication to access the Solar API. Make sure to:

1. Create a service account in Google Cloud Console
2. Download the JSON key file
3. Set the `GOOGLE_CREDENTIALS_PATH` environment variable
4. Grant the service account appropriate permissions

## 📊 Data Processing

The application processes various types of data:

- **Satellite Imagery**: High-resolution satellite data for building analysis
- **Building Contours**: Extracted building boundaries for measurement calculations
- **Roof Segments**: Detailed roof analysis for solar potential assessment
- **Geospatial Data**: Coordinate transformations and spatial calculations
