# 🚌 KMB Transport API Documentation

## Overview

The KMB Transport application provides internal APIs for route data access and processing. These APIs are used by the Streamlit interface and can be accessed programmatically.

## Core Functions

### Data Loading

#### `load_kmb_data()`
Loads KMB route and stop data from the SQLite database.

**Returns:**
- `Tuple[pd.DataFrame, pd.DataFrame]`: Routes and stops dataframes

**Example:**
```python
from src.hk_kmb_transport.pipelines.web_app.nodes import load_kmb_data

routes_df, stops_df = load_kmb_data()
print(f"Loaded {len(routes_df)} routes and {len(stops_df)} stops")
```

### Route Processing

#### `get_route_stops_with_directions(route_id: str)`
Retrieves stops for a specific route with direction information.

**Parameters:**
- `route_id` (str): Route identifier (e.g., "65X", "24", "219X")

**Returns:**
- `pd.DataFrame`: DataFrame with stop information including coordinates and directions

**Example:**
```python
from src.hk_kmb_transport.pipelines.web_app.nodes import get_route_stops_with_directions

stops = get_route_stops_with_directions("65X")
print(f"Route 65X has {len(stops)} stops")
```

#### `get_sorted_routes(routes_df: pd.DataFrame)`
Sorts routes naturally (1, 2, 3, 10, 11, 101...).

**Parameters:**
- `routes_df` (pd.DataFrame): DataFrame with route information

**Returns:**
- `pd.DataFrame`: Naturally sorted routes

**Example:**
```python
from src.hk_kmb_transport.pipelines.web_app.nodes import get_sorted_routes

sorted_routes = get_sorted_routes(routes_df)
print(sorted_routes['route_id'].head(10).tolist())
# Output: ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']
```

### Map Visualization

#### `create_route_map(route_stops, selected_stop_id=None, direction=1)`
Creates an interactive Folium map with route visualization.

**Parameters:**
- `route_stops` (pd.DataFrame): Route stops data
- `selected_stop_id` (str, optional): Stop ID to highlight
- `direction` (int): Route direction (1=outbound, 2=inbound)

**Returns:**
- `folium.Map`: Interactive map object

**Example:**
```python
from src.hk_kmb_transport.pipelines.web_app.nodes import create_route_map

route_stops = get_route_stops_with_directions("65X")
map_obj = create_route_map(route_stops, direction=1)
```

## Database Schema

### Tables

#### `routes`
Contains route information.

**Columns:**
- `route_id` (TEXT): Unique route identifier
- `route_name` (TEXT): Route display name
- `origin_en` (TEXT): Origin stop name in English
- `destination_en` (TEXT): Destination stop name in English
- `service_type` (INTEGER): Service type code
- `company` (TEXT): Operating company

#### `stops`
Contains stop information.

**Columns:**
- `stop_id` (TEXT): Unique stop identifier
- `stop_name_en` (TEXT): Stop name in English
- `lat` (REAL): Latitude coordinate
- `lng` (REAL): Longitude coordinate
- `company` (TEXT): Operating company

#### `route_stops`
Maps routes to stops with sequencing.

**Columns:**
- `route_id` (TEXT): Route identifier
- `stop_id` (TEXT): Stop identifier
- `direction` (INTEGER): Direction (1=outbound, 2=inbound)
- `sequence` (INTEGER): Stop sequence number
- `service_type` (INTEGER): Service type code
- `updated_at` (TIMESTAMP): Last update timestamp

## External APIs

### KMB Open Data API
Base URL: `https://data.etabus.gov.hk/v1/transport/kmb/`

#### Endpoints Used:
- `/route`: Get all routes
- `/stop`: Get all stops
- `/route-stop/{route}/{direction}/{service_type}`: Get route stops

### OpenStreetMap Routing Service (OSRM)
Base URL: `http://router.project-osrm.org/route/v1/driving/`

#### Usage:
- Waypoint routing through all bus stops
- Fallback to direct lines if routing fails
- Maximum 25 waypoints per request

## Error Handling

### Database Errors
- Empty results return empty DataFrames
- Connection errors are logged and cached
- Graceful fallback to cached data

### Routing Errors
- OSM routing failures fall back to direct paths
- Network timeouts handled gracefully
- User sees progress indicators

### Search Errors
- Invalid route IDs return empty results
- Search terms are sanitized
- Case-insensitive matching

## Performance Considerations

### Caching
- Route data cached for 1 hour
- Map objects cached per route
- Database queries optimized with indexes

### Rate Limiting
- OSM API respects rate limits
- Batch processing for multiple routes
- Progress indicators for long operations

## Testing

### Unit Tests
```bash
# Test core functions
pytest tests/test_api.py

# Test with specific route
python -c "
from src.hk_kmb_transport.pipelines.web_app.nodes import get_route_stops_with_directions
result = get_route_stops_with_directions('65X')
assert not result.empty, 'Route 65X should have stops'
print('✅ Route 65X test passed')
"
```

### Integration Tests
```bash
# Test full workflow
python src/hk_kmb_transport/test_production_features.py
```

## Examples

### Get Route Information
```python
# Load all routes
routes_df, stops_df = load_kmb_data()

# Find specific route
route_65x = routes_df[routes_df['route_id'] == '65X']
print(f"Route 65X: {route_65x.iloc[0]['origin']} → {route_65x.iloc[0]['destination']}")

# Get stops for route
stops = get_route_stops_with_directions("65X")
print(f"Number of stops: {len(stops)}")
print(f"Directions available: {stops['direction'].unique()}")
```

### Search Routes
```python
# Search by route number
search_term = "65"
mask = routes_df['route_id'].str.contains(search_term, case=False, na=False)
matching_routes = routes_df[mask]

# Search by destination
search_term = "Tsim Sha Tsui"
mask = routes_df['destination'].str.contains(search_term, case=False, na=False)
matching_routes = routes_df[mask]
```

### Create Custom Map
```python
import folium
from src.hk_kmb_transport.pipelines.web_app.nodes import create_route_map

# Get route data
route_stops = get_route_stops_with_directions("65X")

# Create map
map_obj = create_route_map(route_stops, direction=1)

# Save to file
map_obj.save("route_65x_map.html")
```

## Support

For API support and questions:
- Check the troubleshooting guide in the main README
- Review the source code in `src/hk_kmb_transport/pipelines/web_app/nodes.py`
- Create an issue on GitHub with specific error messages 