# 🚌 KMB Database System Migration Guide

This document explains the migration from sample data to a local database-based system for KMB transportation data.

## 📋 Overview

The system has been migrated from using **sample data** to a **local SQLite database** approach:

- **Before**: Routes and stops were hardcoded as sample data
- **After**: Routes and stops are stored in a local database and updated from the official KMB API
- **ETA Data**: Still fetched in real-time from the API (as it should be)

## 🔧 System Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   KMB API       │    │  Local Database │    │  Dashboard App  │
│                 │    │                 │    │                 │
│ • Routes        │───▶│ • routes        │───▶│ • Route Info    │
│ • Stops         │    │ • stops         │    │ • Stop Info     │
│ • Route-Stops   │    │ • route_stops   │    │ • Map Display   │
│ • ETA (live)    │──────────────────────────▶│ • Real-time ETA │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🗃️ Database Schema

The system uses SQLite with the following tables:

### `routes`
- `route_id` (TEXT PRIMARY KEY)
- `route_name` (TEXT)
- `origin_en` (TEXT)
- `destination_en` (TEXT)
- `service_type` (INTEGER)
- `company` (TEXT)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### `stops`
- `stop_id` (TEXT PRIMARY KEY)
- `stop_name_en` (TEXT)
- `lat` (REAL)
- `lng` (REAL)
- `company` (TEXT)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### `route_stops`
- `route_id` (TEXT)
- `stop_id` (TEXT)
- `direction` (INTEGER)
- `service_type` (INTEGER)
- `sequence` (INTEGER)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### `data_updates`
- `update_type` (TEXT)
- `records_updated` (INTEGER)
- `status` (TEXT)
- `error_message` (TEXT)
- `updated_at` (TIMESTAMP)

## 🚀 Getting Started

### 1. Initial Database Setup

First, populate the database with KMB data:

```bash
# Update all data (routes, stops, route-stops)
python data_updater.py --all

# Or update specific components
python data_updater.py --routes
python data_updater.py --stops
python data_updater.py --route-stops
```

### 2. Check Database Status

```bash
# Check current database status
python data_updater.py --status
```

### 3. Run the Dashboard

```bash
# Start the Streamlit dashboard
streamlit run hk_transport_enhanced.py
```

## 🔄 Data Updates

### Daily Updates

Set up a cron job for daily updates:

```bash
# Add to crontab (runs daily at 3 AM)
0 3 * * * /usr/bin/python3 /path/to/data_updater.py --all
```

### Manual Updates

```bash
# Full update (may take 10-30 minutes)
python data_updater.py --all

# Quick update (routes and stops only)
python data_updater.py --routes --stops
```

### Update Options

```bash
# Limit route-stops update for testing
python data_updater.py --route-stops --max-routes 10

# Update specific database file
python data_updater.py --all --db-path custom_kmb.db
```

## 🎯 Key Benefits

### Performance
- **Faster Loading**: Routes and stops load instantly from local database
- **Reduced API Calls**: Only ETA data fetched from API in real-time
- **Offline Capability**: Basic route/stop info available without internet

### Reliability
- **No Sample Data**: All data is authentic from KMB API
- **Data Freshness**: Regular updates ensure current information
- **Fallback Handling**: Graceful handling when database is empty

### Efficiency
- **Reduced API Load**: Thousands of stops/routes cached locally
- **Cost Effective**: Minimal API usage for static data
- **Scalable**: Database can handle full KMB network data

## 📊 Usage Examples

### Basic Usage

```python
from database_manager import KMBDatabaseManager
from api_connectors import KMBLWBConnector

# Initialize components
db_manager = KMBDatabaseManager()
api_connector = KMBLWBConnector()

# Get routes from database (fast)
routes = api_connector.get_routes()
print(f"Total routes: {len(routes)}")

# Get stops from database (fast)
stops = api_connector.get_stops()
print(f"Total stops: {len(stops)}")

# Get ETA from API (real-time)
eta_data = api_connector.get_stop_eta("some_stop_id")
```

### Database Management

```python
# Check database statistics
stats = db_manager.get_database_stats()
print(f"Routes: {stats['routes_count']}")
print(f"Stops: {stats['stops_count']}")
print(f"Last update: {stats['last_routes_update']}")

# Check if data is stale
is_stale = db_manager.is_data_stale(max_age_hours=24)
if is_stale:
    print("Database needs updating")
```

## 🔧 Configuration

### Database Configuration

Update `config.py`:

```python
# Data Configuration
DATA_CONFIG = {
    'cache_timeout': 300,  # seconds
    'max_retries': 3,
    'timeout': 10,
    'use_local_database': True,  # Use local SQLite database
    'database_path': 'kmb_data.db'  # Path to SQLite database
}
```

### API Configuration

The API connector automatically uses the database for routes/stops:

```python
# Database-backed connector
connector = KMBLWBConnector(db_path="kmb_data.db")

# Routes and stops from database
routes = connector.get_routes()
stops = connector.get_stops()

# ETA still from API
eta = connector.get_stop_eta(stop_id)
```

## 🛠️ Migration Process

### What Changed

1. **Removed Sample Data**:
   - `SAMPLE_KMB_ROUTES` removed from `config.py`
   - `SAMPLE_KMB_STOPS` removed from `config.py`
   - Sample data methods removed from `api_connectors.py`

2. **Added Database System**:
   - `database_manager.py` - SQLite database management
   - `data_updater.py` - Data fetching and updating
   - Updated `api_connectors.py` - Uses database for routes/stops

3. **Updated Applications**:
   - `hk_transport_enhanced.py` - Added database status display
   - `hk_transport_optimized.py` - Compatible with database system

### Migration Steps

1. **Remove old sample data** ✅
2. **Create database system** ✅
3. **Update API connectors** ✅
4. **Update applications** ✅
5. **Test system** ✅

## 🧪 Testing

### Run Demo Script

```bash
# Demo the system (database must be populated first)
python example_usage.py

# Demo with database update
python example_usage.py --update
```

### Test Components

```bash
# Test database manager
python -c "from database_manager import KMBDatabaseManager; print(KMBDatabaseManager().get_database_stats())"

# Test data updater
python -c "from data_updater import KMBDataUpdater; print(KMBDataUpdater().get_update_status())"

# Test API connector
python -c "from api_connectors import KMBLWBConnector; print(len(KMBLWBConnector().get_routes()))"
```

## 📝 Troubleshooting

### Empty Database

**Problem**: Dashboard shows "Database empty" warning

**Solution**:
```bash
python data_updater.py --all
```

### Stale Data

**Problem**: Data is more than 24 hours old

**Solution**:
```bash
python data_updater.py --routes --stops
```

### API Errors

**Problem**: Data updater fails with API errors

**Solution**:
- Check internet connection
- Verify KMB API is accessible
- Check API response format hasn't changed
- Run with fewer routes: `python data_updater.py --route-stops --max-routes 5`

### Database Corruption

**Problem**: Database file is corrupted

**Solution**:
```bash
# Remove database file and recreate
rm kmb_data.db
python data_updater.py --all
```

## 🔮 Future Enhancements

1. **Scheduled Updates**: Automatic daily updates with cron
2. **Multiple Transport Modes**: Extend to other transport operators
3. **Data Compression**: Optimize database storage
4. **API Rate Limiting**: Intelligent throttling for updates
5. **Data Validation**: Verify data integrity during updates

## 📞 Support

For issues or questions about the database system:

1. Check the database status: `python data_updater.py --status`
2. Review update logs: `data_updater.log`
3. Test with demo script: `python example_usage.py`
4. Clear and rebuild database if needed

---

**Migration Complete** ✅

The system now uses a local database for efficient, reliable access to KMB transportation data while maintaining real-time ETA capabilities. 