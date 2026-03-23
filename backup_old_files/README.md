# Hong Kong KMB Bus Dashboard

A specialized Streamlit-based dashboard for visualizing Hong Kong's KMB (Kowloon Motor Bus) and LWB (Long Win Bus) network with real-time data integration and interactive route exploration.

## 🚌 Overview

This dashboard provides comprehensive insights into Hong Kong's largest bus operator, KMB/LWB, serving Kowloon and New Territories with over 400 routes and 4,000+ buses carrying 2.8 million passengers daily.

## ✨ Features

- **🗺️ Interactive Route Maps**: Explore KMB routes with real-time stop information
- **📍 Real-time ETA**: Live arrival times for selected bus stops
- **🚌 Route Explorer**: Detailed route information with stop sequences
- **📊 Analytics Dashboard**: KMB performance metrics and usage statistics  
- **🎯 Focused Data**: Exclusively KMB/LWB services (Kowloon & New Territories)
- **⚡ Optimized Performance**: Smart caching and efficient data loading

## 🏗️ Architecture

- **Frontend**: Streamlit with Folium for interactive maps
- **Data Source**: Hong Kong Government ETA Bus API
- **Visualization**: Plotly for charts and analytics
- **Caching**: Multi-level caching for optimal performance

## 📋 Prerequisites

- Python 3.8 or higher
- pip (Python package installer)
- Internet connection (for map tiles and API data)

## 🚀 Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd e-Mobility-analysis
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Launch the dashboard**
   ```bash
   python run_app.py
   ```
   
   Or run directly:
   ```bash
   streamlit run hk_transport_optimized.py
   ```

4. **Access the dashboard**
   - Open your browser and go to `http://localhost:8501`
   - Select KMB routes from the sidebar
   - Explore interactive maps and real-time data

## 📱 Usage Guide

### Dashboard Navigation

1. **Route Selection**: Choose from 400+ KMB routes using the sidebar dropdown
2. **Stop Selection**: Pick specific stops along your selected route
3. **Real-time ETA**: View live arrival times for the selected stop
4. **Map Interaction**: Explore route paths with color-coded stop markers

### Features Breakdown

#### 🗺️ Interactive Map
- **Route Visualization**: Purple lines showing complete route paths
- **Stop Markers**: Color-coded bus stops (blue=regular, green=depot, red=selected)
- **Real-time Info**: Click stops for detailed information and ETA
- **Auto-centering**: Map automatically focuses on selected routes

#### 📊 Statistics Dashboard  
- **Route Analytics**: Distribution of service types and popular routes
- **Performance Metrics**: On-time performance, journey times, satisfaction scores
- **Geographic Coverage**: Visual representation of KMB's service area

#### ⏰ Real-time Information
- **Live ETA**: Next 5 arrivals with color-coded timing (🟢 arrived, 🟡 soon, 🔵 scheduled)
- **Route Details**: Origin, destination, and service type information
- **Service Status**: Current operational status of KMB services

## 🔧 Configuration

### API Integration
The dashboard connects to:
- **KMB ETA API**: `https://data.etabus.gov.hk/v1/transport/kmb/`
- **Endpoints**: Routes, stops, route-stops, and real-time ETA data

### Customization Options
Modify these files for customization:
- `config.py`: API endpoints, map settings, UI configuration
- `api_connectors.py`: Data fetching and processing logic
- CSS styling within the Streamlit apps

## 📊 Data Coverage

### KMB/LWB Network
- **Routes**: 400+ bus routes across Kowloon and New Territories
- **Stops**: 6,000+ bus stops with GPS coordinates
- **Service Types**: Regular, express, and special services
- **Real-time Data**: Live ETA and service status updates

### Geographic Coverage
- **Primary Areas**: Kowloon, New Territories
- **Key Terminals**: Tsim Sha Tsui, Mong Kok, Kwun Tong, Tsuen Wan
- **Route Types**: Local, cross-district, and express services

## 🛠️ Technical Details

### File Structure
```
├── api_connectors.py          # KMB API integration
├── hk_transport_enhanced.py   # Main dashboard application  
├── hk_transport_optimized.py  # Optimized version with caching
├── config.py                  # Configuration settings
├── run_app.py                 # Application launcher
└── requirements.txt           # Python dependencies
```

### Dependencies
- `streamlit`: Web application framework
- `folium`: Interactive maps
- `pandas`: Data manipulation
- `plotly`: Interactive charts
- `requests`: API communication

## 🔍 Troubleshooting

### Common Issues

**"No route data available"**
- Check internet connection
- API may be temporarily unavailable (app uses fallback data)

**Map not displaying**
- Ensure internet connection for map tiles
- Try refreshing the page

**Slow loading**
- Large routes may take time to load
- Use the caching feature (data refreshes every hour)

### Performance Tips
- Use the optimized version (`hk_transport_optimized.py`) for better performance
- Clear cache if data seems stale (refresh button in sidebar)
- Select specific routes rather than viewing all data at once

## 🚌 About KMB/LWB

**Kowloon Motor Bus (KMB)** is Hong Kong's largest bus operator:
- **Founded**: 1933
- **Service Area**: Kowloon and New Territories  
- **Fleet Size**: 4,000+ buses
- **Daily Passengers**: ~2.8 million
- **Routes**: 400+ regular and express services

**Long Win Bus (LWB)** operates airport and North Lantau services under the KMB group.

## 📈 Future Enhancements

- [ ] Route planning between stops
- [ ] Historical ETA accuracy analysis  
- [ ] Fare calculation integration
- [ ] Mobile-responsive improvements
- [ ] Multilingual support (English/Traditional Chinese)
- [ ] Bus capacity and crowding predictions

## 🤝 Contributing

1. Fork this repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Hong Kong Government** for providing open transportation data
- **KMB** for their comprehensive API and service information
- **OpenStreetMap** contributors for map data
- **Streamlit** community for the excellent framework

## 📞 Support

For questions, issues, or suggestions:
- 🐛 Report bugs via GitHub Issues
- 💡 Request features via GitHub Discussions  
- 📖 Check the troubleshooting section above

---

**Disclaimer**: This is an unofficial dashboard created for educational and informational purposes. Real-time data is subject to API availability and may not always reflect current conditions.
