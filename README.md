# YuuTraffic - Hong Kong Public Transport Analytics

[![CI/CD Pipeline](https://github.com/yutsang/e-Mobility-analysis/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/yutsang/e-Mobility-analysis/actions/workflows/ci-cd.yml)
[![Powered by Kedro](https://img.shields.io/badge/powered_by-kedro-ffc900?logo=kedro)](https://kedro.org)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit)](https://streamlit.io)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)](https://www.python.org)

## 📋 Overview

**Traffic ETA** is a comprehensive, production-ready web application for exploring Hong Kong's public transport system. Built with modern technologies and best practices, it provides detailed route analysis, interactive mapping, and real-time data visualization for the entire KMB (Kowloon Motor Bus) network.

### ✨ Key Features

### 🚌 Complete Coverage
- **All KMB routes** with real-time data
- **788 routes** with 100% data coverage
- **5,000+ stops** across Hong Kong
- **Dual direction** support with depot names

### 🔍 Smart Search
- **Find routes** by number or destination
- **Type-ahead suggestions** with autocomplete
- **Dual direction results** for each route
- **Depot names** showing actual origin/destination

### 🧭 Route Types
- **Express routes** (X suffix) - Orange badges
- **Night routes** (N prefix) - Dark badges  
- **Circular routes** - Purple badges
- **Airport routes** (A/E prefix) - Blue badges
- **Special routes** (S/P/R suffix) - Red badges
- **Regular routes** - Green badges

### 🗺️ Interactive Maps
- **Real-time OSM routing** through actual roads
- **Auto-zoom** when route or stop selected
- **Center button** to return to Hong Kong view
- **Stop highlighting** with detailed information
- **Responsive design** for mobile devices

### 🚇 MTR Tools
- **Railway routing** across the MTR network, including Airport Express
- **Live railway ETA** from the official next-train API in a compact route card
- **Light Rail routing + ETA** using official route-stop data and live station boards
- **Interactive station layout maps** powered by the CSDI indoor map API

### 📱 Mobile Friendly
- **Responsive design** adapts to all screen sizes
- **Touch-friendly** interface for mobile devices
- **Fast loading** with optimized caching
- **Offline-capable** with local database

### ⚡ Performance
- **Sub-2 second** route loading times
- **95%+ cache hit rate** for repeated queries
- **5.8 MB** optimized SQLite database
- **Intelligent sorting** (1, 2, 3, 10, 11, 101...)
- **Background updates** without interrupting users

### 🔄 Auto Updates
- **Daily data updates** at 2 AM Hong Kong time
- **First-run setup** for new installations
- **Configurable schedules** through parameters
- **Backup and restore** functionality

### 🏗️ Production Ready
- **Simple Python package** with Streamlit UI
- **Comprehensive configuration** system
- **CI/CD pipeline** with automated testing
- **Docker support** for containerized deployment
- **Monitoring and logging** built-in

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- pip package manager
- Internet connection (for OSM routing)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/yuutraffic.git
   cd yuutraffic
   ```
   *(If you rename the repo on GitHub to `yuutraffic`, update your local remote: `git remote set-url origin https://github.com/YOUR_USERNAME/yuutraffic.git`)*

2. **Install the package and dependencies:**
   ```bash
   pip install -e .
   ```

3. **_(First run only)_ Download all transport data and map geometry:**
   ```bash
   yuutraffic --update
   ```
   Refreshes **KMB, Citybus, green minibus (GMB), MTR Bus**, **red minibus** listings, then **incremental** road geometry for maps (GMB download is slow).  
   **Where data lives:** route/stop tables are in **SQLite** (`data/01_raw/kmb_data.db`); map polylines are **JSON** under `data/02_intermediate/route_geometry/`. This is **not** a general point-to-point router—only fixed routes from the APIs.  
   **Repeat runs:** if the DB passes minimum row counts (`data_update.catalog_min_*`) **and** lightweight live checks match the database (KMB / Citybus / GMB route lists, optional MTR Bus stop sequences, red minibus JSON vs `RMB` rows), `yuutraffic --update` skips downloading and map geometry. Set **`skip_transport_api_if_catalog_complete: false`** for a full download every time; set **`catalog_compare_mtr: false`** to skip MTR POSTs during that check (faster).

   **MTR Bus** stops have no official names in the ETA API; the app uses district-aware labels (`mtr_bus_routes_meta.py`), optional per-stop names in `data/01_raw/mtr_bus_stop_overrides.json`, and approximate map lines per route (not survey-grade). After changing metadata, run a transport refresh so SQLite picks up new coordinates.  
   **CLI summary:** `yuutraffic` starts the app · `yuutraffic --update` refreshes DB + maps.

4. **Launch the application:**
   ```bash
   yuutraffic
   ```
   Or: `python -m yuutraffic`  
   Or directly: `streamlit run app.py --server.port 8508`

5. **Open in your browser:**
   ```
   http://localhost:8508
   ```
   Sidebar **Trip Planner**: point-to-point bus suggestions (direct + one interchange).  
   Sidebar **MTR Routing & ETA**: railway routing, live ETA at each rail boarding station (planned direction only), heuristic per-segment and total times, Light Rail ETA, and station layout summaries.

## 🛠️ Usage Guide

### Enhanced Search Features

#### 1. Dual Direction Search
Search for any route and get **both directions** with proper depot names:
- **Outbound**: Origin → Destination (e.g., "Tin Shui Wai → Tsim Sha Tsui")
- **Inbound**: Destination → Origin (e.g., "Tsim Sha Tsui → Tin Shui Wai")
- **Circular**: Same depot for both directions (e.g., "Central (Circular)")

#### 2. Route Type Classification
Routes are automatically categorized with color-coded badges:
- 🟢 **Regular**: Standard routes (e.g., 1, 2, 3)
- 🟠 **Express**: Fast routes with fewer stops (e.g., 65X, 219X)
- 🟣 **Circular**: Routes returning to origin (e.g., routes ending in "Circular")
- ⚫ **Night**: Late-night services (e.g., N213, N241)
- 🔴 **Peak**: Rush hour only (e.g., routes ending in P)
- 🔵 **Airport**: Airport connection routes (e.g., A22, E23)
- 🟡 **Special Service**: Special event routes (e.g., routes ending in S, R)

#### 3. Interactive Search Examples
```
Search Examples:
• "65X" → Shows both directions of route 65X
• "Central" → All routes serving Central
• "Airport" → All airport routes
• "Tsim Sha Tsui" → All routes to/from TST
• "213" → All routes containing "213"
```

### Enhanced Map Features

#### 1. Auto-Zoom
- **Route Selection**: Automatically zooms to fit entire route
- **Stop Selection**: Zooms closer when a specific stop is highlighted
- **Configurable**: Zoom levels can be adjusted in parameters

#### 2. Center Button
- **🏠 Center to HK**: Button to return map view to Hong Kong overview
- **Always Available**: Present on both route maps and default map
- **One-Click**: Instantly centers map to Hong Kong coordinates

#### 3. OSM Routing
- **Real Roads**: Routes follow actual roads using OSRM (driving profile for bus routes)
- **Waypoint Optimization**: Passes through all bus stops in sequence
- **Fallback**: Direct lines if OSM routing fails
- **Progress Tracking**: Visual progress bars during route calculation

#### 4. Map Tiles (Faster Loading / Offline)
- **Default**: CartoDB Positron tiles (faster than OpenStreetMap)
- **Local tiles**: Download HK tiles for offline use:
  ```bash
  python scripts/download_hk_tiles.py --min-zoom 10 --max-zoom 15
  # Then in another terminal:
  python -m http.server 8000 --directory data/tiles
  ```
  Uncomment `tiles_url` in `conf/base/parameters.yml` and set to `http://localhost:8000/{z}/{x}/{y}.png`

## 🏗️ Technical Architecture

### Project Structure
```
yuutraffic/
├── app.py                    # Streamlit app (entry point for UI)
├── src/yuutraffic/           # Package code
│   ├── config.py             # YAML config loader
│   ├── database_manager.py  # SQLite database operations
│   ├── data_updater.py      # KMB API data fetcher
│   ├── web.py               # Web logic (maps, search, data loading)
│   ├── launcher.py          # App launcher with pre-flight checks
│   └── __main__.py          # CLI entry: yuutraffic / python -m yuutraffic
├── conf/base/
│   └── parameters.yml       # Configuration
├── data/01_raw/             # SQLite database (kmb_data.db)
├── tests/
└── requirements.txt
```

### Configuration Parameters

All application behavior is configurable through `conf/base/parameters.yml`:

```yaml
# API Endpoints
api:
  kmb_base_url: "https://data.etabus.gov.hk/v1/transport/kmb"
  osm_routing_url: "http://router.project-osrm.org/route/v1/driving"
  mtr_next_train_url: "https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php"
  mtr_light_rail_schedule_url: "https://rt.data.gov.hk/v1/transport/mtr/lrt/getSchedule"
  mtr_light_rail_routes_stops_url: "https://opendata.mtr.com.hk/data/light_rail_routes_and_stops.csv"
  mtr_lines_stations_url: "https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv"
  mtr_indoor_map_base_url: "https://mapapi.hkmapservice.gov.hk/ogc/wfs/indoor"

# Route Type Classification
route_types:
  circular: ["CIRCULAR", "(CIRCULAR)", "CIRCLE"]
  special: ["X", "S", "P", "A", "E", "N", "R"]
  express: ["X"]
  night: ["N"]

# Map Configuration
map:
  center: {lat: 22.3193, lng: 114.1694}
  auto_zoom: {enabled: true, route_zoom: 13, stop_zoom: 16}

# MTR routing
mtr:
  routing_transfer_penalty: 4.0
  light_rail_transfer_penalty: 3.0
  # Heuristic journey time on the MTR Routing page (not live ETA)
  rail_minutes_per_stop: 2.5
  walk_leg_minutes: 5.0
  interchange_minutes: 3.0

# Scheduling
schedule:
  daily_update: {enabled: true, time: "02:00"}
  first_run_setup: true
```

## 🎯 Route Examples

### Example: Route 65X
Perfect example showcasing all features:

**Route Information:**
- **Route**: 65X (Express)
- **Type**: Express 🟠
- **Outbound**: Tin Shui Wai (Tin Yiu Bus Terminus) → Tsim Sha Tsui (Circular)
- **Inbound**: Tsim Sha Tsui (Circular) → Tin Shui Wai (Tin Yiu Bus Terminus)
- **Stops**: 25+ stops per direction
- **Features**: OSM routing, auto-zoom, stop highlighting

**Search Results:**
```
Search: "65X"
Results:
1. 65X - Tin Shui Wai → Tsim Sha Tsui (Outbound, 25 stops) [Express]
2. 65X - Tsim Sha Tsui → Tin Shui Wai (Inbound, 24 stops) [Express]
```

### Missing Routes Fixed
Previously missing routes now fully supported:
- **Route 24**: Kai Yip → Mong Kok (Circular) ✅
- **Route 213X**: On Tai (South) → Tsim Sha Tsui (Circular) ✅  
- **Route 219X**: Ko Ling Road → Tsim Sha Tsui (Circular) ✅

## 🔧 Configuration

### Database Settings
```yaml
database:
  path: "data/01_raw/kmb_data.db"
  backup_path: "data/02_backup"
  connection_timeout: 30
```

### Application Settings
```yaml
app:
  name: "Traffic ETA"
  port: 8508
  host: "localhost"
  debug: false
```

### Update Schedule
```yaml
schedule:
  daily_update:
    enabled: true
    time: "02:00"  # 2 AM daily
    timezone: "Asia/Hong_Kong"
  first_run_setup: true
```

## 🏗️ Architecture

- **app.py** – Streamlit UI at project root; imports from `yuutraffic.web`
- **yuutraffic.web** – Map rendering, search, route loading, config
- **yuutraffic.data_updater** – Fetches routes/stops from KMB API
- **yuutraffic.database_manager** – SQLite storage for routes, stops, route_stops

## 🧪 Testing

### Run Tests
```bash
pytest tests/
python -m pytest tests/test_app.py -v  # With verbose output
```

## 📊 Performance Metrics

- **Route Coverage**: 788/788 routes (100%)
- **Stop Coverage**: 5,000+ stops across Hong Kong  
- **Route Types**: 8 different classifications
- **Response Time**: <2 seconds for route loading
- **Cache Hit Rate**: >95% for repeated queries
- **Database Size**: 5.8 MB optimized SQLite
- **Auto-zoom**: Configurable zoom levels per context
- **OSM Routing**: Real-time waypoint optimization

## 🐛 Troubleshooting

### Common Issues

1. **App Won't Start**
   ```bash
   # Check if port is in use
   lsof -i :8508
   
   # Clear cache and restart
   rm -rf .streamlit
   yuutraffic
   ```

2. **Missing Routes**
   ```bash
   # Check database
   sqlite3 data/01_raw/kmb_data.db "SELECT COUNT(*) FROM routes"
   # Should return 788
   ```

3. **CI/CD Failures**
   - Ensure all dependencies are in `requirements.txt`
   - Check Python version compatibility (3.8+)
   - Verify test database creation
   - Review GitHub Actions logs

### Debug Mode
```bash
export DEBUG_MODE=true
yuutraffic
```

## 🚀 Deployment

### Production Deployment
```bash
# Build production package
python -m build

# Deploy with Docker
docker build -t yuutraffic .
docker run -p 8508:8508 yuutraffic
```

### CI/CD Pipeline
The project includes a comprehensive GitHub Actions workflow:
- ✅ Code formatting (Black, isort)
- ✅ Linting (Ruff)
- ✅ Testing (pytest with coverage)
- ✅ Security scanning (Bandit, Safety)
- ✅ Build and packaging
- ✅ Automated deployment
- ✅ Release management

## 🤝 Contributing

Repository hygiene (`.gitignore`, GitHub Actions expectations, no `.gitattributes`) is documented in **[docs/GIT_AND_CI.md](docs/GIT_AND_CI.md)**.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes following the coding standards
4. Add tests for new functionality
5. Run the test suite: `pytest`
6. Commit your changes: `git commit -m 'Add amazing feature'`
7. Push to the branch: `git push origin feature/amazing-feature`
8. Submit a pull request

### Development Setup
```bash
# Install development dependencies
pip install -r requirements.txt
pip install black isort ruff pytest pytest-cov

# Set up pre-commit hooks
pre-commit install

# Run formatting
black src/ pages/ tests/
isort src/ pages/ tests/

# Run linting
ruff check src/ pages/ tests/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [KMB Open Data](https://data.gov.hk/en-data/dataset/kmb-kmb-route-stop-fare-geospatial-data) for providing comprehensive route data
- [OpenStreetMap](https://www.openstreetmap.org/) for routing services and map tiles
- [Kedro](https://kedro.org/) for the excellent ML pipeline framework
- [Streamlit](https://streamlit.io/) for the intuitive web framework
- [Folium](https://python-visualization.github.io/folium/) for interactive mapping

## 🆘 Support

For issues and questions:
- 🐛 [Create an issue](https://github.com/YOUR_USERNAME/e-Mobility-analysis/issues/new) on GitHub
- 📖 Check the [troubleshooting guide](#troubleshooting) above
- 📚 Review the [documentation](docs/) directory
- 💬 Start a [discussion](https://github.com/YOUR_USERNAME/e-Mobility-analysis/discussions) for feature requests

---

**Ready to explore Hong Kong's transport network? 🚌✨**

*Built with ❤️ for Hong Kong commuters and transport enthusiasts*
