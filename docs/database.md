# 🗄️ Database Schema Documentation

## Overview

The KMB Transport application uses SQLite for local data storage. The database contains comprehensive information about Hong Kong KMB routes, stops, and their relationships.

## Database File
- **Location**: `data/01_raw/kmb_data.db`
- **Type**: SQLite 3
- **Size**: ~5.8 MB
- **Encoding**: UTF-8

## Tables Overview

| Table | Records | Description |
|-------|---------|-------------|
| `routes` | 788 | Route information and metadata |
| `stops` | 5,000+ | Bus stop locations and details |
| `route_stops` | 29,740 | Route-stop mappings with sequences |

## Table Schemas

### `routes` Table

Stores basic route information for all KMB routes.

```sql
CREATE TABLE routes (
    route_id TEXT PRIMARY KEY,
    route_name TEXT,
    origin_en TEXT,
    destination_en TEXT,
    service_type INTEGER,
    company TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Columns Description

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `route_id` | TEXT | Unique route identifier | "65X", "24", "219X" |
| `route_name` | TEXT | Display name of the route | "Route 65X" |
| `origin_en` | TEXT | English name of origin stop | "Tin Shui Wai (Tin Yiu Bus Terminus)" |
| `destination_en` | TEXT | English name of destination stop | "Tsim Sha Tsui (Circular)" |
| `service_type` | INTEGER | Service type code (usually 1) | 1 |
| `company` | TEXT | Operating company | "KMB" |
| `created_at` | TIMESTAMP | Record creation time | "2024-01-15 10:30:00" |
| `updated_at` | TIMESTAMP | Last update time | "2024-01-15 10:30:00" |

#### Sample Data

```sql
SELECT * FROM routes WHERE route_id IN ('65X', '24', '219X');
```

| route_id | route_name | origin_en | destination_en | service_type | company |
|----------|------------|-----------|----------------|--------------|---------|
| 65X | Route 65X | Tin Shui Wai (Tin Yiu Bus Terminus) | Tsim Sha Tsui (Circular) | 1 | KMB |
| 24 | Route 24 | Kai Yip | Mong Kok (Circular) | 1 | KMB |
| 219X | Route 219X | Ko Ling Road | Tsim Sha Tsui (Circular) | 1 | KMB |

### `stops` Table

Stores information about all bus stops in the KMB network.

```sql
CREATE TABLE stops (
    stop_id TEXT PRIMARY KEY,
    stop_name_en TEXT,
    lat REAL,
    lng REAL,
    company TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Columns Description

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `stop_id` | TEXT | Unique stop identifier | "1A0E7C6A8B8C7D5E" |
| `stop_name_en` | TEXT | English name of the stop | "Tin Shui Wai Station" |
| `lat` | REAL | Latitude coordinate | 22.457834 |
| `lng` | REAL | Longitude coordinate | 113.993767 |
| `company` | TEXT | Operating company | "KMB" |
| `created_at` | TIMESTAMP | Record creation time | "2024-01-15 10:30:00" |
| `updated_at` | TIMESTAMP | Last update time | "2024-01-15 10:30:00" |

#### Sample Data

```sql
SELECT * FROM stops WHERE stop_name_en LIKE '%Tin Shui Wai%' LIMIT 3;
```

| stop_id | stop_name_en | lat | lng | company |
|---------|--------------|-----|-----|---------|
| 1A0E7C6A8B8C7D5E | Tin Shui Wai Station | 22.457834 | 113.993767 | KMB |
| 2B1F8D7C9A0B1E2F | Tin Shui Wai Sports Ground | 22.458123 | 113.994567 | KMB |
| 3C2E9F8D0B1A2C3E | Tin Shui Wai Park | 22.459456 | 113.995789 | KMB |

### `route_stops` Table

Maps routes to their stops with sequence information and directions.

```sql
CREATE TABLE route_stops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id TEXT,
    stop_id TEXT,
    direction INTEGER,
    sequence INTEGER,
    service_type INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (route_id) REFERENCES routes(route_id),
    FOREIGN KEY (stop_id) REFERENCES stops(stop_id)
);
```

#### Columns Description

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | INTEGER | Auto-incrementing primary key | 1, 2, 3... |
| `route_id` | TEXT | Reference to routes table | "65X" |
| `stop_id` | TEXT | Reference to stops table | "1A0E7C6A8B8C7D5E" |
| `direction` | INTEGER | Direction (1=outbound, 2=inbound) | 1 |
| `sequence` | INTEGER | Stop sequence in route | 1, 2, 3... |
| `service_type` | INTEGER | Service type code | 1 |
| `created_at` | TIMESTAMP | Record creation time | "2024-01-15 10:30:00" |
| `updated_at` | TIMESTAMP | Last update time | "2024-01-15 10:30:00" |

#### Sample Data

```sql
SELECT * FROM route_stops WHERE route_id = '65X' AND direction = 1 ORDER BY sequence LIMIT 5;
```

| id | route_id | stop_id | direction | sequence | service_type |
|----|----------|---------|-----------|----------|--------------|
| 1 | 65X | 1A0E7C6A8B8C7D5E | 1 | 1 | 1 |
| 2 | 65X | 2B1F8D7C9A0B1E2F | 1 | 2 | 1 |
| 3 | 65X | 3C2E9F8D0B1A2C3E | 1 | 3 | 1 |
| 4 | 65X | 4D3F0E9C1B2A3D4F | 1 | 4 | 1 |
| 5 | 65X | 5E4G1F0D2C3B4E5G | 1 | 5 | 1 |

## Indexes

For optimal query performance, the following indexes are recommended:

```sql
-- Route indexes
CREATE INDEX idx_routes_route_id ON routes(route_id);
CREATE INDEX idx_routes_origin ON routes(origin_en);
CREATE INDEX idx_routes_destination ON routes(destination_en);

-- Stop indexes
CREATE INDEX idx_stops_stop_id ON stops(stop_id);
CREATE INDEX idx_stops_name ON stops(stop_name_en);
CREATE INDEX idx_stops_location ON stops(lat, lng);

-- Route-stop indexes
CREATE INDEX idx_route_stops_route_id ON route_stops(route_id);
CREATE INDEX idx_route_stops_stop_id ON route_stops(stop_id);
CREATE INDEX idx_route_stops_direction ON route_stops(direction);
CREATE INDEX idx_route_stops_sequence ON route_stops(sequence);
CREATE INDEX idx_route_stops_route_direction ON route_stops(route_id, direction);
```

## Common Queries

### Get All Routes
```sql
SELECT route_id, origin_en, destination_en 
FROM routes 
ORDER BY route_id;
```

### Get Route Stops with Coordinates
```sql
SELECT 
    rs.route_id,
    rs.sequence,
    rs.direction,
    s.stop_name_en,
    s.lat,
    s.lng
FROM route_stops rs
JOIN stops s ON rs.stop_id = s.stop_id
WHERE rs.route_id = '65X' AND rs.direction = 1
ORDER BY rs.sequence;
```

### Search Routes by Destination
```sql
SELECT route_id, origin_en, destination_en
FROM routes
WHERE destination_en LIKE '%Tsim Sha Tsui%'
ORDER BY route_id;
```

### Get Route Statistics
```sql
SELECT 
    r.route_id,
    r.origin_en,
    r.destination_en,
    COUNT(DISTINCT rs.stop_id) as total_stops,
    COUNT(DISTINCT rs.direction) as directions
FROM routes r
LEFT JOIN route_stops rs ON r.route_id = rs.route_id
GROUP BY r.route_id
ORDER BY total_stops DESC;
```

### Find Routes Through a Specific Stop
```sql
SELECT DISTINCT r.route_id, r.origin_en, r.destination_en
FROM routes r
JOIN route_stops rs ON r.route_id = rs.route_id
JOIN stops s ON rs.stop_id = s.stop_id
WHERE s.stop_name_en LIKE '%Central%'
ORDER BY r.route_id;
```

## Data Integrity

### Constraints

```sql
-- Ensure route_id is not null
ALTER TABLE routes ADD CONSTRAINT route_id_not_null CHECK (route_id IS NOT NULL);

-- Ensure coordinates are valid
ALTER TABLE stops ADD CONSTRAINT valid_lat CHECK (lat BETWEEN -90 AND 90);
ALTER TABLE stops ADD CONSTRAINT valid_lng CHECK (lng BETWEEN -180 AND 180);

-- Ensure direction is valid
ALTER TABLE route_stops ADD CONSTRAINT valid_direction CHECK (direction IN (1, 2));

-- Ensure sequence is positive
ALTER TABLE route_stops ADD CONSTRAINT positive_sequence CHECK (sequence > 0);
```

### Referential Integrity

```sql
-- Enable foreign key constraints
PRAGMA foreign_keys = ON;

-- Add foreign key constraints
ALTER TABLE route_stops ADD CONSTRAINT fk_route_stops_route_id 
    FOREIGN KEY (route_id) REFERENCES routes(route_id);

ALTER TABLE route_stops ADD CONSTRAINT fk_route_stops_stop_id 
    FOREIGN KEY (stop_id) REFERENCES stops(stop_id);
```

## Maintenance

### Database Statistics
```sql
-- Check table sizes
SELECT name, COUNT(*) as record_count 
FROM (
    SELECT 'routes' as name, COUNT(*) as count FROM routes
    UNION ALL
    SELECT 'stops' as name, COUNT(*) as count FROM stops
    UNION ALL
    SELECT 'route_stops' as name, COUNT(*) as count FROM route_stops
) GROUP BY name;

-- Check database size
SELECT page_count * page_size as size_bytes 
FROM pragma_page_count(), pragma_page_size();
```

### Vacuum and Optimization
```sql
-- Optimize database
VACUUM;

-- Update table statistics
ANALYZE;

-- Check integrity
PRAGMA integrity_check;
```

## Backup and Recovery

### Create Backup
```bash
# Create backup
sqlite3 data/01_raw/kmb_data.db ".backup backup/kmb_data_backup.db"

# Verify backup
sqlite3 backup/kmb_data_backup.db "SELECT COUNT(*) FROM routes;"
```

### Restore from Backup
```bash
# Restore from backup
cp backup/kmb_data_backup.db data/01_raw/kmb_data.db
```

## Performance Considerations

### Query Optimization Tips

1. **Use Indexes**: Always use indexed columns in WHERE clauses
2. **Limit Results**: Use LIMIT for large result sets
3. **Avoid SELECT ***: Select only needed columns
4. **Use Prepared Statements**: For repeated queries
5. **Consider Joins**: Use JOINs instead of subqueries when possible

### Monitoring

```sql
-- Check slow queries
PRAGMA compile_options;

-- Monitor query performance
EXPLAIN QUERY PLAN SELECT * FROM routes WHERE route_id = '65X';
```

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-01-15 | Initial schema with basic tables |
| 1.1 | 2024-01-20 | Added indexes for performance |
| 1.2 | 2024-01-25 | Added constraints and foreign keys |
| 1.3 | 2024-02-01 | Optimized route_stops table structure |

## Support

For database-related issues:
- Check the troubleshooting guide in the main README
- Verify database integrity with `PRAGMA integrity_check`
- Review slow query logs for performance issues
- Create an issue on GitHub with specific error messages 