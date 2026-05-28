"""
***************************************************************************
*                                                                         *
*   自定义等差分纬线多圆锥投影工具                                          *
*   Custom Polyconic Projection Tool                                      *
*                                                                         *
*   流程：旋转+反子午线裁剪 → 修正几何 → 增密 → 投影                         *
*                                                                         *
***************************************************************************
"""

import math
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from typing import Any, Optional

from qgis.core import (
    QgsPointXY,
    QgsGeometry,
    QgsFeature,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
)
from qgis import processing

from qgis_d3_geo.qgis_tool import process_layer


# ============================================================
# 投影公式
# ============================================================

# ---------- 1963年方案：样条函数 ----------

def ynSpline(phi):
    sgn = 1.0 if phi >= 0 else -1.0
    abs_phi = abs(phi)
    if abs_phi < 0.17453292519943295:
        return 1.5271229924920866 * phi - 1.0100872528750704 * phi**3
    elif abs_phi < 0.26179938779914946:
        return (-sgn * 0.030891469712581106 + 2.0581082437382188 * phi
                - sgn * 3.0423213880097015 * phi**2 + 4.80031859563621 * phi**3)
    elif abs_phi < 0.3490658503988659:
        return (sgn * 0.1709495921326784 - 0.25481995149626163 * phi
                + sgn * 5.792413538906713 * phi**2 - 6.448415280566685 * phi**3)
    elif abs_phi < 0.41015237421866746:
        return (-sgn * 0.28946654896159746 + 3.702165304164013 * phi
                - sgn * 5.543514198334726 * phi**2 + 4.376598322920309 * phi**3)
    elif abs_phi < 0.5235987755982989:
        return (sgn * 0.05307970360138684 + 1.1966604667323502 * phi
                + sgn * 0.5652029393012619 * phi**2 - 0.5879933114879028 * phi**3)
    elif abs_phi < 0.6981317007977318:
        return (-sgn * 0.040699882295465985 + 1.7339779143697747 * phi
                - sgn * 0.4609977943109389 * phi**2 + 0.06530636594774145 * phi**3)
    elif abs_phi < 0.7853981633974483:
        return (-sgn * 0.04647955512903578 + 1.758814228894522 * phi
                - sgn * 0.49657319433412633 * phi**2 + 0.08229236824622688 * phi**3)
    elif abs_phi < 0.8726646259971648:
        return (sgn * 0.1627992073626043 + 0.95942824006174 * phi
                + sgn * 0.5212366581549931 * phi**2 - 0.3496795494905096 * phi**3)
    elif abs_phi < 1.0471975511965979:
        return (-sgn * 0.4934162518439651 + 3.21533081588828 * phi
                - sgn * 2.063837273596045 * phi**2 + 0.637745957300319 * phi**3)
    elif abs_phi < 1.160643952576229:
        return (sgn * 2.6323996710067004 - 5.739472179818403 * phi
                + sgn * 6.487369693488941 * phi**2 - 2.0841877591265408 * phi**3)
    elif abs_phi < 1.2217304763960306:
        return (-sgn * 0.06331771971040438 + 1.228342673479739 * phi
                + sgn * 0.4839654299919428 * phi**2 - 0.36002872649885964 * phi**3)
    elif abs_phi < 1.3089969389957472:
        return (-sgn * 3.0290030290957928 + 8.510682027411134 * phi
                - sgn * 5.4767104266122795 * phi**2 + 1.2662644622104196 * phi**3)
    elif abs_phi < 1.3962634015954636:
        return (-sgn * 2.455207302687121 + 7.195639090376726 * phi
                - sgn * 4.472091624338152 * phi**2 + 1.0104403849224404 * phi**3)
    else:
        return (-sgn * 0.9501716941205609 + 3.9619320258354533 * phi
                - sgn * 2.156119537089983 * phi**2 + 0.45754277629984 * phi**3)


def xnSpline(phi):
    abs_phi = abs(phi)
    if abs_phi < 0.17453292519943295:
        return (2.589813150474736 - 0.8852514776808 * abs_phi**2 + 0.2156744452624301 * abs_phi**3)
    elif abs_phi < 0.26179938779914946:
        return (2.5888006039905727 + 0.01740439203101801 * abs_phi
                - 0.9849712985176455 * abs_phi**2 + 0.4061252741874958 * abs_phi**3)
    elif abs_phi < 0.3490658503988659:
        return (2.586566421877108 + 0.043006233184045874 * abs_phi
                - 1.082763128239835 * abs_phi**2 + 0.5306376989417948 * abs_phi**3)
    elif abs_phi < 0.41015237421866746:
        return (2.591710444836326 - 0.0012033876081931026 * abs_phi
                - 0.9561118939763797 * abs_phi**2 + 0.4096946790514837 * abs_phi**3)
    elif abs_phi < 0.5235987755982989:
        return (2.59129428902019 + 0.0018405236962004488 * abs_phi
                - 0.9635333097616526 * abs_phi**2 + 0.41572610887429085 * abs_phi**3)
    elif abs_phi < 0.6981317007977318:
        return (2.6488583874553955 - 0.3279774654850895 * abs_phi
                - 0.333627350175674 * abs_phi**2 + 0.014715520269682264 * abs_phi**3)
    elif abs_phi < 0.7853981633974483:
        return (2.7684001717397826 - 0.8416704441069918 * abs_phi
                + 0.40218364083780167 * abs_phi**2 - 0.33660834893374025 * abs_phi**3)
    elif abs_phi < 0.8726646259971648:
        return (3.0046791444742453 - 1.74418963913175 * abs_phi
                + 1.5513067698258702 * abs_phi**2 - 0.8243113521328783 * abs_phi**3)
    elif abs_phi < 1.0471975511965979:
        return (2.4264910216094973 + 0.24347471315274363 * abs_phi
                - 0.7263887996642484 * abs_phi**2 + 0.04570426884999046 * abs_phi**3)
    elif abs_phi < 1.160643952576229:
        return (0.32726032286130863 + 6.257327676281242 * abs_phi
                - 6.469195356322702 * abs_phi**2 + 1.8736963702754696 * abs_phi**3)
    elif abs_phi < 1.2217304763960306:
        return (5.713126712541212 - 7.663909007178327 * abs_phi
                + 5.525212232676679 * abs_phi**2 - 1.5710601966665094 * abs_phi**3)
    elif abs_phi < 1.3089969389957472:
        return (-2.20484561744157 + 11.778936570366538 * abs_phi
                - 10.388973342594724 * abs_phi**2 + 2.77091918593635 * abs_phi**3)
    elif abs_phi < 1.3962634015954636:
        return (16.061152339503188 - 30.08364709073422 * abs_phi
                + 21.59168483466383 * abs_phi**2 - 5.3728885456523585 * abs_phi**3)
    else:
        return (-3.317160382002574 + 11.55243539777649 * abs_phi
                - 8.22796269096389 * abs_phi**2 + 1.7460279117901278 * abs_phi**3)


# ---------- 1963年方案投影 ----------

Y_MAX_1963 = 1.62070986487959


def project_1963(lon_deg, lat_deg, clip_y=True):
    lam = math.radians(lon_deg)
    phi = math.radians(lat_deg)
    b = 1.1
    C = 0.028937262380344605
    lambdaN = math.pi
    y0 = 0.9953537 * phi + 0.01476138 * phi**3
    yn = ynSpline(phi)
    xn = xnSpline(phi)

    if phi == 0.0:
        x = xn * b * (1 - C * abs(lam)) * lam / lambdaN
        y = 0.0
    else:
        dy = yn - y0
        rho = (xn**2 + dy**2) / (2 * dy)
        deltaPhiN = math.asin(xn / rho)
        deltaPhi = deltaPhiN * b * (1 - C * abs(lam)) * lam / lambdaN
        y = y0 + rho * (1 - math.cos(deltaPhi))
        x = rho * math.sin(deltaPhi)

    if clip_y and abs(y) > Y_MAX_1963:
        y = math.copysign(Y_MAX_1963, y)
    return x, y


# ---------- 郝晓光广义等差分纬线多圆锥投影 ----------

Y_MAX_HAO = 1.6262809761582284


def project_haoxiaoguang(lon_deg, lat_deg, angle_deg=0, clip_y=True):
    lam = math.radians(lon_deg)
    phi = math.radians(lat_deg)
    b = 1.1
    C = 0.028937262380344605
    lambdaN = math.pi

    y0 = 0.9953510305742277 * phi + 0.014761224628025876 * phi**3
    yn = (1.501487749065408 * phi
          - 0.23845050808110835 * phi**3
          + 0.03725714354686819 * phi**5)
    xn_sq = 6.5736602244998785 - 1.625 * yn**2
    if xn_sq < 0:
        xn_sq = 0.0
    xn = math.sqrt(xn_sq) + 0.025898131504747363

    if phi == 0.0:
        x = xn * b * (1 - C * abs(lam)) * lam / lambdaN
        y = 0.0
    else:
        dy = yn - y0
        rho = (xn**2 + dy**2) / (2 * dy)
        deltaPhiN = math.asin(xn / rho)
        deltaPhi = deltaPhiN * b * (1 - C * abs(lam)) * lam / lambdaN
        y = y0 + rho * (1 - math.cos(deltaPhi))
        x = rho * math.sin(deltaPhi)

    if clip_y and abs(y) > Y_MAX_HAO:
        y = math.copysign(Y_MAX_HAO, y)

    if angle_deg:
        a = math.radians(angle_deg)
        cos_a = math.cos(a)
        sin_a = math.sin(a)
        x, y = x * cos_a - y * sin_a, x * sin_a + y * cos_a

    return x, y


# ============================================================
# 几何变换工具函数
# ============================================================

def transform_geometry(geom, point_transform):
    def transform_line(line):
        return [point_transform(pt) for pt in line]

    if geom.isMultipart():
        parts = geom.asGeometryCollection()
        new_parts = [transform_geometry(part, point_transform) for part in parts]
        return QgsGeometry.collectGeometry(new_parts)
    else:
        geom_type = geom.type()
        if geom_type == QgsWkbTypes.PointGeometry:
            return QgsGeometry.fromPointXY(point_transform(geom.asPoint()))
        elif geom_type == QgsWkbTypes.LineGeometry:
            return QgsGeometry.fromPolylineXY(transform_line(geom.asPolyline()))
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            rings = geom.asPolygon()
            new_rings = [transform_line(ring) for ring in rings]
            return QgsGeometry.fromPolygonXY(new_rings)


# ============================================================
# 投影方案预设表
# ============================================================

# (显示名称, 投影函数标识, λ, φ, γ, 平面旋转角度)
PRESETS = [
    ("等差分纬线多圆锥投影（1963年方案）", "1963", -150.0, 0.0, 0.0, 0.0),
    ("郝晓光 广义等差分纬线多圆锥投影 — 东", "hao", -150.0, 0.0, 0.0, 0.0),
    ("郝晓光 广义等差分纬线多圆锥投影 — 西", "hao", 0.0, 0.0, 0.0, 0.0),
    ("郝晓光 广义等差分纬线多圆锥投影 — 南", "hao", 105.0, 165.0, 90.0, 90.0),
    ("郝晓光 广义等差分纬线多圆锥投影 — 北", "hao", -150.0, -120.0, 90.0, 90.0),
]


# ============================================================
# QGIS Processing 算法
# ============================================================

class CustomProjectionAlgorithm(QgsProcessingAlgorithm):

    INPUT = "INPUT"
    PROJECTION_TYPE = "PROJECTION_TYPE"
    DENSIFY_INTERVAL = "DENSIFY_INTERVAL"
    CLIP_Y = "CLIP_Y"
    OUTPUT_EXTENT = "OUTPUT_EXTENT"
    OUTPUT_ROTATION = "OUTPUT_ROTATION"
    OUTPUT_PROJECTION = "OUTPUT_PROJECTION"
    OUTPUT_EXTENT_SINK = "OUTPUT_EXTENT_SINK"

    def name(self):
        return "custompolyconicprojection"

    def displayName(self):
        return "自定义等差分纬线多圆锥投影"

    def group(self):
        return "自定义投影工具"

    def groupId(self):
        return "customprojections"

    def shortHelpString(self):
        return (
            "将矢量图层转换为等差分纬线多圆锥投影。\n\n"
            "投影方案预设：\n"
            "  - 等差分纬线多圆锥投影（1963年方案）: λ=-150°, φ=0°, γ=0°\n"
            "  - 郝晓光 东: λ=-150°, φ=0°, γ=0°, 平面旋转=0°\n"
            "  - 郝晓光 西: λ=0°, φ=0°, γ=0°, 平面旋转=0°\n"
            "  - 郝晓光 南: λ=105°, φ=165°, γ=90°, 平面旋转=90°\n"
            "  - 郝晓光 北: λ=-150°, φ=-120°, γ=90°, 平面旋转=90°\n\n"
            "流程：旋转+反子午线裁剪 → 修正几何 → 增密 → 投影\n"
            "Extent 图层：全球矩形框 [-180/180, -90/90] 不经旋转、直接修正+增密+投影"
        )

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT, "输入矢量图层",
                [QgsProcessing.TypeVectorAnyGeometry],
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PROJECTION_TYPE, "投影方案",
                options=[p[0] for p in PRESETS],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DENSIFY_INTERVAL, "增密间隔（度）",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.1, minValue=0.001, maxValue=10.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CLIP_Y, "裁剪 Y 轴（极区裁切）",
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_ROTATION, "输出旋转裁剪图层",
                createByDefault=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_PROJECTION, "输出投影图层",
                createByDefault=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OUTPUT_EXTENT, "输出 Extent 图层",
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_EXTENT_SINK, "Extent 图层",
                createByDefault=False,
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:

        source_layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        if source_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        preset_idx = self.parameterAsEnum(parameters, self.PROJECTION_TYPE, context)
        densify_interval = self.parameterAsDouble(parameters, self.DENSIFY_INTERVAL, context)
        clip_y = self.parameterAsBool(parameters, self.CLIP_Y, context)
        output_extent = self.parameterAsBool(parameters, self.OUTPUT_EXTENT, context)

        preset_name, proj_id, rot_lam, rot_phi, rot_gam, plane_angle = PRESETS[preset_idx]

        layer_name = source_layer.name()
        in_count = source_layer.featureCount()

        # 输出 sink
        (sink_rot, dest_rot) = self.parameterAsSink(
            parameters, self.OUTPUT_ROTATION, context,
            source_layer.fields(), source_layer.wkbType(), source_layer.sourceCrs(),
        )
        (sink_proj, dest_proj) = self.parameterAsSink(
            parameters, self.OUTPUT_PROJECTION, context,
            source_layer.fields(), source_layer.wkbType(), source_layer.sourceCrs(),
        )
        if sink_proj is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_PROJECTION))

        sink_ext = None
        dest_ext = None
        if output_extent:
            (sink_ext, dest_ext) = self.parameterAsSink(
                parameters, self.OUTPUT_EXTENT_SINK, context,
                source_layer.fields(), QgsWkbTypes.Polygon, source_layer.sourceCrs(),
            )

        # 选择投影函数
        if proj_id == "1963":
            def proj_fn(lon, lat):
                return project_1963(lon, lat, clip_y)
        else:
            def proj_fn(lon, lat):
                return project_haoxiaoguang(lon, lat, plane_angle, clip_y)

        # 日志
        total_steps = 4 + (1 if output_extent else 0)
        feedback.pushInfo(f"投影方案：{preset_name}")
        feedback.pushInfo(f"球面旋转：λ={rot_lam}°, φ={rot_phi}°, γ={rot_gam}°")
        if proj_id == "hao":
            feedback.pushInfo(f"平面旋转：{plane_angle}°")
        feedback.pushInfo(f"增密间隔：{densify_interval}°")
        feedback.pushInfo(f"Y轴裁切：{'启用' if clip_y else '禁用'}")
        feedback.pushInfo(f"Extent 图层：{'是' if output_extent else '否'}")
        feedback.pushInfo(f"输入要素数：{in_count}，共 {total_steps} 个处理步骤")

        def register_layer(layer, display_name, sink, dest_id, progress_pct):
            """写入 sink 并注册到 context 以控制图层名"""
            for f in layer.getFeatures():
                sink.addFeature(f)
            # 注册到 context，让框架在完成时以指定名称加载
            details = QgsProcessingContext.LayerDetails(
                display_name, context.project(), display_name
            )
            context.addLayerToLoadOnCompletion(dest_id, details)
            feedback.setProgress(progress_pct)
            feedback.pushInfo(f"已输出：{display_name} ({layer.featureCount()} 要素)")

        working_layer = source_layer
        step = 0

        # --- Step 1: 球面旋转 + 反子午线裁剪 ---
        step += 1
        feedback.pushInfo(
            f"--- [{step}/{total_steps}] 球面旋转 + 反子午线裁剪 "
            f"(λ={rot_lam}°, φ={rot_phi}°, γ={rot_gam}°) ---"
        )
        if feedback.isCanceled():
            return {}

        working_layer = process_layer(
            working_layer,
            rotation=[rot_lam, rot_phi, rot_gam],
            output_layer_name=f"{layer_name}_rotation",
        )
        feedback.pushInfo(f"旋转裁剪完成，要素数：{working_layer.featureCount()}")

        if sink_rot is not None:
            register_layer(working_layer, f"{layer_name}_rotation",
                          sink_rot, dest_rot, 20)

        # --- Step 2: 修正图形几何 ---
        step += 1
        feedback.pushInfo(f"--- [{step}/{total_steps}] 修正图形几何 ---")
        if feedback.isCanceled():
            return {}

        fix_result = processing.run(
            "native:fixgeometries",
            {"INPUT": working_layer, "METHOD": 1, "OUTPUT": "TEMPORARY_OUTPUT"},
            context=context, feedback=feedback,
        )
        working_layer = fix_result["OUTPUT"]
        feedback.pushInfo(f"修正完成，要素数：{working_layer.featureCount()}")

        # --- Step 3: 按间隔增密 ---
        step += 1
        feedback.pushInfo(f"--- [{step}/{total_steps}] 几何增密（间隔={densify_interval}°）---")
        if feedback.isCanceled():
            return {}

        densify_result = processing.run(
            "native:densifygeometriesgivenaninterval",
            {"INPUT": working_layer, "INTERVAL": densify_interval, "OUTPUT": "TEMPORARY_OUTPUT"},
            context=context, feedback=feedback,
        )
        working_layer = densify_result["OUTPUT"]
        feedback.pushInfo(f"增密完成，要素数：{working_layer.featureCount()}")

        # --- Step 4: 投影 ---
        step += 1
        feedback.pushInfo(f"--- [{step}/{total_steps}] 投影变换 ---")
        if feedback.isCanceled():
            return {}

        projected_layer = self._transform_layer(
            working_layer, proj_fn,
            layer_name=f"{layer_name}_rotation_project",
            feedback=feedback,
        )
        feedback.pushInfo(f"投影完成，要素数：{projected_layer.featureCount()}")
        register_layer(projected_layer, f"{layer_name}_rotation_project",
                      sink_proj, dest_proj, 90)

        # --- Step 5 (可选): Extent 图层 ---
        if output_extent:
            step += 1
            feedback.pushInfo(f"--- [{step}/{total_steps}] 生成 Extent 图层 ---")
            if feedback.isCanceled():
                return {}

            # 构建全球矩形 [-180,-90 → 180,90]
            rect_geom = QgsGeometry.fromRect(QgsRectangle(-180.0, -90.0, 180.0, 90.0))
            rect_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "extent_temp", "memory")
            dp = rect_layer.dataProvider()
            dp.addAttributes(source_layer.fields())
            rect_layer.updateFields()
            rect_feat = QgsFeature(rect_layer.fields())
            rect_feat.setGeometry(rect_geom)
            dp.addFeatures([rect_feat])

            # 不经旋转裁剪，直接修正 → 增密 → 投影
            e_fix = processing.run(
                "native:fixgeometries",
                {"INPUT": rect_layer, "METHOD": 1, "OUTPUT": "TEMPORARY_OUTPUT"},
                context=context, feedback=feedback,
            )
            e_dens = processing.run(
                "native:densifygeometriesgivenaninterval",
                {"INPUT": e_fix["OUTPUT"], "INTERVAL": densify_interval, "OUTPUT": "TEMPORARY_OUTPUT"},
                context=context, feedback=feedback,
            )
            extent_projected = self._transform_layer(
                e_dens["OUTPUT"], proj_fn,
                layer_name=f"Extent_Project",
                feedback=feedback,
            )

            if sink_ext is not None:
                register_layer(extent_projected, f"Extent_Project",
                              sink_ext, dest_ext, 100)

        feedback.pushInfo("处理完成！")
        result = {self.OUTPUT_PROJECTION: dest_proj}
        if dest_rot:
            result[self.OUTPUT_ROTATION] = dest_rot
        if dest_ext:
            result[self.OUTPUT_EXTENT_SINK] = dest_ext
        return result

    # ----------------------------------------------------------
    # 图层逐要素投影变换
    # ----------------------------------------------------------

    def _transform_layer(self, source_layer, project_func, layer_name, feedback=None):
        geom_type = source_layer.geometryType()
        if geom_type == QgsWkbTypes.PointGeometry:
            wkt_type = "Point"
        elif geom_type == QgsWkbTypes.LineGeometry:
            wkt_type = "LineString"
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            wkt_type = "Polygon"
        else:
            wkt_type = "Geometry"

        target_layer = QgsVectorLayer(
            f"{wkt_type}?crs=no_projection", layer_name, "memory",
        )
        dp = target_layer.dataProvider()
        dp.addAttributes(source_layer.fields())
        target_layer.updateFields()

        new_features = []
        features = source_layer.getFeatures()
        total = source_layer.featureCount() or 1

        for i, feature in enumerate(features):
            if feedback and feedback.isCanceled():
                break

            geom = feature.geometry()
            if geom.isEmpty():
                continue

            def pt_transform(pt):
                x, y = project_func(pt.x(), pt.y())
                return QgsPointXY(x, y)

            new_geom = transform_geometry(geom, pt_transform)
            if new_geom and not new_geom.isEmpty():
                new_feat = QgsFeature()
                new_feat.setFields(target_layer.fields())
                new_feat.setAttributes(feature.attributes())
                new_feat.setGeometry(new_geom)
                new_features.append(new_feat)

            if feedback and i % 100 == 0:
                feedback.setProgress(int(i / total * 100))

        target_layer.dataProvider().addFeatures(new_features)
        target_layer.updateExtents()
        return target_layer

    def createInstance(self):
        return self.__class__()
