"""
Port of D3-geo rotation and antimeridian clipping to Python.
"""
import math

EPSILON = 1e-6
EPSILON2 = 1e-12
PI = math.pi
HALF_PI = PI / 2
QUARTER_PI = PI / 4
TAU = PI * 2
DEGREES = 180 / PI
RADIANS = PI / 180


def _asin(x):
    return HALF_PI if x > 1 else (-HALF_PI if x < -1 else math.asin(x))


def point_equal(a, b):
    return abs(a[0] - b[0]) < EPSILON and abs(a[1] - b[1]) < EPSILON


# ── Cartesian / spherical ────────────────────────────────────────────────

def cartesian(spherical):
    lam, phi = spherical[0], spherical[1]
    cos_phi = math.cos(phi)
    return [cos_phi * math.cos(lam), cos_phi * math.sin(lam), math.sin(phi)]


def cartesian_cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def cartesian_normalize_inplace(d):
    l = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    d[0] /= l; d[1] /= l; d[2] /= l


# ── Rotation ─────────────────────────────────────────────────────────────

def _forward_rotation_lambda(delta_lambda):
    def rotate(lam, phi):
        lam += delta_lambda
        if abs(lam) > PI:
            lam -= round(lam / TAU) * TAU
        return [lam, phi]
    return rotate


def _rotation_lambda(delta_lambda):
    fwd = _forward_rotation_lambda(delta_lambda)
    inv = _forward_rotation_lambda(-delta_lambda)
    return fwd, inv


def _rotation_phi_gamma(delta_phi, delta_gamma):
    cos_dphi = math.cos(delta_phi); sin_dphi = math.sin(delta_phi)
    cos_dgam = math.cos(delta_gamma); sin_dgam = math.sin(delta_gamma)

    def rotate(lam, phi):
        cos_phi = math.cos(phi)
        x = math.cos(lam) * cos_phi; y = math.sin(lam) * cos_phi
        z = math.sin(phi); k = z * cos_dphi + x * sin_dphi
        return [math.atan2(y * cos_dgam - k * sin_dgam, x * cos_dphi - z * sin_dphi),
                _asin(k * cos_dgam + y * sin_dgam)]

    def invert(lam, phi):
        cos_phi = math.cos(phi)
        x = math.cos(lam) * cos_phi; y = math.sin(lam) * cos_phi
        z = math.sin(phi); k = z * cos_dgam - y * sin_dgam
        return [math.atan2(y * cos_dgam + z * sin_dgam, x * cos_dphi + k * sin_dphi),
                _asin(k * cos_dphi - x * sin_dphi)]

    return rotate, invert


def _rotate_radians(delta_lambda, delta_phi, delta_gamma):
    delta_lambda %= TAU
    if delta_lambda:
        if delta_phi or delta_gamma:
            rl_fwd, rl_inv = _rotation_lambda(delta_lambda)
            rg_fwd, rg_inv = _rotation_phi_gamma(delta_phi, delta_gamma)
            def compose(x, y): x, y = rl_fwd(x, y); return rg_fwd(x, y)
            def compose_inv(x, y): x, y = rg_inv(x, y); return rl_inv(x, y)
            return compose, compose_inv
        else:
            return _rotation_lambda(delta_lambda)
    elif delta_phi or delta_gamma:
        return _rotation_phi_gamma(delta_phi, delta_gamma)
    else:
        def identity(lam, phi):
            if abs(lam) > PI: lam -= round(lam / TAU) * TAU
            return [lam, phi]
        return identity, identity


def rotate(angles):
    angles = [angles[0] * RADIANS, angles[1] * RADIANS,
              angles[2] * RADIANS if len(angles) > 2 else 0]
    rot_fwd, rot_inv = _rotate_radians(angles[0], angles[1], angles[2])

    def forward(coordinates):
        coord = rot_fwd(coordinates[0] * RADIANS, coordinates[1] * RADIANS)
        return [coord[0] * DEGREES, coord[1] * DEGREES]

    def invert(coordinates):
        coord = rot_inv(coordinates[0] * RADIANS, coordinates[1] * RADIANS)
        return [coord[0] * DEGREES, coord[1] * DEGREES]

    forward.invert = invert
    return forward


# ── Polygon containment ──────────────────────────────────────────────────

def _longitude(point):
    return point[0] if abs(point[0]) <= PI else (
        (1 if point[0] > 0 else -1) * ((abs(point[0]) + PI) % TAU - PI))


def polygon_contains(polygon, point):
    lam = _longitude(point); phi = point[1]
    sin_phi = math.sin(phi); normal = [math.sin(lam), -math.cos(lam), 0]
    angle = 0; winding = 0; _sum = 0.0
    if sin_phi == 1: phi = HALF_PI + EPSILON
    elif sin_phi == -1: phi = -HALF_PI - EPSILON
    for ring in polygon:
        m = len(ring)
        if m == 0: continue
        point0 = ring[m - 1]; lam0 = _longitude(point0)
        phi0 = point0[1] / 2 + QUARTER_PI
        sin_phi0 = math.sin(phi0); cos_phi0 = math.cos(phi0)
        for j in range(m):
            point1 = ring[j]; lam1 = _longitude(point1)
            phi1 = point1[1] / 2 + QUARTER_PI
            sin_phi1 = math.sin(phi1); cos_phi1 = math.cos(phi1)
            delta = lam1 - lam0; sign = 1 if delta >= 0 else -1
            abs_delta = sign * delta; antimeridian = abs_delta > PI
            k = sin_phi0 * sin_phi1
            _sum += math.atan2(k * sign * math.sin(abs_delta),
                               cos_phi0 * cos_phi1 + k * math.cos(abs_delta))
            angle += delta + sign * TAU if antimeridian else delta
            if antimeridian ^ (lam0 >= lam) ^ (lam1 >= lam):
                arc = cartesian_cross(cartesian(point0), cartesian(point1))
                cartesian_normalize_inplace(arc)
                intersection = cartesian_cross(normal, arc)
                cartesian_normalize_inplace(intersection)
                phi_arc = ((1 if antimeridian ^ (delta >= 0) else -1)
                           * _asin(intersection[2]))
                if phi > phi_arc or (phi == phi_arc and (arc[0] or arc[1])):
                    winding += 1 if antimeridian ^ (delta >= 0) else -1
            lam0, sin_phi0, cos_phi0, point0 = lam1, sin_phi1, cos_phi1, point1
    return (angle < -EPSILON or (angle < EPSILON and _sum < -EPSILON2)) ^ (winding & 1)


# ── Ring orientation ─────────────────────────────────────────────────────

def _ring_signed_area(ring):
    m = len(ring)
    if m < 3: return 0
    _sum = 0.0
    point0 = ring[m - 1]
    lam0 = _longitude(point0) if abs(point0[0]) > PI else point0[0]
    phi0 = point0[1] / 2 + QUARTER_PI
    sin_phi0 = math.sin(phi0); cos_phi0 = math.cos(phi0)
    for j in range(m):
        point1 = ring[j]
        lam1 = _longitude(point1) if abs(point1[0]) > PI else point1[0]
        phi1 = point1[1] / 2 + QUARTER_PI
        sin_phi1 = math.sin(phi1); cos_phi1 = math.cos(phi1)
        delta = lam1 - lam0; sign = 1 if delta >= 0 else -1
        abs_delta = sign * delta; k = sin_phi0 * sin_phi1
        _sum += math.atan2(k * sign * math.sin(abs_delta),
                           cos_phi0 * cos_phi1 + k * math.cos(abs_delta))
        lam0, sin_phi0, cos_phi0, point0 = lam1, sin_phi1, cos_phi1, point1
    return _sum


def _ensure_ccw(rings):
    result = []
    for i, ring in enumerate(rings):
        if len(ring) < 3:
            result.append(ring); continue
        area = _ring_signed_area(ring)
        if i == 0:
            if area < 0: result.append(list(reversed(ring)))
            else: result.append(list(ring))
        else:
            if area > 0: result.append(list(reversed(ring)))
            else: result.append(list(ring))
    return result


def _ring_spans_antimeridian(ring):
    """Check if a ring has consecutive vertices that span the antimeridian."""
    m = len(ring)
    if m < 2:
        return False
    for i in range(m):
        lon1 = ring[i][0]
        lon2 = ring[(i + 1) % m][0]
        if abs(lon1 - lon2) > PI:
            return True
    return False


def _ensure_ccw_skip_antimeridian(rings):
    """Like _ensure_ccw, but skip rings that cross the antimeridian.

    _ring_signed_area gives incorrect sign for antimeridian-crossing rings
    because the longitude folding creates virtual self-intersections.
    Applying _ensure_ccw to such rings would incorrectly reverse
    exterior↔hole orientation.
    """
    result = []
    for i, ring in enumerate(rings):
        if len(ring) < 3:
            result.append(ring)
            continue
        if _ring_spans_antimeridian(ring):
            # Can't reliably determine winding — preserve as-is
            result.append(list(ring))
            continue
        area = _ring_signed_area(ring)
        if i == 0:
            if area < 0:
                result.append(list(reversed(ring)))
            else:
                result.append(list(ring))
        else:
            if area > 0:
                result.append(list(reversed(ring)))
            else:
                result.append(list(ring))
    return result


# ── Antimeridian intersection ────────────────────────────────────────────

def _antimeridian_intersect(lam0, phi0, lam1, phi1):
    sin_lam_diff = math.sin(lam0 - lam1)
    if abs(sin_lam_diff) > EPSILON:
        cos_phi1 = math.cos(phi1); cos_phi0 = math.cos(phi0)
        return math.atan((math.sin(phi0) * cos_phi1 * math.sin(lam1) -
                          math.sin(phi1) * cos_phi0 * math.sin(lam0)) /
                         (cos_phi0 * cos_phi1 * sin_lam_diff))
    return (phi0 + phi1) / 2


# ── Line clipper (streaming) ─────────────────────────────────────────────

def _clip_antimeridian_line(stream):
    lam0 = float('nan'); phi0 = float('nan'); sign0 = float('nan'); clean = None

    class Clipper:
        @staticmethod
        def line_start():
            stream.line_start()
            nonlocal clean; clean = 1

        @staticmethod
        def point(lam1, phi1):
            nonlocal lam0, phi0, sign0, clean
            sign1 = PI if lam1 > 0 else -PI; delta = abs(lam1 - lam0)
            if abs(delta - PI) < EPSILON:
                phi0 = HALF_PI if (phi0 + phi1) / 2 > 0 else -HALF_PI
                stream.point(lam0, phi0); stream.point(sign0, phi0)
                stream.line_end(); stream.line_start()
                stream.point(sign1, phi0); stream.point(lam1, phi0); clean = 0
            elif sign0 != sign1 and delta >= PI:
                # Use copies to avoid corrupting lam0/lam1 for subsequent iterations
                a0 = lam0 - sign0 * EPSILON if abs(lam0 - sign0) < EPSILON else lam0
                a1 = lam1 - sign1 * EPSILON if abs(lam1 - sign1) < EPSILON else lam1
                phi = _antimeridian_intersect(a0, phi0, a1, phi1)
                stream.point(sign0, phi); stream.line_end()
                stream.line_start(); stream.point(sign1, phi); clean = 0
            stream.point(lam1, phi1)
            lam0, phi0, sign0 = lam1, phi1, sign1

        @staticmethod
        def line_end():
            stream.line_end()
            nonlocal lam0, phi0; lam0 = phi0 = float('nan')

        @staticmethod
        def clean(): return 2 - clean

    return Clipper()


# ── Clip buffer ──────────────────────────────────────────────────────────

class _ClipBuffer:
    """Collects line segments from the clipper (port of d3-geo clip/buffer.js)."""
    def __init__(self):
        self._lines = []
        self._line = None

    def point(self, x, y):
        self._line.append([x, y])

    def line_start(self):
        self._lines.append([])
        self._line = self._lines[-1]

    def line_end(self):
        pass

    def result(self):
        r = self._lines
        self._lines = []
        self._line = None
        return r


# ── Rejoin (port of d3-geo clip/rejoin.js) ───────────────────────────────

class _Intersection:
    __slots__ = ('x', 'z', 'o', 'e', 'd', 'v', 'n', 'p')
    def __init__(self, point, points, other, entry):
        self.x = point          # endpoint coordinate [lam, phi]
        self.z = points         # segment this belongs to (or None for clip)
        self.o = other          # linked intersection on the other side
        self.e = entry          # is this an entry?
        self.d = 0              # interpolation direction (+1 or -1)
        self.v = False          # visited
        self.n = None           # next in circular linked list
        self.p = None           # prev in circular linked list


def _intersection_compare_key(a):
    """Sort key for intersections along the ±180° clip boundary."""
    ax, ay = a.x
    return (ay - HALF_PI - EPSILON) if ax < 0 else (HALF_PI - ay)


def _clip_rejoin(segments, start_inside, sink):
    """Rejoin clipped segments into closed rings (port of d3-geo rejoin.js)."""
    subject = []
    clip = []

    for segment in segments:
        n = len(segment) - 1
        if n <= 0:
            continue
        p0 = segment[0]
        p1 = segment[n]

        if point_equal(p0, p1):
            sink.line_start()
            for i in range(n):
                pt = segment[i]
                sink.point(pt[0], pt[1])
            sink.line_end()
            continue

        x = _Intersection(p0, segment, None, True)
        subject.append(x)
        clip.append(_Intersection(p0, None, x, False))
        x.o = clip[-1]

        x = _Intersection(p1, segment, None, False)
        subject.append(x)
        clip.append(_Intersection(p1, None, x, True))
        x.o = clip[-1]

    if not subject:
        return

    clip.sort(key=_intersection_compare_key)
    _link(subject)
    _link(clip)

    for i in range(len(clip)):
        start_inside = not start_inside
        clip[i].e = start_inside

    start = subject[0]

    while True:
        current = start
        is_subject = True
        while current.v:
            current = current.n
            if current is start:
                return
        points = current.z
        sink.line_start()
        while True:
            current.v = True
            current.o.v = True
            if current.e:
                if is_subject:
                    for i in range(len(points)):
                        pt = points[i]
                        sink.point(pt[0], pt[1])
                else:
                    _interpolate(current.x, current.n.x, 1, sink)
                current = current.n
            else:
                if is_subject:
                    points = current.p.z
                    for i in range(len(points) - 1, -1, -1):
                        pt = points[i]
                        sink.point(pt[0], pt[1])
                else:
                    _interpolate(current.x, current.p.x, -1, sink)
                current = current.p
            current = current.o
            points = current.z
            is_subject = not is_subject
            if current.v:
                break
        sink.line_end()


def _link(array):
    n = len(array)
    if not n:
        return
    a = array[0]
    for i in range(1, n):
        b = array[i]
        a.n = b
        b.p = a
        a = b
    b = array[0]
    a.n = b
    b.p = a


def _interpolate(from_pt, to_pt, direction, sink):
    """Interpolate along the clip edge (±180° meridian). Port of clipAntimeridianInterpolate."""
    if from_pt is None:
        phi = direction * HALF_PI
        sink.point(-PI, phi)
        sink.point(0, phi)
        sink.point(PI, phi)
        sink.point(PI, 0)
        sink.point(PI, -phi)
        sink.point(0, -phi)
        sink.point(-PI, -phi)
        sink.point(-PI, 0)
        sink.point(-PI, phi)
    elif abs(from_pt[0] - to_pt[0]) > EPSILON:
        lam = PI if from_pt[0] < to_pt[0] else -PI
        phi = direction * lam / 2
        sink.point(-lam, phi)
        sink.point(0, phi)
        sink.point(lam, phi)
    else:
        sink.point(to_pt[0], to_pt[1])


# ── Output sink ──────────────────────────────────────────────────────────

class _RingCollector:
    """Collects stream calls into a list of rings (in radian coordinates)."""
    def __init__(self):
        self.rings = []
        self._current = []

    def point(self, x, y):
        self._current.append([x, y])

    def line_start(self):
        self._current = []

    def line_end(self):
        if len(self._current) >= 3:
            self.rings.append(list(self._current))
        self._current = []


# ── Antimeridian clip (main pipeline) ────────────────────────────────────

def antimeridian_clip(rings):
    """
    Clip polygon rings at the antimeridian (±180°).

    This is a faithful port of the d3-geo antimeridian clip pipeline:
    clip/antimeridian.js + clip/buffer.js + clip/index.js + clip/rejoin.js

    Args:
        rings: List of rings, each ring is a list of [lon_deg, lat_deg] points.

    Returns:
        List of clipped rings in degree coordinates.
    """
    if not rings:
        return []

    # Convert to radians.
    rad_rings = []
    for ring in rings:
        if len(ring) < 3:
            continue
        rad_rings.append([[math.radians(pt[0]), math.radians(pt[1])] for pt in ring])

    if not rad_rings:
        return []

    # Normalize winding for rings that DON'T cross the antimeridian.
    # Rings that DO cross have unreliable _ring_signed_area (the longitude
    # wrapping creates virtual self-intersections), so we skip them here
    # and fix winding on the OUTPUT after clipping instead.
    rad_rings = _ensure_ccw_skip_antimeridian(rad_rings)

    if not rad_rings:
        return []

    # ── First pass: stream each ring through clipper, collect segments ──
    output = _RingCollector()
    dirty_segments = []   # segments with clip-boundary intersections
    polygon = []          # original rings for polygonContains check

    for ring in rad_rings:
        buf = _ClipBuffer()
        clipper = _clip_antimeridian_line(buf)

        clipper.line_start()
        for pt in ring:
            clipper.point(pt[0], pt[1])
        # Close the ring by repeating the first point
        clipper.point(ring[0][0], ring[0][1])
        clipper.line_end()

        clean_val = clipper.clean()
        ring_segments = buf.result()

        polygon.append(list(ring))

        if not ring_segments:
            continue

        # clean & 1: no intersections → output segment directly (bypass rejoin)
        if clean_val & 1:
            seg = ring_segments[0]
            m = len(seg) - 1
            if m > 0:
                output.line_start()
                for i in range(m):
                    output.point(seg[i][0], seg[i][1])
                output.line_end()
            continue

        # clean & 2: rejoin first and last segments of this ring
        if len(ring_segments) > 1 and (clean_val & 2):
            ring_segments.append(ring_segments.pop(-1) + ring_segments.pop(0))

        for seg in ring_segments:
            if len(seg) > 1:
                dirty_segments.append(seg)

    # ── Second pass: check containment, run rejoin ──
    start_inside = polygon_contains(polygon, [-PI, -HALF_PI]) if polygon else False

    if dirty_segments:
        _clip_rejoin(dirty_segments, start_inside, output)
    elif start_inside and not output.rings:
        output.line_start()
        _interpolate(None, None, 1, output)
        output.line_end()

    # ── Convert output back to degrees ──
    if not output.rings:
        # Polygon is completely outside → return empty
        return []

    result_rad = list(output.rings)

    # ── Fix winding: ensure exterior CCW, holes CW ──
    result_rad = _ensure_ccw(result_rad)

    # ── Sanity: if the exterior ring covers more than half the globe
    #    (|signed area| > 2π), the polygon was inverted during rejoin.
    #    Reverse all rings to get the intended complement. ──
    if result_rad:
        ext_area = _ring_signed_area(result_rad[0])
        if abs(ext_area) > 2 * PI:
            # All rings are inverted — complement each
            result_rad = [list(reversed(r)) for r in result_rad]
            # Re-normalize winding after complement
            result_rad = _ensure_ccw(result_rad)

    result = []
    for ring in result_rad:
        clean_ring = []
        for pt in ring:
            deg_pt = [pt[0] * DEGREES, pt[1] * DEGREES]
            if clean_ring and point_equal(deg_pt, clean_ring[-1]):
                continue
            clean_ring.append(deg_pt)
        # Ensure ring is closed
        if len(clean_ring) >= 3:
            if not point_equal(clean_ring[0], clean_ring[-1]):
                clean_ring.append([clean_ring[0][0], clean_ring[0][1]])
            result.append(clean_ring)

    return result


# ── Public API ───────────────────────────────────────────────────────────

def clip_line(coords):
    """Clip a line at the antimeridian. Coords are in radians."""
    segments = []; _cur = [[]]
    class Sink:
        @staticmethod
        def point(x, y): _cur[0].append([x, y])
        @staticmethod
        def line_start(): _cur[0] = []
        @staticmethod
        def line_end():
            if len(_cur[0]) >= 2: segments.append(list(_cur[0]))
            _cur[0] = []
    clipper = _clip_antimeridian_line(Sink)
    if len(coords) >= 2:
        clipper.line_start()
        for pt in coords: clipper.point(pt[0], pt[1])
        clipper.line_end()
    return segments


def clip_geometry(geom_rings, rotation=None):
    """Clip polygon geometry with optional rotation. Rings are in degrees."""
    if rotation and any(a != 0 for a in rotation):
        rot = rotate(rotation)
        rings = [[rot([pt[0], pt[1]]) for pt in ring] for ring in geom_rings]
    else:
        rings = geom_rings
    return antimeridian_clip(rings)
