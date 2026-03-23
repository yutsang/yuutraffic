# 🚀 Deployment Guide

## Overview

This guide covers how to deploy the Hong Kong KMB Transport application in various environments, from local development to production servers.

## Prerequisites

- Python 3.8+
- pip package manager
- Git (for version control)
- Internet connection (for OSM routing)

## Local Development

### Quick Start

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd e-Mobility-analysis/hk-kmb-transport
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the application:**
   ```bash
   python src/hk_kmb_transport/run_production.py
   ```

5. **Access the application:**
   ```
   http://localhost:8508
   ```

### Development Mode

For development with hot reloading:

```bash
# Enable development mode
export STREAMLIT_ENV=development

# Run with auto-reload
streamlit run src/hk_kmb_transport/kmb_app_production.py --server.port 8508 --server.runOnSave true
```

## Production Deployment

### Server Requirements

**Minimum:**
- CPU: 2 cores
- RAM: 4GB
- Storage: 10GB
- Network: 100Mbps

**Recommended:**
- CPU: 4 cores
- RAM: 8GB
- Storage: 20GB
- Network: 1Gbps

### Option 1: Direct Python Deployment

1. **Prepare the server:**
   ```bash
   # Update system
   sudo apt update && sudo apt upgrade -y
   
   # Install Python and tools
   sudo apt install python3.8 python3-pip python3-venv nginx -y
   ```

2. **Clone and setup:**
   ```bash
   git clone <repository-url>
   cd e-Mobility-analysis/hk-kmb-transport
   
   # Create virtual environment
   python3 -m venv venv
   source venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

3. **Create systemd service:**
   ```bash
   sudo vim /etc/systemd/system/kmb-transport.service
   ```

   ```ini
   [Unit]
   Description=KMB Transport Application
   After=network.target
   
   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/e-Mobility-analysis/hk-kmb-transport
   Environment=PATH=/home/ubuntu/e-Mobility-analysis/hk-kmb-transport/venv/bin
   ExecStart=/home/ubuntu/e-Mobility-analysis/hk-kmb-transport/venv/bin/python src/hk_kmb_transport/run_production.py
   Restart=always
   
   [Install]
   WantedBy=multi-user.target
   ```

4. **Enable and start service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable kmb-transport
   sudo systemctl start kmb-transport
   ```

5. **Configure Nginx (optional):**
   ```bash
   sudo vim /etc/nginx/sites-available/kmb-transport
   ```

   ```nginx
   server {
       listen 80;
       server_name your-domain.com;
       
       location / {
           proxy_pass http://localhost:8508;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

   ```bash
   sudo ln -s /etc/nginx/sites-available/kmb-transport /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

### Option 2: Docker Deployment

1. **Create Dockerfile:**
   ```dockerfile
   FROM python:3.8-slim
   
   WORKDIR /app
   
   # Install system dependencies
   RUN apt-get update && apt-get install -y \
       sqlite3 \
       && rm -rf /var/lib/apt/lists/*
   
   # Copy requirements and install Python dependencies
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   
   # Copy application code
   COPY . .
   
   # Create data directory
   RUN mkdir -p data/01_raw
   
   # Expose port
   EXPOSE 8508
   
   # Run the application
   CMD ["python", "src/hk_kmb_transport/run_production.py"]
   ```

2. **Create docker-compose.yml:**
   ```yaml
   version: '3.8'
   
   services:
     kmb-transport:
       build: .
       ports:
         - "8508:8508"
       volumes:
         - ./data:/app/data
       restart: unless-stopped
       environment:
         - STREAMLIT_SERVER_PORT=8508
         - STREAMLIT_SERVER_ADDRESS=0.0.0.0
   ```

3. **Build and run:**
   ```bash
   docker-compose up -d
   ```

### Option 3: Cloud Deployment (Heroku)

1. **Create Procfile:**
   ```
   web: python src/hk_kmb_transport/run_production.py
   ```

2. **Create runtime.txt:**
   ```
   python-3.8.16
   ```

3. **Deploy to Heroku:**
   ```bash
   heroku create kmb-transport-app
   heroku config:set STREAMLIT_SERVER_PORT=$PORT
   heroku config:set STREAMLIT_SERVER_ADDRESS=0.0.0.0
   git push heroku main
   ```

## Environment Configuration

### Environment Variables

```bash
# Server Configuration
export STREAMLIT_SERVER_PORT=8508
export STREAMLIT_SERVER_ADDRESS=0.0.0.0
export STREAMLIT_SERVER_HEADLESS=true

# Database Configuration
export KMB_DB_PATH=data/01_raw/kmb_data.db

# Caching Configuration
export CACHE_TTL=3600

# Logging Configuration
export LOG_LEVEL=INFO
export LOG_FILE=logs/kmb_transport.log
```

### Configuration Files

Create `config/production.env`:
```env
# Production settings
STREAMLIT_SERVER_PORT=8508
STREAMLIT_SERVER_ADDRESS=0.0.0.0
STREAMLIT_SERVER_HEADLESS=true
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
STREAMLIT_SERVER_RUN_ON_SAVE=false

# Database settings
KMB_DB_PATH=data/01_raw/kmb_data.db

# Performance settings
CACHE_TTL=3600
MAX_WAYPOINTS=25
ROUTING_TIMEOUT=10
```

## Monitoring and Logging

### Application Logs

1. **Configure logging:**
   ```python
   import logging
   
   logging.basicConfig(
       level=logging.INFO,
       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
       handlers=[
           logging.FileHandler('logs/kmb_transport.log'),
           logging.StreamHandler()
       ]
   )
   ```

2. **Monitor logs:**
   ```bash
   # Real-time log monitoring
   tail -f logs/kmb_transport.log
   
   # Search for errors
   grep -i error logs/kmb_transport.log
   ```

### System Monitoring

1. **Check application status:**
   ```bash
   sudo systemctl status kmb-transport
   ```

2. **Monitor resource usage:**
   ```bash
   # CPU and memory usage
   top -p $(pgrep -f kmb_transport)
   
   # Disk usage
   df -h
   
   # Network usage
   netstat -tuln | grep 8508
   ```

### Health Checks

1. **Create health check script:**
   ```bash
   #!/bin/bash
   # health_check.sh
   
   response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8508)
   
   if [ $response -eq 200 ]; then
       echo "Application is healthy"
       exit 0
   else
       echo "Application is unhealthy: HTTP $response"
       exit 1
   fi
   ```

2. **Set up monitoring cron job:**
   ```bash
   # Add to crontab
   */5 * * * * /path/to/health_check.sh
   ```

## Database Management

### Backup Strategy

1. **Automated backups:**
   ```bash
   #!/bin/bash
   # backup_db.sh
   
   DATE=$(date +%Y%m%d_%H%M%S)
   BACKUP_DIR="/backup/kmb_transport"
   
   mkdir -p $BACKUP_DIR
   
   # Create backup
   sqlite3 data/01_raw/kmb_data.db ".backup $BACKUP_DIR/kmb_data_$DATE.db"
   
   # Compress backup
   gzip "$BACKUP_DIR/kmb_data_$DATE.db"
   
   # Remove old backups (keep last 7 days)
   find $BACKUP_DIR -name "*.gz" -mtime +7 -delete
   ```

2. **Schedule backups:**
   ```bash
   # Daily backup at 2 AM
   0 2 * * * /path/to/backup_db.sh
   ```

### Database Updates

1. **Update route data:**
   ```bash
   # Backup current database
   cp data/01_raw/kmb_data.db data/01_raw/kmb_data_backup.db
   
   # Update data
   python src/hk_kmb_transport/data_updater.py --all
   
   # Restart application
   sudo systemctl restart kmb-transport
   ```

## Security

### Basic Security Measures

1. **Firewall configuration:**
   ```bash
   # Allow SSH and HTTP
   sudo ufw allow 22
   sudo ufw allow 80
   sudo ufw allow 8508
   sudo ufw enable
   ```

2. **SSL/TLS (with Let's Encrypt):**
   ```bash
   # Install certbot
   sudo apt install certbot python3-certbot-nginx
   
   # Get certificate
   sudo certbot --nginx -d your-domain.com
   ```

3. **Application security:**
   - Use environment variables for sensitive data
   - Implement rate limiting
   - Regular security updates
   - Monitor access logs

## Performance Optimization

### Application Optimization

1. **Caching configuration:**
   ```python
   # Streamlit caching
   @st.cache_data(ttl=3600)
   def load_cached_data():
       return load_kmb_data()
   ```

2. **Database optimization:**
   ```sql
   -- Optimize database
   VACUUM;
   ANALYZE;
   
   -- Check query performance
   EXPLAIN QUERY PLAN SELECT * FROM routes WHERE route_id = '65X';
   ```

### Server Optimization

1. **System tuning:**
   ```bash
   # Increase file limits
   echo "* soft nofile 65536" >> /etc/security/limits.conf
   echo "* hard nofile 65536" >> /etc/security/limits.conf
   
   # Optimize TCP settings
   echo "net.core.somaxconn = 65536" >> /etc/sysctl.conf
   sysctl -p
   ```

2. **Memory optimization:**
   ```bash
   # Monitor memory usage
   free -h
   
   # Clear cache if needed
   echo 3 > /proc/sys/vm/drop_caches
   ```

## Troubleshooting

### Common Issues

1. **Application won't start:**
   ```bash
   # Check logs
   sudo journalctl -u kmb-transport -f
   
   # Check port availability
   lsof -i :8508
   
   # Check database permissions
   ls -la data/01_raw/kmb_data.db
   ```

2. **Database connection errors:**
   ```bash
   # Test database connection
   sqlite3 data/01_raw/kmb_data.db "SELECT COUNT(*) FROM routes;"
   
   # Check file integrity
   sqlite3 data/01_raw/kmb_data.db "PRAGMA integrity_check;"
   ```

3. **Performance issues:**
   ```bash
   # Check system resources
   htop
   
   # Check disk I/O
   iotop
   
   # Check network
   netstat -i
   ```

### Recovery Procedures

1. **Application crash recovery:**
   ```bash
   # Stop application
   sudo systemctl stop kmb-transport
   
   # Clear cache
   rm -rf .streamlit
   
   # Restart application
   sudo systemctl start kmb-transport
   ```

2. **Database corruption recovery:**
   ```bash
   # Restore from backup
   cp backup/kmb_data_backup.db data/01_raw/kmb_data.db
   
   # Restart application
   sudo systemctl restart kmb-transport
   ```

## Maintenance

### Regular Maintenance Tasks

1. **Weekly tasks:**
   - Check application logs
   - Monitor disk usage
   - Review performance metrics
   - Update dependencies

2. **Monthly tasks:**
   - System updates
   - Database optimization
   - Security audit
   - Backup verification

3. **Quarterly tasks:**
   - Performance review
   - Capacity planning
   - Security updates
   - Documentation updates

### Automated Maintenance

Create maintenance script:
```bash
#!/bin/bash
# maintenance.sh

# System updates
sudo apt update && sudo apt upgrade -y

# Database maintenance
sqlite3 data/01_raw/kmb_data.db "VACUUM; ANALYZE;"

# Log rotation
sudo logrotate -f /etc/logrotate.d/kmb-transport

# Clear old cache files
find .streamlit -name "*.cache" -mtime +7 -delete

# Restart application
sudo systemctl restart kmb-transport

echo "Maintenance completed: $(date)"
```

## Support

For deployment issues:
- Check the troubleshooting guide above
- Review application logs
- Verify system requirements
- Create an issue on GitHub with deployment details 