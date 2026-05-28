# Latitudinally Equal-Differential Polyconic Projection (1963 Scheme & Hao Xiaoguang Scheme)

## Overview

This project provides a QGIS data processing toolchain for the **Latitudinally Equal-Differential Polyconic Projection**.

Core workflow: **Spherical rotation → Antimeridian clipping → Geometry fix → Densification → Projection**

Features:

- Port of D3-geo's spherical rotation and antimeridian clipping algorithms to Python
- QGIS Processing toolbox script for seamless integration into QGIS workflows
- Batch processing of vector layers through rotation, clipping, and projection
- Quality-check tools for area/distance change detection

## Project Structure

```
├── qgis_d3_geo/                # Python package: D3-geo port + QGIS tools
│   ├── __init__.py             # Package entry, exports rotate / clip / process
│   ├── d3_geo.py               # Pure Python implementation of D3-geo rotation & clipping
│   └── qgis_tool.py            # QGIS layer processing tools (process_layer / process_file)
├── test_data/                  # Test data (Natural Earth 110m land outline)
│   └── ne_110m_land.*          # 1:110m global land vector from Natural Earth
├── check_rotation.py           # Batch check: area/vertex-distance comparison + JPG output
├── process_file.py             # Single-file processing: rotation + antimeridian clipping
├── script_template.py          # QGIS Processing script template (full projection tool)
└── README.en.md
```

## Dependencies

### Python package (pure algorithm)

No external dependencies — only the standard `math` library.

### QGIS tools (qgis_tool.py / script_template.py)

- [QGIS](https://qgis.org/) (tested on version 3.40.10-Bratislava)
- Requires QGIS's bundled Python environment (`python-qgis-ltr.bat` or QGIS Processing Framework)

## Quick Start

### 1. Process a single vector file

Edit the input path and rotation parameters in [process_file.py](process_file.py), then run:

```batch
"D:\QGIS 3.40.10\bin\python-qgis-ltr.bat" process_file.py
```

The example rotates `test_data/ne_110m_land.shp` by 45° longitude and outputs to `ne_110m_land_rotated_+0_+45_+0.shp`.

### 2. Batch-check rotation quality

Edit the input path and rotation angle combinations in [check_rotation.py](check_rotation.py), then run:

```batch
"D:\QGIS 3.40.10\bin\python-qgis-ltr.bat" check_rotation.py
```

The script scans multiple rotation angle combinations, computes area changes and vertex displacements for each feature, and outputs JPG comparison charts.

### 3. Use in QGIS Processing

1. Copy the [qgis_d3_geo](qgis_d3_geo) folder and [script_template.py](script_template.py) to the QGIS script path `\AppData\Roaming\QGIS\QGIS3\profiles\default\processing\scripts`
2. Open QGIS, the tool will appear under **Toolbox → Scripts**, ready to use like any standard QGIS algorithm
![qgis_script_tool_screenshot](qgis_script_tool_screenshot.jpg)

## Core Algorithms

### Spherical Rotation

A three-axis rotation (longitude λ, latitude φ, roll γ) based on D3-geo, which rotates spherical coordinates around three axes sequentially to center the area of interest.

### Antimeridian Clipping

After rotation, geometries that were continuous near the antimeridian (±180°) may become torn. The algorithm clips along the antimeridian and rebuilds the geometry topology to ensure correct subsequent projection.

### Equal-difference Parallel Polyconic Projection (1963 Scheme)

- Central meridian and equator remain orthogonal
- Parallels are concentric circular arcs symmetric about the equator, with centers on the central meridian
- Meridians are curves symmetric about the central meridian, with spacing decreasing arithmetically as distance from the central meridian increases
- The poles deform into two symmetric arcs, half the length of the equator's projection (usually trimmed by the map border)
- China is positioned near the map center, with territorial distortion under 10%

### Generalized Equal-difference Parallel Polyconic Projection (Hao Xiaoguang Scheme)

- Uses a 5th-degree polynomial to fit the cubic spline function of the 1963 scheme
- Defines 4 rotation angle configurations for east, west, north, and south map orientations
- The southern hemisphere version is commonly used for vertical world maps

> Projection implementation based on [Ishisashi's D3 implementation](https://mrhso.github.io/IshisashiWebsite/projection/).

## License

The source code in this project is licensed under the MIT License. Test data is from [Natural Earth](https://www.naturalearthdata.com/) and is in the public domain.
