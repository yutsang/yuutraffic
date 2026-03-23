# Hong Kong KMB Bus Dashboard

A comprehensive Streamlit-based dashboard for visualizing Hong Kong's KMB (Kowloon Motor Bus) and LWB (Long Win Bus) network with real-time data integration and interactive route exploration.

## 🚌 Features

- **Interactive Route Maps**: OpenStreetMap-based visualization with KMB route data
- **Real-time ETA Data**: Integration with Hong Kong Government bus API
- **Route Explorer**: Detailed KMB route information with stop sequences
- **Service Status**: Real-time service updates and operational information
- **Analytics Dashboard**: KMB performance metrics and usage statistics
- **Responsive Design**: Modern UI optimized for KMB data visualization

## 📋 Prerequisites

- Python 3.8 or higher
- pip (Python package installer)

## 🛠️ Installation

1. **Clone or download this project**
   ```bash
   git clone <repository-url>
   cd e-Mobility-analysis
   ```

2. **Install required dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**
   ```bash
   python run_app.py
   ```
   
   Or directly:
   ```bash
   streamlit run hk_transport_optimized.py
   ```

## 🚀 Usage

### Basic Usage
1. Open your web browser and navigate to `http://localhost:8501`
2. Use the sidebar to select KMB routes
3. Explore the interactive map and real-time data tabs

### Features Overview

#### 🗺️ Interactive Map Tab
- View KMB routes and bus stops on an interactive map
- Click on markers for detailed stop information and real-time ETA
- Select specific routes to see complete route paths
- Color-coded markers: blue (regular stops), green (depots), red (selected)

#### 📊 Statistics Tab
- View key KMB network metrics and statistics
- Interactive charts showing route distribution by service type
- Geographic distribution of KMB stops across Kowloon & New Territories
- Performance indicators and operational metrics

#### 🚌 Real-time Info Tab
- Live ETA information for selected bus stops
- KMB service status updates
- Route details including origin, destination, and service type
- Next 5 arrivals with color-coded timing indicators

#### 📈 Analytics Tab
- KMB daily passenger volume analysis by hour
- Most popular KMB routes with popularity scores
- Performance metrics: on-time performance, journey times, satisfaction
- Peak hour analysis and usage patterns

## 🔧 Configuration

### API Endpoints
The application integrates with the Hong Kong Government data source:

- **KMB ETA API**: `https://data.etabus.gov.hk/v1/transport/kmb/`
  - Routes endpoint for route information
  - Stops endpoint for bus stop locations
  - Route-stops endpoint for route-specific stop sequences
  - Stop-ETA endpoint for real-time arrival data

### Customization
You can modify the following in the code:
- Map center coordinates (`HK_CENTER`) in config.py
- Hong Kong boundary coordinates (`HK_BOUNDARY`)
- KMB API endpoints and data sources
- UI styling and colors
- Chart configurations and analytics

## 📊 Data Sources

### KMB/LWB Services
- **Route Information**: 400+ bus routes across Kowloon and New Territories
- **Stop Locations**: 6,000+ bus stops with GPS coordinates
- **Real-time ETA**: Live arrival predictions for all active routes
- **Service Types**: Regular, express, and special services

### Coverage Areas
- **Primary Service Area**: Kowloon and New Territories
- **Key Terminals**: Tsim Sha Tsui, Mong Kok, Kwun Tong, Tsuen Wan
- **Route Categories**: Local, cross-district, express, and airport services

## 🎨 UI Features

- **Responsive Design**: Optimized for desktop and mobile devices
- **KMB Branding**: Color scheme reflecting KMB's blue branding
- **Interactive Elements**: Hover effects, popups, and real-time tooltips
- **Route Visualization**: Purple route paths with color-coded stop markers
- **Smart Caching**: Automatic data refresh with local caching for performance

## 🔍 Troubleshooting

### Common Issues

1. **Import Errors**
   - Ensure all dependencies are installed: `pip install -r requirements.txt`
   - Check Python version compatibility (3.8+)

2. **Map Not Loading**
   - Check internet connection (required for OpenStreetMap tiles)
   - Verify firewall settings allow map tile downloads

3. **KMB API Data Not Loading**
   - Government APIs may have rate limits or temporary outages
   - Application includes comprehensive fallback sample data
   - Check API endpoint availability at data.etabus.gov.hk

4. **Performance Issues**
   - Use the optimized version: `hk_transport_optimized.py`
   - Reduce the number of displayed routes/stops
   - Clear cache using the refresh button in sidebar

### Error Messages

- **"No KMB route data available"**: API temporarily unavailable, using sample data
- **"No KMB bus data available"**: Check route selections in sidebar
- **"Loading KMB data..."**: Normal loading state, wait for completion

## 📈 Future Enhancements

- [ ] Historical ETA accuracy analysis for KMB routes
- [ ] KMB fare calculation integration
- [ ] Route planning between KMB stops
- [ ] Mobile app version for KMB riders
- [ ] Multi-language support (English/Traditional Chinese/Simplified Chinese)
- [ ] Weather impact analysis on KMB services
- [ ] Bus capacity and crowding level predictions
- [ ] Integration with KMB App+ features

## 🚌 About KMB/LWB

### Kowloon Motor Bus (KMB)
- **Established**: 1933
- **Service Area**: Kowloon and New Territories
- **Fleet Size**: Over 4,000 buses
- **Daily Passengers**: Approximately 2.8 million
- **Route Network**: 400+ routes covering urban and suburban areas
- **Headquarters**: Kowloon Bay Depot

### Long Win Bus (LWB)
- **Service**: Airport and North Lantau Island routes
- **Integration**: Part of the KMB Group
- **Special Routes**: Connecting Tung Chung, Airport, and Disneyland

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch focused on KMB improvements
3. Make your changes (ensure they maintain KMB focus)
4. Test thoroughly with KMB data
5. Submit a pull request

## 📄 License

This project is open source and available under the MIT License.

## 🙏 Acknowledgments

- Hong Kong Government for providing comprehensive KMB open data
- KMB for their extensive API and real-time data services
- Long Win Bus for route and schedule information
- OpenStreetMap contributors for detailed Hong Kong map data
- Streamlit community for the excellent framework

## 📞 Support

For issues, questions, or suggestions:
- Create an issue in the repository (tag with "KMB" for bus-related issues)
- Check the troubleshooting section above
- Review the KMB API documentation

---

**Important Notes**:
- This application focuses exclusively on KMB/LWB services
- Real-time data depends on Hong Kong Government API availability
- Sample data ensures functionality even when APIs are unavailable

> **Technical Note:**
> The KMB `/route-stop` API endpoint may occasionally return errors. The application is designed to gracefully handle these cases by falling back to curated sample data that represents actual KMB routes and stops. This ensures the dashboard remains functional and informative even during API outages.

## 🔗 Useful Links

- [KMB Official Website](https://www.kmb.hk)
- [Hong Kong Government Open Data Portal](https://data.gov.hk)
- [KMB ETA API Documentation](https://data.etabus.gov.hk)
- [Transport Department Hong Kong](https://www.td.gov.hk) 