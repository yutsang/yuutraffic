# Hong Kong Transportation Dashboard - CI/CD Setup

This document explains how to set up and use the CI/CD pipeline for the Hong Kong Transportation Dashboard.

## 🚀 Quick Start

### Local Development
```bash
# Clone the repository
git clone <your-repo-url>
cd e-Mobility-analysis

# Install dependencies
pip install -r requirements.txt

# Run the application
python run_app.py
# or
streamlit run hk_transport_enhanced.py
```

### Docker Deployment
```bash
# Build and run with Docker
docker-compose up --build

# Or build and run manually
docker build -t hk-transport-app .
docker run -p 8501:8501 hk-transport-app
```

## 🔧 CI/CD Pipeline Overview

The project uses GitHub Actions for continuous integration and deployment with the following workflow:

### Pipeline Stages

1. **Test Stage**
   - Code linting with flake8
   - Unit tests with pytest
   - Code coverage reporting
   - Security scanning

2. **Build Stage**
   - Create deployment package
   - Build Docker image
   - Upload artifacts

3. **Deploy Stage**
   - Deploy to Streamlit Cloud
   - Create GitHub release
   - Update documentation

## 📋 Prerequisites

### For Local Development
- Python 3.8+
- pip
- Git

### For CI/CD
- GitHub repository
- Streamlit Cloud account (for deployment)
- Docker (for containerization)

## 🛠️ Setup Instructions

### 1. GitHub Repository Setup

1. **Fork or create a new repository**
2. **Enable GitHub Actions**
   - Go to Settings > Actions > General
   - Enable "Allow all actions and reusable workflows"

3. **Set up repository secrets** (Settings > Secrets and variables > Actions):
   ```
   STREAMLIT_SHARING_TOKEN: Your Streamlit Cloud token
   ```

### 2. Streamlit Cloud Deployment

1. **Sign up for Streamlit Cloud** at https://streamlit.io/cloud
2. **Connect your GitHub repository**
3. **Deploy the app**:
   - Main file path: `hk_transport_enhanced.py`
   - Python version: 3.10
   - Requirements file: `requirements.txt`

### 3. Docker Setup

```bash
# Build the image
docker build -t hk-transport-app .

# Run the container
docker run -p 8501:8501 hk-transport-app

# Or use docker-compose
docker-compose up --build
```

## 🔍 Testing

### Run Tests Locally
```bash
# Install test dependencies
pip install pytest pytest-cov flake8

# Run all tests
pytest

# Run with coverage
pytest --cov=.

# Run linting
flake8 .

# Run specific test file
pytest tests/test_app.py -v
```

### Test Structure
```
tests/
├── test_app.py          # Main application tests
├── test_data.py         # Data validation tests
├── test_api.py          # API integration tests
└── conftest.py          # Test configuration
```

## 📊 Code Quality

### Linting
The project uses flake8 for code linting with custom configuration in `.flake8`.

### Code Formatting
```bash
# Install formatting tools
pip install black isort

# Format code
black .
isort .
```

### Pre-commit Hooks
```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

## 🚀 Deployment Options

### 1. Streamlit Cloud (Recommended)
- **Pros**: Easy setup, free tier, automatic deployments
- **Cons**: Limited customization, vendor lock-in

### 2. Docker + Cloud Platform
- **Pros**: Full control, portable, scalable
- **Cons**: More complex setup, requires infrastructure

### 3. Self-hosted
- **Pros**: Complete control, no vendor dependencies
- **Cons**: Requires server management, security considerations

## 🔧 Configuration

### Environment Variables
```bash
# Application settings
STREAMLIT_SERVER_PORT=8501
STREAMLIT_SERVER_ADDRESS=0.0.0.0

# API settings
MTR_API_URL=https://opendata.mtr.com.hk
BUS_API_URL=https://data.etabus.gov.hk

# Database settings (if using)
DATABASE_URL=postgresql://user:pass@localhost/db
```

### Configuration Files
- `config.py`: Application configuration
- `pytest.ini`: Test configuration
- `.flake8`: Linting configuration
- `docker-compose.yml`: Docker services configuration

## 📈 Monitoring and Logging

### Health Checks
The application includes health check endpoints:
- `/_stcore/health`: Streamlit health check
- `/health`: Custom health check

### Logging
```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## 🔒 Security Considerations

### Environment Variables
- Never commit sensitive data to version control
- Use GitHub Secrets for CI/CD
- Use environment variables for configuration

### Docker Security
- Run containers as non-root user
- Use multi-stage builds
- Scan images for vulnerabilities

### API Security
- Implement rate limiting
- Use HTTPS for all API calls
- Validate input data

## 🐛 Troubleshooting

### Common Issues

1. **Import Errors**
   ```bash
   # Solution: Install missing dependencies
   pip install -r requirements.txt
   ```

2. **Port Already in Use**
   ```bash
   # Solution: Change port or kill process
   lsof -ti:8501 | xargs kill -9
   ```

3. **Docker Build Failures**
   ```bash
   # Solution: Clear Docker cache
   docker system prune -a
   ```

4. **CI/CD Pipeline Failures**
   - Check GitHub Actions logs
   - Verify repository secrets
   - Ensure all dependencies are in requirements.txt

### Debug Mode
```bash
# Run with debug logging
STREAMLIT_LOG_LEVEL=debug streamlit run hk_transport_enhanced.py
```

## 📚 Additional Resources

- [Streamlit Documentation](https://docs.streamlit.io/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Documentation](https://docs.docker.com/)
- [Pytest Documentation](https://docs.pytest.org/)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

### Development Workflow
```bash
# Create feature branch
git checkout -b feature/new-feature

# Make changes and test
pytest
flake8 .

# Commit changes
git add .
git commit -m "Add new feature"

# Push and create PR
git push origin feature/new-feature
```

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details. 