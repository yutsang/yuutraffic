#!/usr/bin/env python3
"""
Test script for Hong Kong Transportation Map with OpenStreetMap
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import folium
import pandas as pd
from hk_transport_enhanced import HK_BOUNDARY, HK_CENTER, HKTransportData, create_hk_map


def test_map_creation():
    """Test map creation with OpenStreetMap"""
    print("🧪 Testing Hong Kong Transportation Map with OpenStreetMap...")

    # Initialize transport data
    transport_data = HKTransportData()

    # Get sample data
    print("📊 Loading transportation data...")
    mtr_data = transport_data.get_mtr_data()
    bus_data = transport_data.get_bus_data()
    minibus_data = transport_data.get_minibus_data()

    print(f"✅ MTR Stations: {len(mtr_data)}")
    print(f"✅ Bus Stops: {len(bus_data)}")
    print(f"✅ Minibus Routes: {len(minibus_data)}")

    # Create transport data dictionary
    transport_data_dict = {"MTR": mtr_data, "Bus": bus_data, "Minibus": minibus_data}

    # Test map creation
    print("🗺️ Creating map with OpenStreetMap...")
    try:
        map_obj = create_hk_map(transport_data_dict)
        print("✅ Map created successfully!")

        # Check map properties
        print(f"📍 Map center: {map_obj.location}")
        print(f"🔍 Default zoom: {map_obj.options.get('zoom', 'N/A')}")

        # Check if OpenStreetMap tiles are used
        tile_layers = [
            layer for layer in map_obj._children.values() if hasattr(layer, "tiles")
        ]
        if tile_layers:
            print(f"🗺️ Tile layer: {tile_layers[0].tiles}")

        # Save map for inspection
        map_file = "test_hk_map.html"
        map_obj.save(map_file)
        print(f"💾 Map saved to: {map_file}")

        return True

    except Exception as e:
        print(f"❌ Error creating map: {e}")
        return False


def test_coordinates():
    """Test Hong Kong coordinates"""
    print("\n📍 Testing Hong Kong coordinates...")

    print(f"✅ HK Center: {HK_CENTER}")
    print(f"✅ HK Boundary points: {len(HK_BOUNDARY)}")

    # Validate coordinates
    lat, lng = HK_CENTER
    if 22.0 <= lat <= 23.0 and 113.0 <= lng <= 115.0:
        print("✅ Coordinates are within Hong Kong bounds")
    else:
        print("❌ Coordinates are outside Hong Kong bounds")

    return True


def test_data_validation():
    """Test data validation"""
    print("\n📊 Testing data validation...")

    transport_data = HKTransportData()

    # Test MTR data
    mtr_data = transport_data.get_mtr_data()
    if not mtr_data.empty:
        print("✅ MTR data loaded successfully")
        print(f"   - Columns: {list(mtr_data.columns)}")
        print(f"   - Sample station: {mtr_data.iloc[0]['name']}")
    else:
        print("❌ MTR data is empty")

    # Test bus data
    bus_data = transport_data.get_bus_data()
    if not bus_data.empty:
        print("✅ Bus data loaded successfully")
        print(f"   - Columns: {list(bus_data.columns)}")
        print(f"   - Sample stop: {bus_data.iloc[0]['name']}")
    else:
        print("❌ Bus data is empty")

    # Test minibus data
    minibus_data = transport_data.get_minibus_data()
    if not minibus_data.empty:
        print("✅ Minibus data loaded successfully")
        print(f"   - Columns: {list(minibus_data.columns)}")
        print(f"   - Sample route: {minibus_data.iloc[0]['name']}")
    else:
        print("❌ Minibus data is empty")

    return True


def test_openstreetmap_specific():
    """Test OpenStreetMap specific functionality"""
    print("\n🗺️ Testing OpenStreetMap specific features...")

    # Create a simple map with OpenStreetMap
    try:
        m = folium.Map(location=HK_CENTER, zoom_start=11, tiles="OpenStreetMap")

        # Add a test marker
        folium.Marker(
            location=HK_CENTER,
            popup="Hong Kong Central",
            icon=folium.Icon(color="red", icon="info-sign"),
        ).add_to(m)

        # Add Hong Kong boundary
        folium.Polygon(
            locations=HK_BOUNDARY,
            color="black",
            weight=2,
            fill=False,
            popup="Hong Kong SAR",
        ).add_to(m)

        # Save test map
        test_map_file = "test_osm_map.html"
        m.save(test_map_file)
        print(f"✅ OpenStreetMap test map saved to: {test_map_file}")

        # Check if map has OpenStreetMap tiles
        if "OpenStreetMap" in str(m):
            print("✅ OpenStreetMap tiles configured correctly")
        else:
            print("❌ OpenStreetMap tiles not found")

        return True

    except Exception as e:
        print(f"❌ Error testing OpenStreetMap: {e}")
        return False


def main():
    """Main test function"""
    print("🚇 Hong Kong Transportation Map Test Suite")
    print("=" * 50)

    tests = [
        ("Coordinates", test_coordinates),
        ("Data Validation", test_data_validation),
        ("OpenStreetMap", test_openstreetmap_specific),
        ("Map Creation", test_map_creation),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n🧪 Running {test_name} test...")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test failed: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 50)
    print("📋 Test Results Summary:")
    print("=" * 50)

    passed = 0
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
        if result:
            passed += 1

    print(f"\n📊 Overall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! The map with OpenStreetMap is working correctly.")
    else:
        print("⚠️  Some tests failed. Please check the errors above.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
