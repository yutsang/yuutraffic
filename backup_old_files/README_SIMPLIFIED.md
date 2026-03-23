# Hong Kong KMB Route Map - Simplified Version

A streamlined Streamlit application for viewing Hong Kong KMB bus routes with interactive maps.

## 🚌 Features

- **Route Selection**: Choose from KMB bus routes via dropdown menu
- **Interactive Map**: View route paths with colored markers for stops and depots
- **Stop Information**: Select specific stops to highlight on the map
- **Clean Interface**: No statistics, no ETA requirements - just route selection and map display

## 🚀 Quick Start

### 1. Run the Simplified Application

```bash
python run_simplified.py
```

This will:
- Clear all cache automatically
- Launch the app on port 8508
- Open in your browser at `http://localhost:8508`

### 2. Usage

1. **Select a Route**: Use the sidebar dropdown to choose a KMB route
2. **View the Map**: Route path and stops appear automatically on the map
3. **Select a Stop (Optional)**: Choose a specific stop to highlight it in red
4. **Refresh**: Use the "Clear Cache & Refresh" button if needed

## 🎯 What's Simplified

### ✅ What's Included
- Route selection dropdown
- Interactive map with route visualization
- Stop markers (blue=regular, green=depot, red=selected)
- Basic route information (origin, destination, total stops)
- Stop list table

### ❌ What's Removed
- Statistics dashboard
- KMB service information
- Routes by service type sections
- ETA API integration
- Multiple tabs interface
- Non-KMB transport modes

## 🗺️ Map Features

- **Blue Line**: Route path connecting all stops
- **Blue Markers**: Regular bus stops
- **Green Markers**: Depot stops
- **Red Markers**: Selected/highlighted stops
- **Auto-fit**: Map automatically centers on the selected route

## 🔧 Technical Details

- **Port**: 8508 (for easy debugging - just refresh browser)
- **Cache**: Automatically cleared on startup
- **API**: Only uses KMB/LWB endpoints
- **Database**: Uses local SQLite database for route/stop data

## 📱 Access

- **Local**: http://localhost:8508
- **Refresh**: Just refresh the browser to debug
- **Stop**: Press Ctrl+C in terminal

## 🛠️ Files

- `hk_transport_simplified.py` - Main simplified Streamlit app
- `run_simplified.py` - Launcher with cache clearing
- `api_connectors.py` - KMB API integration (simplified)
- `database_manager.py` - Local database management

## 🔄 Cache Management

The launcher automatically clears:
- Streamlit cache
- Python cache files
- Temporary JSON files
- Database cache

## 🚌 About

This simplified version focuses solely on KMB route visualization without the complexity of statistics, ETA data, or multiple transport modes. Perfect for quick route exploration and debugging. 