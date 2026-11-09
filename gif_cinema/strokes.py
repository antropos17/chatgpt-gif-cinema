"""Bounded, local polyline draw-on animation. No tracing or generated handwriting."""
import bisect
import math

from .motion import number

MAX_POINTS = 512
# Dynamic paths are rerasterized at 3x resolution, unlike cached text/shapes.
MAX_RASTER_PIXEL_FRAMES = 256 * 1024 * 1024
MAX_SEGMENT_FRAMES = 1000000


def validate_points(points, size):
    if not isinstance(points, list) or not 2 <= len(points) <= MAX_POINTS:
        raise ValueError(f'Stroke points must contain 2..{MAX_POINTS} coordinate pairs')
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError('Stroke points must be [x, y] pixel coordinate pairs')
        for axis, limit in zip(point, size):
            number(axis, 'stroke point', 0, limit - 1)
    if all(point == points[0] for point in points):
        raise ValueError('Stroke path must have nonzero length')


def _without_collinear_points(points):
    """Remove only exact forward subdivisions, preserving turns/backtracking."""
    vertices = []
    for coordinates in points:
        point = tuple(coordinates)
        if vertices and point == vertices[-1]:
            continue
        while len(vertices) >= 2:
            a, b = vertices[-2:]
            u, v = (b[0] - a[0], b[1] - a[1]), (point[0] - b[0], point[1] - b[1])
            if u[0] * v[1] != u[1] * v[0] or u[0] * v[0] + u[1] * v[1] < 0:
                break
            vertices.pop()
        vertices.append(point)
    return vertices


def prepare_path(points):
    """Cache cumulative geometric distance; uneven control-point spacing is safe."""
    # Normalize before measuring distance so subdivision does not change floating
    # point rounding at a moving tip. The editable source points are untouched.
    vertices = _without_collinear_points(points)
    distinct = [vertices[0]]
    ends = [0.]
    for point in vertices[1:]:
        length = math.hypot(point[0] - distinct[-1][0], point[1] - distinct[-1][1])
        if length and ends[-1] + length > ends[-1]:
            ends.append(ends[-1] + length)
            distinct.append(tuple(point))
    return {'points': distinct, 'ends': ends, 'length': ends[-1]}


def prefix(path, reveal):
    """Return the visible prefix by arc length, never by vertex count."""
    number(reveal, 'reveal', 0, 1)
    if reveal == 0:
        return []
    if reveal == 1:
        return list(path['points'])
    distance = reveal * path['length']
    index = min(bisect.bisect_right(path['ends'], distance) - 1, len(path['points']) - 2)
    left, right = path['points'][index:index + 2]
    fraction = (distance - path['ends'][index]) / (path['ends'][index + 1] - path['ends'][index])
    endpoint = tuple(a + (b - a) * fraction for a, b in zip(left, right))
    return path['points'][:index + 1] + [endpoint]


def rasterize(layer, path, reveal, supersample):
    """Round caps/joins share one coverage mask, so overlaps do not darken."""
    from PIL import Image, ImageColor, ImageDraw
    points = prefix(path, reveal)
    width, height = layer['size']
    if not points:
        return Image.new('RGBA', (width, height))
    scale = supersample
    mask = Image.new('L', (width * scale, height * scale))
    draw = ImageDraw.Draw(mask)
    vertices = [(x * scale, y * scale) for x, y in _without_collinear_points(points)]
    thickness = layer['stroke_width'] * scale
    radius = thickness / 2
    # Construct segment rectangles and disks from the same geometric radius.
    # ImageDraw.line's integer-width convention differs from ellipse bounds and
    # otherwise produces a visible bulge at every authored vertex and pen tip.
    for (ax, ay), (bx, by) in zip(vertices, vertices[1:]):
        distance = math.hypot(bx - ax, by - ay)
        nx, ny = -(by - ay) * radius / distance, (bx - ax) * radius / distance
        draw.polygon([(ax + nx, ay + ny), (bx + nx, by + ny),
                      (bx - nx, by - ny), (ax - nx, ay - ny)], fill=255)
    # Explicit disks give every join and the moving pen tip the same round cap.
    for x, y in vertices:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    rgba = ImageColor.getcolor(layer['stroke'], 'RGBA')
    if rgba[3] != 255:
        mask = mask.point(lambda coverage: round(coverage * rgba[3] / 255))
    result = Image.new('RGBA', (width, height), rgba)
    result.putalpha(mask)
    return result
