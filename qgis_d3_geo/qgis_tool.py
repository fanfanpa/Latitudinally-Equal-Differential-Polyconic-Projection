"""
QGIS processing tool for spherical rotation and antimeridian clipping.
"""
import os
import math


def _coerce_to_layer(source):
    try:
        from qgis.core import QgsVectorLayer
        if isinstance(source, QgsVectorLayer):
            return source
        if isinstance(source, str) and os.path.exists(source):
            layer = QgsVectorLayer(source, "input", "ogr")
            if not layer.isValid():
                raise ValueError(f"Cannot open: {source}")
            return layer
        raise ValueError(f"Unsupported source type: {type(source)}")
    except ImportError:
        raise ImportError("QGIS (qgis.core) is required. Run this inside QGIS.")


def _extract_rings_from_geometry(geom):
    from qgis.core import QgsWkbTypes

    geom_type = geom.type()
    wkb_type = geom.wkbType()

    if QgsWkbTypes.isMultiType(wkb_type):
        parts = geom.asGeometryCollection()
        if not parts:
            return geom_type, []
        results = [_extract_rings_from_geometry(g) for g in parts]
        if geom_type == 2:
            all_rings = []
            for _, rings in results:
                all_rings.extend(rings)
            return geom_type, all_rings
        elif geom_type == 1:
            all_lines = []
            for _, lines in results:
                all_lines.append(lines)
            return geom_type, all_lines
        elif geom_type == 0:
            all_pts = [coords for _, coords in results]
            return geom_type, all_pts
        return geom_type, results

    if geom_type == 2:
        rings = []
        if geom.isEmpty():
            return geom_type, rings
        try:
            outer = geom.constGet()
            if outer:
                outer_ring = outer.exteriorRing()
                if outer_ring:
                    rings.append(_ring_to_coords(outer_ring))
                for i in range(outer.numInteriorRings()):
                    rings.append(_ring_to_coords(outer.interiorRing(i)))
        except AttributeError:
            outer = geom.asPolygon()
            if outer:
                for ring in outer:
                    rings.append([[p.x(), p.y()] for p in ring])
        return geom_type, rings

    elif geom_type == 1:
        try:
            curve = geom.constGet()
            coords = [[curve.xAt(i), curve.yAt(i)] for i in range(len(curve))]
        except AttributeError:
            pts = geom.asPolyline()
            coords = [[p.x(), p.y()] for p in pts]
        return geom_type, coords

    elif geom_type == 0:
        try:
            pt = geom.constGet()
            return geom_type, [pt.x(), pt.y()]
        except AttributeError:
            pt = geom.asPoint()
            return geom_type, [pt.x(), pt.y()]

    return geom_type, []


def _ring_to_coords(qgs_ring):
    coords = []
    for v in qgs_ring.vertices():
        coords.append([v.x(), v.y()])
    return coords


def _make_line_string(coords):
    from qgis.core import QgsLineString, QgsPoint
    ls = QgsLineString()
    for pt in coords:
        ls.addVertex(QgsPoint(pt[0], pt[1]))
    return ls


def _build_polygon_geometry(rings):
    from qgis.core import QgsGeometry, QgsPolygon
    if not rings:
        return QgsGeometry()
    try:
        exterior = _make_line_string(rings[0])
        polygon = QgsPolygon()
        polygon.setExteriorRing(exterior)
        for ring in rings[1:]:
            polygon.addInteriorRing(_make_line_string(ring))
        return QgsGeometry(polygon)
    except Exception:
        from qgis.core import QgsPoint
        qgs_rings = []
        for ring_coords in rings:
            qgs_ring = [QgsPoint(pt[0], pt[1]) for pt in ring_coords]
            qgs_rings.append(qgs_ring)
        return QgsGeometry.fromPolygonXY(qgs_rings)


def _build_line_geometry(segments):
    from qgis.core import QgsGeometry, QgsLineString, QgsPoint, QgsMultiLineString
    if not segments:
        return QgsGeometry()
    if isinstance(segments[0], list) and isinstance(segments[0][0], list):
        if len(segments) == 1:
            ls = QgsLineString()
            for pt in segments[0]:
                ls.addVertex(QgsPoint(pt[0], pt[1]))
            return QgsGeometry(ls)
        else:
            mls = QgsMultiLineString()
            for seg in segments:
                ls = QgsLineString()
                for pt in seg:
                    ls.addVertex(QgsPoint(pt[0], pt[1]))
                mls.addGeometry(ls)
            return QgsGeometry(mls)
    else:
        ls = QgsLineString()
        for pt in segments:
            ls.addVertex(QgsPoint(pt[0], pt[1]))
        return QgsGeometry(ls)


def _clip_line_coords(coords, rotation_fn=None):
    from .d3_geo import _clip_antimeridian_line

    if rotation_fn:
        coords = [rotation_fn(pt) for pt in coords]

    segments = []
    _cur = [[]]

    class LineSink:
        @staticmethod
        def point(x, y):
            _cur[0].append([x, y])

        @staticmethod
        def line_start():
            _cur[0] = []

        @staticmethod
        def line_end():
            if len(_cur[0]) >= 2:
                segments.append(list(_cur[0]))
            _cur[0] = []

    clipper = _clip_antimeridian_line(LineSink)
    if len(coords) >= 2:
        clipper.line_start()
        for pt in coords:
            clipper.point(pt[0], pt[1])
        clipper.line_end()

    return segments


def _clip_polygon_rings(rings, rotation_fn=None):
    from .d3_geo import antimeridian_clip
    if rotation_fn:
        rings = [[rotation_fn(pt) for pt in ring] for ring in rings]
    return antimeridian_clip(rings)


def _process_feature(feature, rotation):
    from qgis.core import QgsGeometry, QgsWkbTypes

    geom = feature.geometry()
    if geom.isEmpty():
        return None
    
    if rotation is None:
        return geom
    
    geom_type, coords = _extract_rings_from_geometry(geom)
    rot_fn = rotation if rotation else None

    if geom_type == 0:
        if isinstance(coords, list) and isinstance(coords[0], (int, float)):
            new_coord = [coords[0], coords[1]]
            if rot_fn:
                new_coord = rot_fn(new_coord)
            from qgis.core import QgsPoint
            return QgsGeometry(QgsPoint(new_coord[0], new_coord[1]))
        else:
            from qgis.core import QgsMultiPoint, QgsPoint
            mp = QgsMultiPoint()
            for pt in coords:
                new_pt = [pt[0], pt[1]]
                if rot_fn:
                    new_pt = rot_fn(new_pt)
                mp.addGeometry(QgsGeometry(QgsPoint(new_pt[0], new_pt[1])))
            return QgsGeometry(mp)

    elif geom_type == 1:
        if isinstance(coords, list) and coords and isinstance(coords[0], list) \
                and coords[0] and isinstance(coords[0][0], list):
            all_segments = []
            for line_coords in coords:
                all_segments.extend(_clip_line_coords(line_coords, rot_fn))
            return _build_line_geometry(all_segments)
        else:
            segments = _clip_line_coords(coords, rot_fn)
            return _build_line_geometry(segments)

    elif geom_type == 2:
        is_multi = QgsWkbTypes.isMultiType(geom.wkbType())
        if is_multi:
            return _process_multipolygon(geom, rot_fn)
        else:
            clipped = _clip_polygon_rings(coords, rot_fn)
            return _build_polygon_geometry(clipped)

    return None


def _process_multipolygon(geom, rot_fn):
    from qgis.core import QgsGeometry, QgsMultiPolygon

    parts = geom.asGeometryCollection()
    result_polygons = []

    for part in parts:
        if part.isEmpty():
            continue
        _, rings = _extract_rings_from_geometry(part)
        if rings:
            clipped = _clip_polygon_rings(rings, rot_fn)
            poly_geom = _build_polygon_geometry(clipped)
            if poly_geom and not poly_geom.isEmpty():
                result_polygons.append(poly_geom)

    if not result_polygons:
        return QgsGeometry()
    if len(result_polygons) == 1:
        return result_polygons[0]

    mp = QgsMultiPolygon()
    for pg in result_polygons:
        mp.addGeometry(pg)
    return QgsGeometry(mp)


def process_layer(input_layer, rotation=None, output_path=None,
                  output_layer_name="rotated_clipped"):
    from qgis.core import (
        QgsVectorLayer, QgsFeature, QgsWkbTypes,
        QgsVectorFileWriter, QgsCoordinateTransformContext
    )
    from qgis.PyQt.QtCore import QVariant

    try:
        layer = _coerce_to_layer(input_layer)
    except ImportError:
        raise

    rot_fn = None
    if rotation and any(a != 0 for a in rotation):
        from .d3_geo import rotate
        rot = rotate(rotation)
        rot_fn = rot

    wkb_type = layer.wkbType()
    if QgsWkbTypes.isMultiType(wkb_type):
        out_wkb_type = QgsWkbTypes.multiType(wkb_type)
    else:
        out_wkb_type = wkb_type

    crs = layer.crs()
    fields = layer.fields()

    def _wkb_type_to_uri(wkb_type, crs):
        from qgis.core import QgsWkbTypes
        geom_name = QgsWkbTypes.displayString(wkb_type)
        crs_authid = crs.authid() if crs.isValid() else "EPSG:4326"
        return f"{geom_name}?crs={crs_authid}"

    uri = _wkb_type_to_uri(out_wkb_type, crs)
    mem_layer = QgsVectorLayer(uri, output_layer_name, "memory")
    mem_layer.startEditing()
    mem_data = mem_layer.dataProvider()
    mem_data.addAttributes(fields)
    mem_layer.updateFields()

    features = []
    for feature in layer.getFeatures():
        new_geom = _process_feature(feature, rot_fn)
        if new_geom is None or new_geom.isEmpty():
            continue
        new_feat = QgsFeature()
        new_feat.setGeometry(new_geom)
        new_feat.setAttributes(feature.attributes())
        features.append(new_feat)

    mem_data.addFeatures(features)
    mem_layer.commitChanges()

    if output_path:
        def _guess_format(path):
            ext = os.path.splitext(path)[1].lower()
            mapping = {
                '.shp': 'ESRI Shapefile', '.geojson': 'GeoJSON',
                '.json': 'GeoJSON', '.gpkg': 'GPKG', '.sqlite': 'SQLite',
                '.gml': 'GML', '.kml': 'KML', '.kmz': 'KML',
                '.tab': 'MapInfo File', '.mif': 'MapInfo File',
                '.dxf': 'DXF', '.csv': 'CSV',
            }
            return mapping.get(ext, 'ESRI Shapefile')

        fmt = _guess_format(output_path)
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = fmt
        save_options.fileEncoding = "UTF-8"
        save_options.layerName = output_layer_name

        err = QgsVectorFileWriter.writeAsVectorFormatV3(
            mem_layer, output_path,
            QgsCoordinateTransformContext(),
            save_options
        )
        if err[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Write error: {err}")
        result_layer = QgsVectorLayer(output_path, output_layer_name, "ogr")
        return result_layer
    else:
        return mem_layer


def process_file(input_path, rotation=None, output_path=None,
                 output_layer_name="rotated_clipped"):
    layer = _coerce_to_layer(input_path)
    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_rotated{ext}"
    return process_layer(layer, rotation=rotation, output_path=output_path,
                         output_layer_name=output_layer_name)
