"""Provider logos: SVG parsing, rasterising, caching, and the CLI view."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nusa_rg import logos, paths
from nusa_rg.cli import main

#: A square drawn as a path; the rasteriser must see it as a filled block.
SQUARE = (
    '<svg width="24" height="24" viewBox="0 0 24 24" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<path d="M4 4H20V20H4Z" fill="currentColor"/>'
    "</svg>"
)

#: A triangle, to check that curves and closepath are handled.
TRIANGLE = (
    '<svg width="24" height="24" viewBox="0 0 24 24">'
    '<path d="M12 3 L21 20 L3 20 Z" fill="black"/>'
    "</svg>"
)


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)


# ------------------------------------------------------------------ parsing
def test_parse_reads_the_view_box_and_the_shapes():
    shapes, view = logos.parse(SQUARE)

    assert view == (0.0, 0.0, 24.0, 24.0)
    assert len(shapes) == 1
    shape, box = shapes[0]
    assert box == (4.0, 4.0, 20.0, 20.0)
    assert shape[0][0] == (4.0, 4.0)


def test_parse_understands_rectangles_and_circles():
    svg = ('<svg viewBox="0 0 10 10">'
           '<rect x="1" y="2" width="3" height="4"/>'
           '<circle cx="5" cy="5" r="2"/>'
           "</svg>")

    shapes, _ = logos.parse(svg)

    assert len(shapes) == 2
    assert shapes[0][1] == (1.0, 2.0, 4.0, 6.0)


def test_parse_applies_a_translate():
    svg = ('<svg viewBox="0 0 10 10">'
           '<g transform="translate(5 5)">'
           '<rect x="0" y="0" width="2" height="2"/>'
           "</g></svg>")

    shapes, _ = logos.parse(svg)

    assert shapes[0][1] == (5.0, 5.0, 7.0, 7.0)


def test_shapes_with_no_fill_are_skipped():
    svg = ('<svg viewBox="0 0 10 10">'
           '<rect x="0" y="0" width="2" height="2" fill="none"/>'
           '<rect x="4" y="4" width="2" height="2"/>'
           "</svg>")

    shapes, _ = logos.parse(svg)

    assert len(shapes) == 1


# -------------------------------------------------------------- rasterising
def test_render_draws_a_filled_square():
    lines = logos.render(SQUARE, 16)

    assert len(lines) == 4, "a 16 pixel square is four Braille rows"
    assert any(line.replace("⠀", "") for line in lines), "the block is not empty"
    # The middle of the shape is ink.
    assert lines[1][3] != "⠀"


def test_render_leaves_the_corners_empty():
    lines = logos.render(SQUARE, 16)

    first = lines[0][0]
    assert first == "⠀", "the corner of the view box stays blank"


def test_render_of_a_triangle_is_not_empty():
    lines = logos.render(TRIANGLE, 16)

    assert len(lines) == 4
    assert any(line.strip("⠀") for line in lines)


def test_render_of_garbage_is_empty():
    assert logos.render("not an svg at all") == []
    assert logos.render("") == []


def test_braille_encodes_the_dots():
    grid = [[True, False, False, False],
            [False, False, False, False],
            [False, False, False, False],
            [False, False, False, False]]

    # Dot 1 is the top left corner of the cell.
    assert logos.braille(grid) == ["⠁⠀"]


# ------------------------------------------------------------------ caching
class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size=-1):
        return self._payload


def test_svg_is_cached_after_the_first_fetch(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=0):
        calls.append(request.full_url)
        return _FakeResponse(SQUARE.encode())

    monkeypatch.setattr(logos.urllib.request, "urlopen", fake_urlopen)

    first = logos.svg_text("groq")
    second = logos.svg_text("groq")

    assert "<svg" in first
    assert second == first
    assert len(calls) == 1, "the second read comes from the cache"
    cached = paths.logos_dir() / "groq.svg"
    assert cached.is_file()
    assert cached.stat().st_mode & 0o077 == 0


def test_a_missing_logo_is_reported_not_raised(monkeypatch):
    def fake_urlopen(request, timeout=0):
        raise OSError("no network")

    monkeypatch.setattr(logos.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(logos.LogoError):
        logos.svg_text("groq")
    assert logos.icon("groq") == []


def test_cache_path_rejects_an_empty_id():
    with pytest.raises(logos.LogoError):
        logos.cache_path("")


def test_disabled_reads_the_environment(monkeypatch):
    monkeypatch.delenv(logos.DISABLE_ENV, raising=False)
    assert logos.disabled() is False
    monkeypatch.setenv(logos.DISABLE_ENV, "1")
    assert logos.disabled() is True
    assert logos.icons(["groq"]) == {}


# ---------------------------------------------------------------------- CLI
def test_providers_list_draws_the_logo(runner, monkeypatch):
    monkeypatch.delenv(logos.DISABLE_ENV, raising=False)
    monkeypatch.setattr(logos, "svg_text", lambda name, timeout=15: SQUARE)

    result = run(runner, ["providers", "list", "--search", "groq"])

    assert result.exit_code == 0
    assert "groq" in result.output
    assert any(character in result.output for character in "⠿⣿⠟⠛")
    assert "models.dev/logos/groq.svg" in result.output


def test_providers_list_falls_back_to_one_line_without_logos(runner, monkeypatch):
    monkeypatch.delenv(logos.DISABLE_ENV, raising=False)
    monkeypatch.setattr(logos, "svg_text", lambda name, timeout=15: "")

    result = run(runner, ["providers", "list", "--search", "groq"])

    assert result.exit_code == 0
    assert "groq.svg" in result.output
    assert not any(character in result.output for character in "⠿⣿⠟⠛")


def test_providers_list_no_icons_skips_the_download(runner, monkeypatch):
    calls = []

    def fake_svg(name, timeout=15):
        calls.append(name)
        return SQUARE

    monkeypatch.delenv(logos.DISABLE_ENV, raising=False)
    monkeypatch.setattr(logos, "svg_text", fake_svg)

    result = run(runner, ["providers", "list", "--search", "groq", "--no-icons"])

    assert result.exit_code == 0
    assert calls == []
    assert "groq.svg" in result.output


def test_providers_show_draws_the_logo(runner, monkeypatch):
    monkeypatch.delenv(logos.DISABLE_ENV, raising=False)
    monkeypatch.setattr(logos, "svg_text", lambda name, timeout=15: SQUARE)

    result = run(runner, ["providers", "show", "groq"])

    assert result.exit_code == 0
    assert "https://models.dev/logos/groq.svg" in result.output
    assert any(character in result.output for character in "⠿⣿⠟⠛")


def test_providers_icon_prints_the_drawing_and_the_address(runner, monkeypatch):
    monkeypatch.delenv(logos.DISABLE_ENV, raising=False)
    monkeypatch.setattr(logos, "svg_text", lambda name, timeout=15: SQUARE)

    result = run(runner, ["providers", "icon", "groq"])

    assert result.exit_code == 0
    assert "https://models.dev/logos/groq.svg" in result.output
    assert any(character in result.output for character in "⠿⣿⠟⠛")


def test_providers_icon_unknown_provider(runner):
    result = run(runner, ["providers", "icon", "skynet"])
    assert result.exit_code == 1
    assert "unknown provider" in result.output


# ------------------------------------------------------------- box & colour
def test_provider_list_has_no_frame(runner, monkeypatch):
    """The list is plain rows: only the logo and the colour set it apart."""
    monkeypatch.delenv(logos.DISABLE_ENV, raising=False)
    monkeypatch.setattr(logos, "svg_text", lambda name, timeout=15: SQUARE)

    result = run(runner, ["providers", "list", "--search", "groq"])

    assert result.exit_code == 0
    assert "┌" not in result.output
    assert "│" not in result.output
    assert "└" not in result.output
    assert "groq" in result.output
    assert any(character in result.output for character in "⠿⣿⠟⠛")


def test_provider_accents_are_stable_and_varied():
    from nusa_rg import ui

    assert ui.provider_accent("groq") == ui.provider_accent("groq")
    assert ui.provider_accent("groq").startswith("\033[")
    colours = {ui.provider_accent(f"provider-{number}") for number in range(40)}
    assert len(colours) >= 8, "the palette must not collapse to a few colours"


def test_box_glyphs_fold_to_ascii(monkeypatch):
    from nusa_rg import ui

    monkeypatch.setattr(ui, "_utf8", lambda: False)
    assert ui.glyph("┌─┐│└┘") == "+-+|++"


def test_visible_width_ignores_escape_codes():
    from nusa_rg import ui

    previous = ui._COLOUR
    ui.set_colour(True)
    try:
        assert ui.visible_width(ui.paint("abc", ui.GREEN)) == 3
    finally:
        ui.set_colour(previous)
