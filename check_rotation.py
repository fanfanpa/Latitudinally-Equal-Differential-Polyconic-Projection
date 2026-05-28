"""
Batch check: area / vertex-distance before-vs-after comparison + JPG output.
Usage:
    "D:\QGIS 3.40.10\bin\python-qgis-ltr.bat" check_rotation.py
"""
import sys
import os
import math
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPoint, QgsLineString,
    QgsMapSettings, QgsMapRendererCustomPainterJob,
    QgsRectangle, QgsFillSymbol, QgsLineSymbol,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QImage, QPainter, QColor

from qgis_d3_geo.qgis_tool import process_file, _extract_rings_from_geometry
from qgis_d3_geo.d3_geo import _ring_signed_area

# ══════════════════════════════════════════════════════════════════════════════
#  Spherical geometry helpers
# ══════════════════════════════════════════════════════════════════════════════

R_EARTH = 6371.0
R2 = R_EARTH ** 2  # km² per steradian


def _ring_area_sr(ring_deg):
    """Signed spherical area of a ring in steradians."""
    m = len(ring_deg)
    if m < 3:
        return 0.0
    rad = [[math.radians(p[0]), math.radians(p[1])] for p in ring_deg]
    return _ring_signed_area(rad)


def _haversine_km(p0, p1):
    """Great-circle distance (km) between two [lon, lat] degree points."""
    lam0, phi0 = math.radians(p0[0]), math.radians(p0[1])
    lam1, phi1 = math.radians(p1[0]), math.radians(p1[1])
    dlam, dphi = lam1 - lam0, phi1 - phi0
    a = math.sin(dphi / 2) ** 2 + math.cos(phi0) * math.cos(phi1) * math.sin(dlam / 2) ** 2
    return R_EARTH * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ══════════════════════════════════════════════════════════════════════════════
#  Per-feature metrics extraction
# ══════════════════════════════════════════════════════════════════════════════

def _iter_polygon_parts(geom):
    """Yield list-of-rings for each polygon part (handles MultiPolygon correctly)."""
    from qgis.core import QgsWkbTypes
    if QgsWkbTypes.isMultiType(geom.wkbType()):
        for part in geom.asGeometryCollection():
            if part.isEmpty():
                continue
            _, rings = _extract_rings_from_geometry(part)
            if rings:
                yield rings
    else:
        _, rings = _extract_rings_from_geometry(geom)
        if rings:
            yield rings


def feature_metrics(feature):
    """Return dict of area + vertex-distance stats for a polygon feature.

    Keys: area_km2, min_dist_km, max_dist_km, zero_dist_edges,
          ring_count, vertex_count.
    Handles MultiPolygon by processing each part independently so that
    exterior/hole distinction is correct per part.
    """
    geom = feature.geometry()
    if geom.isEmpty():
        return None
    geom_type, _ = _extract_rings_from_geometry(geom)
    if geom_type != 2:
        return None

    total_area = 0.0
    min_dist = float('inf')
    dist_sum = 0.0
    dist_count = 0
    zero_dist_edges = 0
    total_verts = 0
    ring_count = 0

    for rings in _iter_polygon_parts(geom):
        for ri, ring in enumerate(rings):
            n = len(ring)
            if n < 4:               # closed ring: 3 unique vertices = 4 coords
                continue
            ring_count += 1
            total_verts += n
            area_sr = _ring_area_sr(ring)
            if ri == 0:             # exterior → add
                total_area += abs(area_sr)
            else:                   # hole → subtract
                total_area -= abs(area_sr)
            for i in range(n):
                d = _haversine_km(ring[i], ring[(i + 1) % n])
                dist_sum += d
                dist_count += 1
                if d < min_dist:
                    min_dist = d
                if d < 0.001:       # < 1 metre → effectively duplicate
                    zero_dist_edges += 1

    if min_dist == float('inf'):
        min_dist = 0.0
    mean_dist = dist_sum / dist_count if dist_count > 0 else 0.0

    return {
        'area_km2': total_area * R2,
        'min_dist_km': min_dist,
        'mean_dist_km': mean_dist,
        'zero_dist_edges': zero_dist_edges,
        'ring_count': ring_count,
        'vertex_count': total_verts,
    }


def collect_metrics(layer):
    """Return list of feature_metrics dicts for all features in layer, in order."""
    results = []
    for feat in layer.getFeatures():
        m = feature_metrics(feat)
        if m:
            results.append(m)
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  Comparison & reporting
# ══════════════════════════════════════════════════════════════════════════════

def compare_metrics(baseline, rotated, tol_area_pct=1.0, tol_meandist_pct=50.0):
    """Compare rotated metrics against baseline.

    Detection logic:
      - Total area should be preserved (rotation is area-preserving).
      - Mean edge distance change >50% suggests systematic vertex distortion.
        (Mean is robust: clipping adds legitimate long edges along ±180°,
        but anomalous edges will still shift the average noticeably.)
      - New zero-distance edges indicate duplicate vertices from clipping.
      - Vertex count should not balloon (>5×).
    Returns (issues_list, global_area_dict).
    """
    issues = []

    n_base = len(baseline)
    n_rot = len(rotated)
    total_area_base = sum(m['area_km2'] for m in baseline)
    total_area_rot = sum(m['area_km2'] for m in rotated)

    if n_base != n_rot:
        issues.append(('WARN',
            f"Feature count changed: {n_base} → {n_rot}  "
            f"({abs(n_base - n_rot)} difference)"))

    if total_area_base > 0:
        area_delta_pct = abs(total_area_rot - total_area_base) / total_area_base * 100
        if area_delta_pct > 0.01:
            level = 'ERROR' if area_delta_pct > 0.5 else 'WARN'
            issues.append((level,
                f"Total world area changed: {total_area_base:,.0f} → {total_area_rot:,.0f} km² "
                f"({area_delta_pct:.4f}%)"))

    n_cmp = min(n_base, n_rot)
    area_big = 0
    meandist_big = 0
    new_zero_edges = 0
    vert_balloon = 0

    for i in range(n_cmp):
        b, r = baseline[i], rotated[i]

        # Area
        if b['area_km2'] > 0:
            pct = abs(r['area_km2'] - b['area_km2']) / b['area_km2'] * 100
            if pct > tol_area_pct:
                area_big += 1
                if pct > 10:
                    issues.append(('ERROR',
                        f"Feature #{i}: area {pct:.2f}%  "
                        f"({b['area_km2']:,.0f} → {r['area_km2']:,.0f} km²)"))

        # Mean edge distance — rotation should preserve edge lengths
        if b['mean_dist_km'] > 0.1:
            meandist_pct = abs(r['mean_dist_km'] - b['mean_dist_km']) / b['mean_dist_km'] * 100
            if meandist_pct > tol_meandist_pct:
                meandist_big += 1
                if meandist_pct > 200:
                    issues.append(('ERROR',
                        f"Feature #{i}: mean-edge-dist {meandist_pct:.1f}%  "
                        f"({b['mean_dist_km']:.2f} → {r['mean_dist_km']:.2f} km)"))

        # New zero-distance edges (duplicate vertices)
        if b['zero_dist_edges'] == 0 and r['zero_dist_edges'] > 0:
            new_zero_edges += 1
            if r['zero_dist_edges'] >= 4:
                issues.append(('WARN',
                    f"Feature #{i}: gained {r['zero_dist_edges']} zero-length edges "
                    f"(was 0)"))

        # Vertex count balloon
        if b['vertex_count'] > 0:
            vratio = r['vertex_count'] / b['vertex_count']
            if vratio > 5:
                vert_balloon += 1
                if vratio > 20:
                    issues.append(('ERROR',
                        f"Feature #{i}: vertex count {vratio:.1f}×  "
                        f"({b['vertex_count']} → {r['vertex_count']})"))

    if area_big > 0:
        issues.append(('INFO', f"Features area change >{tol_area_pct}%: {area_big}"))
    if meandist_big > 0:
        issues.append(('INFO', f"Features mean-edge-dist change >{tol_meandist_pct}%: {meandist_big}"))
    if new_zero_edges > 0:
        issues.append(('INFO', f"Features with newly appearing zero-length edges: {new_zero_edges}"))
    if vert_balloon > 0:
        issues.append(('INFO', f"Features vertex count >5×: {vert_balloon}"))

    global_area = {
        'total_base': total_area_base,
        'total_rot': total_area_rot,
        'delta_pct': abs(total_area_rot - total_area_base) / total_area_base * 100 if total_area_base > 0 else 0,
    }
    return issues, global_area


# ══════════════════════════════════════════════════════════════════════════════
#  JPG rendering
# ══════════════════════════════════════════════════════════════════════════════

PADDING_DEG = 5


def _build_grid_layer():
    """10° graticule as a memory layer (EPSG:4326, LineString)."""
    uri = "LineString?crs=EPSG:4326"
    grid = QgsVectorLayer(uri, "grid", "memory")
    dp = grid.dataProvider()

    for lon in range(-180, 181, 10):
        ls = QgsLineString()
        for lat in range(-90, 91, 5):
            ls.addVertex(QgsPoint(lon, lat))
        f = QgsFeature()
        f.setGeometry(QgsGeometry(ls))
        dp.addFeature(f)

    for lat in range(-90, 91, 10):
        ls = QgsLineString()
        for lon in range(-180, 181, 5):
            ls.addVertex(QgsPoint(lon, lat))
        f = QgsFeature()
        f.setGeometry(QgsGeometry(ls))
        dp.addFeature(f)

    grid.updateExtents()
    return grid


def render_map_jpg(layer, out_path, width=2400, height=1200):
    """Render polygon layer (black fill, dark outline) + 10° graticule + margin."""
    ms = QgsMapSettings()
    ms.setDestinationCrs(layer.crs())
    ms.setExtent(QgsRectangle(-180 - PADDING_DEG, -90 - PADDING_DEG,
                               180 + PADDING_DEG,  90 + PADDING_DEG))
    ms.setOutputSize(QSize(width, height))
    ms.setBackgroundColor(QColor(255, 255, 255))

    grid = _build_grid_layer()
    grid_sym = QgsLineSymbol.createSimple({
        'line_color': '180,180,180',
        'line_width': '0.4',
    })
    grid.renderer().setSymbol(grid_sym)

    poly_sym = QgsFillSymbol.createSimple({
        'color': '0,0,0',
        'outline_color': '50,50,50',
        'outline_width': '0.3',
        'outline_style': 'solid',
    })
    layer.renderer().setSymbol(poly_sym)

    ms.setLayers([grid, layer])

    img = QImage(QSize(width, height), QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    job = QgsMapRendererCustomPainterJob(ms, painter)
    job.start()
    job.waitForFinished()
    painter.end()

    img.save(out_path, "JPG", 90)


# ══════════════════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════════════════

INPUT = r"test_data\ne_110m_land.shp"
BASE = os.path.dirname(os.path.abspath(__file__))
CHECK_DIR = os.path.join(BASE, "check")
SHP_DIR = os.path.join(CHECK_DIR, "shp")
JPG_DIR = os.path.join(CHECK_DIR, "jpg")
REPORT_PATH = os.path.join(CHECK_DIR, "comparison_report.txt")

# ── Full-grid parameter space ──
LAMBDA_STEP = 90   # degrees
PHI_STEP = 90      # degrees
GAMMA_STEP = 90    # degrees

ROTATION_COMBOS = [
    [lam, phi, gam]
    for lam in range(-180, 181, LAMBDA_STEP)
    for phi in range(-90, 91, PHI_STEP)
    for gam in range(-90, 91, GAMMA_STEP)
]


def _tag(rot):
    """Sortable rotation tag, e.g. [15,-30,0] → 'lam+15_phi-30_gam+0'."""
    names = ['lam', 'phi', 'gam']
    return "_".join(f"{n}{v:+d}" for n, v in zip(names, rot))


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    os.makedirs(SHP_DIR, exist_ok=True)
    os.makedirs(JPG_DIR, exist_ok=True)

    # ── Combo count ──
    print(f"Total combos: {len(ROTATION_COMBOS)}  "
          f"(lam step={LAMBDA_STEP}°, phi step={PHI_STEP}°, gam step={GAMMA_STEP}°)")
    print()

    # ── Baseline ──
    print("=" * 60)
    print("Computing baseline from INPUT ...")
    base_layer = QgsVectorLayer(INPUT, "baseline", "ogr")
    if not base_layer.isValid():
        print(f"ERROR: cannot open INPUT: {INPUT}")
        return
    baseline = collect_metrics(base_layer)
    n_base = len(baseline)
    total_area_base = sum(m['area_km2'] for m in baseline)
    print(f"  {n_base} features, total land area = {total_area_base:,.0f} km²")
    print()

    # ── Report buffer ──
    report_lines = []
    report_lines.append(f"Comparison report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Input: {INPUT}")
    report_lines.append(f"Baseline: {n_base} features, total area = {total_area_base:,.0f} km²")
    report_lines.append("=" * 70)
    report_lines.append("")

    n_ok = 0
    n_warn = 0
    n_err = 0

    for idx, rot in enumerate(ROTATION_COMBOS):
        tag = _tag(rot)
        label = f"{idx:02d}_{tag}"
        print(f"[{label}]  {rot}", end="")

        # --- SHP ---
        shp = os.path.join(SHP_DIR, f"land_{label}.shp")
        result = process_file(INPUT, rotation=rot, output_path=shp)
        if not result.isValid():
            print("  ERROR: invalid output")
            report_lines.append(f"[{label}] {rot}  ERROR: invalid output layer")
            report_lines.append("")
            n_err += 1
            continue

        # --- metrics ---
        rotated = collect_metrics(result)
        issues, ga = compare_metrics(baseline, rotated)

        # --- print summary ---
        n_feat = result.featureCount()
        tag_level = "OK"
        for lvl, _ in issues:
            if lvl == 'ERROR':
                tag_level = 'ERR'
                break
            if lvl == 'WARN':
                tag_level = 'WRN'

        print(f"  [{tag_level}]  features={n_feat}  area={ga['total_rot']:,.0f} km²  Δ={ga['delta_pct']:.4f}%")

        if tag_level == 'ERR':
            n_err += 1
        elif tag_level == 'WRN':
            n_warn += 1
        else:
            n_ok += 1

        # --- report section ---
        report_lines.append(f"[{label}]  {rot}  —  {tag_level}")
        report_lines.append(f"  Features: {n_base} → {n_feat}")
        report_lines.append(f"  Total area: {ga['total_base']:,.0f} → {ga['total_rot']:,.0f} km²  "
                           f"({ga['delta_pct']:.4f}%)")
        if issues:
            for lvl, msg in issues:
                report_lines.append(f"  [{lvl}] {msg}")
        report_lines.append("")

        # --- detailed per-feature (any metric with notable delta) ---
        n_cmp = min(len(baseline), len(rotated))
        detail = []
        for i in range(n_cmp):
            b, r = baseline[i], rotated[i]
            b_area, r_area = b['area_km2'], r['area_km2']
            parts = [f"#{i}:"]
            added = False

            if b_area > 0:
                pct = abs(r_area - b_area) / b_area * 100
                if pct > 0.01:
                    parts.append(f"area {b_area:,.0f}→{r_area:,.0f} km² ({pct:.2f}%)")
                    added = True

            if b['mean_dist_km'] > 0.1:
                mpct = abs(r['mean_dist_km'] - b['mean_dist_km']) / b['mean_dist_km'] * 100
                if mpct > 10:
                    parts.append(f"mean-edge {b['mean_dist_km']:.2f}→{r['mean_dist_km']:.2f} km ({mpct:.1f}%)")
                    added = True

            if b['zero_dist_edges'] == 0 and r['zero_dist_edges'] > 0:
                parts.append(f"zero-edges 0→{r['zero_dist_edges']}")
                added = True

            vratio = r['vertex_count'] / b['vertex_count'] if b['vertex_count'] > 0 else 1
            if vratio > 2 or vratio < 0.5:
                parts.append(f"verts {b['vertex_count']}→{r['vertex_count']} ({vratio:.1f}×)")
                added = True

            if added:
                detail.append("    " + "  ".join(parts))

        if detail:
            report_lines.append(f"  Per-feature deltas ({len(detail)} features):")
            report_lines.extend(detail)
            report_lines.append("")

        # --- JPG ---
        jpg = os.path.join(JPG_DIR, f"land_{label}.jpg")
        try:
            render_map_jpg(result, jpg)
            print(f"         jpg OK")
        except Exception as e:
            print(f"         jpg ERROR: {e}")

    # ── Write report ──
    report_lines.append("=" * 70)
    report_lines.append(f"Summary:  OK={n_ok}  WARN={n_warn}  ERROR={n_err}  total={n_ok + n_warn + n_err}")
    report = "\n".join(report_lines)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\nReport written to: {REPORT_PATH}")
    print(f"Summary: OK={n_ok}  WARN={n_warn}  ERROR={n_err}")


if __name__ == "__main__":
    main()
