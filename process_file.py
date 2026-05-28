"""
Process a vector file with rotation + antimeridian clip.
Usage (from project root):
    "D:\QGIS 3.40.10\bin\python-qgis-ltr.bat" process_file.py
"""
import sys
import os

# Ensure qgis_d3_geo is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgis_d3_geo.qgis_tool import process_file

INPUT = r"test_data\ne_110m_land.shp"
ROTATION = [0, 45, 0]
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ne_110m_land_rotated_" + "_".join(f"{v:+d}" for v in ROTATION) + ".shp")

print(f"Input:  {INPUT}")
print(f"Output: {OUTPUT}")
print(f"Rotation: {ROTATION}")
print("Processing...")

result = process_file(INPUT, rotation=ROTATION, output_path=OUTPUT)

if result.isValid():
    count = result.featureCount()
    print(f"Done! Output has {count} features.")
else:
    print("Error: output layer is not valid.")
