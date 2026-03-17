"""Test the basic application functionality."""

import os
import sys

import pandas as pd
import pytest

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))


def test_import_app():
    """Test that the app can be imported successfully."""
    try:
        from yuutraffic.web import create_route_options

        assert callable(create_route_options)
    except ImportError as e:
        pytest.fail(f"Failed to import app: {e}")


def test_create_route_options():
    """Test the create_route_options function."""
    from yuutraffic.web import create_route_options

    # Create sample data
    sample_data = pd.DataFrame(
        {
            "route_id": ["1", "2", "65X"],
            "origin": ["Central", "Admiralty", "Tin Shui Wai"],
            "destination": ["Causeway Bay", "Central", "Tsim Sha Tsui"],
            "route_type": ["Regular", "Regular", "Express"],
        }
    )

    options = create_route_options(sample_data)

    assert len(options) == 3
    assert options[0]["route_id"] == "1"
    assert "Express" in options[2]["text"]


def test_app_imports():
    """Test that all required modules can be imported."""
    try:
        import folium
        import pandas
        import streamlit
        from streamlit_folium import folium_static

        assert True
    except ImportError as e:
        pytest.fail(f"Required dependency missing: {e}")


def test_web_imports():
    """Test that web module can be imported."""
    try:
        from yuutraffic.web import load_traffic_data

        assert callable(load_traffic_data)
    except ImportError as e:
        pytest.fail(f"Failed to import web module: {e}")
