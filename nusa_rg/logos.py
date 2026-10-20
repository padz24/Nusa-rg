"""Provider logos drawn in the terminal.

models.dev serves one SVG per provider id (``/logos/{provider}.svg``). A
terminal cannot display SVG, so the file is parsed, rasterised, and printed as
Braille cells: one character carries a 2x4 dot matrix, so a 16x16 pixel mark
fits in four lines of eight characters.

The drawings are deliberately simple -- filled shapes only, no gradients, no
clip paths, no text -- because that is what the registry logos use. A logo
that cannot be parsed yields nothing at all rather than a misleading smear,
so the caller can fall back to plain text.

SVGs are fetched once and cached under ``~/.nusa-rg/logos``. A missing network
is not an error: the icon is simply left out.
"""

from __future__ import annotations

import math
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import paths
from .catalog import logo_url

#: Braille cell base (U+2800) plus the dot bits.
BRAILLE_BASE = 0x2800

#: Dot bit for every (row, column) of a Braille cell.
_DOT_BITS = (0x01, 0x08, 0x02, 0x10, 0x04, 0x20, 0x40, 0x80)

#: A logo is a small vector file; anything larger is not one.
MAX_LOGO_BYTES = 256 * 1024

#: Default drawing size in pixels.
SIZE = 16

#: How many providers are fetched at the same time.
_FETCH_WORKERS = 6

#: Set to any value to keep the CLI from touching the network for logos.
DISABLE_ENV = "NUSA_RG_NO_LOGOS"


class LogoError(RuntimeError):
    """A logo could not be fetched or parsed."""


# ------------------------------------------------------------------ caching

def cache_path(provider_id: str) -> Path:
    """Where the SVG of one provider is kept."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", (provider_id or "").strip())
    if not safe or safe in (".", ".."):
        raise LogoError("empty provider id")
    return paths.logos_dir() / f"{safe}.svg"


def disabled() -> bool:
    """True when the user asked for no logo downloads."""
    return bool(os.environ.get(DISABLE_ENV))


def svg_text(provider_id: str, timeout: int = 15) -> str:
    """The SVG of one provider, from the cache or from models.dev."""
    target = cache_path(provider_id)
    if target.is_file():
        try:
            return target.read_text(encoding="utf-8")
        except OSError:
            pass

    url = logo_url(provider_id)
    from . import __version__

    request = urllib.request.Request(
        url, headers={"User-Agent": f"nusa-rg/{__version__} (Termux)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_LOGO_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise LogoError(f"{url} answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LogoError(f"cannot reach {url}: {exc}") from exc
    if len(payload) > MAX_LOGO_BYTES:
        raise LogoError(f"{url} is larger than {MAX_LOGO_BYTES} bytes")

    text = payload.decode("utf-8", "replace")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        paths.restrict(target.parent, 0o700)
        target.write_text(text, encoding="utf-8")
        paths.restrict(target)
    except OSError:
        # A read-only state directory must not stop the drawing.
        pass
    return text


# ------------------------------------------------------------------ parsing

_TOKEN_RE = re.compile(r"<(/?)([A-Za-z][\w:-]*)([^>]*?)(/?)>", re.S)
_ATTR_RE = re.compile(r'([\w:.-]+)\s*=\s*"([^"]*)"')
_NUMBER_RE = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")

#: A path is a list of closed or open subpaths.
Subpath = list[tuple[float, float]]
Shape = list[Subpath]


def _attributes(text: str) -> dict[str, str]:
    return {key.lower(): value for key, value in _ATTR_RE.findall(text)}


def _numbers(text: str) -> list[float]:
    return [float(value) for value in _NUMBER_RE.findall(text or "")]


def _matrix(values: list[float]) -> tuple[float, float, float, float, float, float]:
    """(a, b, c, d, e, f) of an affine transform, identity when unknown."""
    if len(values) == 6:
        return tuple(values)  # type: ignore[return-value]
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _multiply(first, second):
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = second
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply(matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def _parse_transform(text: str):
    """Translate, scale, rotate and matrix transforms, combined."""
    result = IDENTITY
    for name, body in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        values = _numbers(body)
        if name == "translate":
            step = (1.0, 0.0, 0.0, 1.0,
                    values[0] if values else 0.0,
                    values[1] if len(values) > 1 else 0.0)
        elif name == "scale":
            sx = values[0] if values else 1.0
            sy = values[1] if len(values) > 1 else sx
            step = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate":
            angle = math.radians(values[0] if values else 0.0)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            step = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
        elif name == "matrix":
            step = _matrix(values)
        else:
            continue
        result = _multiply(result, step)
    return result


def _flatten_path(data: str, steps: int = 10) -> list[Subpath]:
    """Turn an SVG path into polylines.

    Every command the registry logos use is supported: moves, lines, cubic and
    quadratic curves (with their shorthand forms), elliptical arcs, and
    closepath.
    """
    tokens = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", data or "")
    index = 0
    command = ""
    x = y = 0.0
    start = (0.0, 0.0)
    previous_control: tuple[float, float] | None = None
    subpaths: list[Subpath] = []
    current: Subpath = []

    def number() -> float:
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    def curve(control1, control2, end):
        for step in range(1, steps + 1):
            t = step / steps
            rest = 1 - t
            px = (rest ** 3 * x + 3 * rest ** 2 * t * control1[0]
                  + 3 * rest * t ** 2 * control2[0] + t ** 3 * end[0])
            py = (rest ** 3 * y + 3 * rest ** 2 * t * control1[1]
                  + 3 * rest * t ** 2 * control2[1] + t ** 3 * end[1])
            current.append((px, py))

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command in "Zz":
                if current:
                    current.append(start)
                    subpaths.append(current)
                    current = []
                x, y = start
                previous_control = None
                continue
        elif not command:
            break
        relative = command.islower()
        upper = command.upper()

        if upper == "M":
            nx, ny = number(), number()
            if relative:
                nx, ny = nx + x, ny + y
            if current:
                subpaths.append(current)
            current = [(nx, ny)]
            x, y = nx, ny
            start = (nx, ny)
            command = "l" if relative else "L"
            previous_control = None
        elif upper == "L":
            nx, ny = number(), number()
            if relative:
                nx, ny = nx + x, ny + y
            current.append((nx, ny))
            x, y = nx, ny
            previous_control = None
        elif upper == "H":
            nx = number()
            if relative:
                nx += x
            current.append((nx, y))
            x = nx
            previous_control = None
        elif upper == "V":
            ny = number()
            if relative:
                ny += y
            current.append((x, ny))
            y = ny
            previous_control = None
        elif upper in ("C", "S"):
            if upper == "C":
                control1 = (number(), number())
                control2 = (number(), number())
            else:
                control1 = (2 * x - previous_control[0], 2 * y - previous_control[1]) \
                    if previous_control else (x, y)
                control2 = (number(), number())
            end = (number(), number())
            if relative:
                control1 = (control1[0] + x, control1[1] + y)
                control2 = (control2[0] + x, control2[1] + y)
                end = (end[0] + x, end[1] + y)
            curve(control1, control2, end)
            previous_control = control2
            x, y = end
        elif upper in ("Q", "T"):
            if upper == "Q":
                control = (number(), number())
            else:
                control = (2 * x - previous_control[0], 2 * y - previous_control[1]) \
                    if previous_control else (x, y)
            end = (number(), number())
            if relative:
                control = (control[0] + x, control[1] + y)
                end = (end[0] + x, end[1] + y)
            control1 = (x + 2 / 3 * (control[0] - x), y + 2 / 3 * (control[1] - y))
            control2 = (end[0] + 2 / 3 * (control[0] - end[0]),
                        end[1] + 2 / 3 * (control[1] - end[1]))
            curve(control1, control2, end)
            previous_control = control
            x, y = end
        elif upper == "A":
            rx, ry = abs(number()), abs(number())
            rotation = math.radians(number())
            large = bool(int(number()))
            sweep = bool(int(number()))
            end = (number(), number())
            if relative:
                end = (end[0] + x, end[1] + y)
            x, y = _arc(x, y, rx, ry, rotation, large, sweep, end, current)
            previous_control = None
        else:
            index += 1

    if current:
        subpaths.append(current)
    return subpaths


def _arc(x: float, y: float, rx: float, ry: float, rotation: float,
         large: bool, sweep: bool, end, current: Subpath):
    """Append an elliptical arc to ``current`` and return its end point."""
    if rx == 0 or ry == 0 or (x == end[0] and y == end[1]):
        current.append(end)
        return end

    cos_r, sin_r = math.cos(rotation), math.sin(rotation)
    dx, dy = (x - end[0]) / 2.0, (y - end[1]) / 2.0
    x1 = cos_r * dx + sin_r * dy
    y1 = -sin_r * dx + cos_r * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx, ry = rx * scale, ry * scale
    numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0.0, numerator / denominator)) if denominator else 0.0
    if large == sweep:
        factor = -factor
    cx1 = factor * rx * y1 / ry
    cy1 = -factor * ry * x1 / rx
    cx = cos_r * cx1 - sin_r * cy1 + (x + end[0]) / 2.0
    cy = sin_r * cx1 + cos_r * cy1 + (y + end[1]) / 2.0
    ux, uy = (x1 - cx1) / rx, (y1 - cy1) / ry
    vx, vy = (-x1 - cx1) / rx, (-y1 - cy1) / ry
    theta = math.atan2(uy, ux)
    delta = math.atan2(vy, vx) - theta
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    segments = max(1, int(abs(delta) / (math.pi / 2)) + 1)
    for step in range(1, segments + 1):
        angle = theta + delta * step / segments
        current.append((
            cx + rx * math.cos(angle) * cos_r - ry * math.sin(angle) * sin_r,
            cy + rx * math.cos(angle) * sin_r + ry * math.sin(angle) * cos_r,
        ))
    return end


def _points(text: str) -> list[tuple[float, float]]:
    values = _numbers(text)
    return [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]


def parse(svg: str) -> tuple[list[tuple[Shape, tuple]], tuple[float, float, float, float]]:
    """Read an SVG into shapes and the view box they live in.

    Returns the shapes (each a list of subpaths) with their bounding box, and
    the view box as ``(min_x, min_y, width, height)``.
    """
    shapes: list[tuple[Shape, tuple]] = []
    stack: list = [IDENTITY]
    view = (0.0, 0.0, 0.0, 0.0)

    for match in _TOKEN_RE.finditer(svg or ""):
        closing, name, body, self_closing = match.groups()
        tag = name.lower()
        if closing:
            if tag == "g" and len(stack) > 1:
                stack.pop()
            continue

        attributes = _attributes(body)
        if tag == "svg":
            if "viewbox" in attributes:
                values = _numbers(attributes["viewbox"])
                if len(values) == 4:
                    view = (values[0], values[1], values[2], values[3])
            elif "width" in attributes and "height" in attributes:
                width = _numbers(attributes["width"])
                height = _numbers(attributes["height"])
                if width and height:
                    view = (0.0, 0.0, width[0], height[0])
            continue

        if tag == "g":
            stack.append(_multiply(stack[-1],
                                   _parse_transform(attributes.get("transform", ""))))
            continue

        if attributes.get("fill", "").strip().lower() == "none":
            continue

        matrix = _multiply(stack[-1],
                            _parse_transform(attributes.get("transform", "")))
        subpaths: list[Subpath] = []
        if tag == "path":
            subpaths = _flatten_path(attributes.get("d", ""))
        elif tag == "rect":
            x = _numbers(attributes.get("x", "0"))
            y = _numbers(attributes.get("y", "0"))
            width = _numbers(attributes.get("width", "0"))
            height = _numbers(attributes.get("height", "0"))
            if width and height and width[0] > 0 and height[0] > 0:
                left, top = x[0] if x else 0.0, y[0] if y else 0.0
                right, bottom = left + width[0], top + height[0]
                subpaths = [[(left, top), (right, top), (right, bottom), (left, bottom)]]
        elif tag in ("circle", "ellipse"):
            cx = _numbers(attributes.get("cx", "0"))
            cy = _numbers(attributes.get("cy", "0"))
            radius = _numbers(attributes.get("r", "0"))
            rx = radius[0] if radius else 0.0
            ry = _numbers(attributes.get("ry", ""))
            ry = ry[0] if ry else rx
            if rx > 0 and ry > 0:
                centre_x = cx[0] if cx else 0.0
                centre_y = cy[0] if cy else 0.0
                subpaths = [[
                    (centre_x + rx * math.cos(step * math.pi / 24),
                     centre_y + ry * math.sin(step * math.pi / 24))
                    for step in range(49)
                ]]
        elif tag in ("polygon", "polyline"):
            points = _points(attributes.get("points", ""))
            if len(points) >= 3:
                subpaths = [points]
        else:
            continue

        if not subpaths:
            continue

        moved: Shape = []
        for subpath in subpaths:
            moved.append([_apply(matrix, px, py) for px, py in subpath])
        xs = [px for subpath in moved for px, _ in subpath]
        ys = [py for subpath in moved for _, py in subpath]
        shapes.append((moved, (min(xs), min(ys), max(xs), max(ys))))

    return shapes, view


# -------------------------------------------------------------- rasterising

def _winding(shape: Shape, px: float, py: float) -> int:
    """Winding number of a point against one shape."""
    winding = 0
    for subpath in shape:
        count = len(subpath)
        for index in range(count):
            x1, y1 = subpath[index]
            x2, y2 = subpath[(index + 1) % count]
            if (y1 > py) != (y2 > py):
                ratio = (py - y1) / (y2 - y1)
                crossing = x1 + ratio * (x2 - x1)
                if px < crossing:
                    winding += 1 if y2 > y1 else -1
    return winding


def rasterize(shapes, view, width: int, height: int) -> list[list[bool]]:
    """Turn shapes into a pixel grid."""
    min_x, min_y, view_w, view_h = view
    if view_w <= 0 or view_h <= 0:
        return [[False] * width for _ in range(height)]
    scale = min(width / view_w, height / view_h)
    offset_x = (width - view_w * scale) / 2
    offset_y = (height - view_h * scale) / 2

    grid = [[False] * width for _ in range(height)]
    for row in range(height):
        for column in range(width):
            ux = min_x + (column + 0.5 - offset_x) / scale
            uy = min_y + (row + 0.5 - offset_y) / scale
            for shape, (left, top, right, bottom) in shapes:
                if ux < left or ux > right or uy < top or uy > bottom:
                    continue
                if _winding(shape, ux, uy) != 0:
                    grid[row][column] = True
                    break
    return grid


def braille(grid: list[list[bool]]) -> list[str]:
    """Print a pixel grid as Braille characters."""
    lines: list[str] = []
    height = len(grid)
    width = len(grid[0]) if height else 0
    for top in range(0, height, 4):
        line = []
        for left in range(0, width, 2):
            dots = 0
            for row in range(4):
                for column in range(2):
                    y, x = top + row, left + column
                    if y < height and x < width and grid[y][x]:
                        dots |= _DOT_BITS[row * 2 + column]
            line.append(chr(BRAILLE_BASE + dots))
        lines.append("".join(line))
    return lines


# ------------------------------------------------------------------ drawing

def render(svg: str, size: int = SIZE) -> list[str]:
    """Draw an SVG as Braille lines, empty when nothing can be drawn."""
    if not svg or "<svg" not in svg:
        return []
    try:
        shapes, view = parse(svg)
    except (ValueError, TypeError, IndexError, ZeroDivisionError, OverflowError):
        return []
    if not shapes:
        return []
    return braille(rasterize(shapes, view, size, size))


def icon(provider_id: str, size: int = SIZE) -> list[str]:
    """Draw the logo of one provider; empty when it cannot be fetched."""
    try:
        svg = svg_text(provider_id)
    except LogoError:
        return []
    return render(svg, size)


def icons(provider_ids: list[str], size: int = SIZE) -> dict[str, list[str]]:
    """Draw several provider logos, fetching the missing ones in parallel."""
    if not provider_ids or disabled():
        return {}
    drawings: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        results = pool.map(lambda name: (name, icon(name, size)), provider_ids)
        for name, drawing in results:
            if drawing:
                drawings[name] = drawing
    return drawings


__all__ = [
    "DISABLE_ENV", "LogoError", "SIZE", "braille", "cache_path", "disabled",
    "icon", "icons", "logo_url", "parse", "rasterize", "render", "svg_text",
]
