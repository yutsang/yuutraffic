# 🚌 Traffic ETA - Hong Kong Public Transport Analytics

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
- **Kedro-based architecture** with proper pipelines
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
   git clone https://github.com/YOUR_USERNAME/e-Mobility-analysis.git
   cd e-Mobility-analysis
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Launch the application:**
   ```bash
   python src/traffic_eta/run_traffic_eta.py
   ```

4. **Open in your browser:**
   ```
   http://localhost:8508
   ```

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
- **Real Roads**: Routes follow actual roads using OpenStreetMap
- **Waypoint Optimization**: Passes through all bus stops in sequence
- **Fallback**: Direct lines if OSM routing fails
- **Progress Tracking**: Visual progress bars during route calculation

## 🏗️ Technical Architecture

### Project Structure
```
traffic-eta/
├── src/traffic_eta/           # Main application code
│   ├── pipelines/
│   │   ├── data_ingestion/    # API connections and data fetching
│   │   ├── data_processing/   # Route optimization and processing
│   │   └── web_app/          # Streamlit application logic
│   ├── traffic_eta_app.py    # Main application entry point
│   ├── run_traffic_eta.py    # Production launcher
│   ├── data_updater.py       # Data update utilities
│   └── database_manager.py   # Database operations
├── conf/                     # Configuration files
│   ├── base/
│   │   └── parameters.yml    # All configurable parameters
│   └── local/               # Local overrides
├── data/
│   ├── 01_raw/              # Raw database files
│   └── 02_backup/           # Database backups
├── docs/                    # Documentation
├── tests/                   # Test suite
├── .github/workflows/       # CI/CD pipeline
└── requirements.txt         # Dependencies
```

### Configuration Parameters

All application behavior is configurable through `conf/base/parameters.yml`:

```yaml
# API Endpoints
api:
  kmb_base_url: "https://data.etabus.gov.hk/v1/transport/kmb"
  osm_routing_url: "http://router.project-osrm.org/route/v1/driving"

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

## 🏗️ Pipeline Organization

The application follows Kedro's pipeline architecture with clear separation of concerns:

### Data Ingestion Pipeline
```
src/traffic_eta/pipelines/data_ingestion/
├── nodes.py              # ✅ KMB API data fetching
├── api_nodes.py          # 🔄 API connectors (planned migration)
├── update_nodes.py       # 🔄 Data update utilities (planned migration)
└── pipeline.py           # ✅ Pipeline definition
```

### Data Processing Pipeline
```
src/traffic_eta/pipelines/data_processing/
├── nodes.py              # ✅ Route classification and processing
├── database_nodes.py     # 🔄 Database management (planned migration)
├── transform_nodes.py    # ✅ Data transformation utilities
└── pipeline.py           # ✅ Pipeline definition
```

### Web App Pipeline
```
src/traffic_eta/pipelines/web_app/
├── nodes.py              # ✅ Core application logic
├── map_nodes.py          # ✅ Interactive map creation
├── search_nodes.py       # ✅ Search and filtering
└── pipeline.py           # ✅ Pipeline definition
```

### Pipeline Benefits
- **🎯 Separation of Concerns**: Clear boundaries between data ingestion, processing, and visualization
- **🔄 Reusability**: Pipeline nodes can be reused across different applications
- **📊 Kedro Integration**: Built-in data catalog management, pipeline visualization with `kedro viz`
- **🧪 Testability**: Easy to test individual components and pipeline stages

## 🧪 Testing

### Run Tests
```bash
# Run all tests
pytest

# Run specific test suite
pytest tests/test_web_app.py

# Run with coverage
pytest --cov=src/traffic_eta --cov-report=html
```

### Test Database
The application creates a test database automatically for CI/CD:
```bash
# Create test database
python -c "
from src.traffic_eta.database_manager import KMBDatabaseManager
db = KMBDatabaseManager('test_data.db')
db.create_tables()
"
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
   python src/traffic_eta/run_traffic_eta.py
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
# Enable debug logging
export DEBUG=true
python src/traffic_eta/run_traffic_eta.py
```

## 🚀 Deployment

### Production Deployment
```bash
# Build production package
python -m build

# Deploy with Docker
docker build -t traffic-eta .
docker run -p 8508:8508 traffic-eta
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
black src/
isort src/

# Run linting
ruff check src/
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
