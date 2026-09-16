"""Verify the shared palette's readable text and status combinations."""
from pathlib import Path
import re
import pytest

CSS = (Path(__file__).parents[1] / 'app/static/theme.css').read_text()
PALETTES = [dict(re.findall(r'--theme-([\w-]+):\s*(#[0-9a-f]{6});', block))
            for block in re.findall(r':root(?:\[data-theme="night"\])?\s*\{([^}]+)', CSS)]


def luminance(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


def contrast(a, b):
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


@pytest.mark.parametrize('palette', PALETTES, ids=['day', 'night'])
def test_theme_text_and_status_contrast(palette):
    for text in ('text', 'muted'):
        for surface in ('canvas', 'surface', 'raised'):
            assert contrast(palette[text], palette[surface]) >= 4.5, (text, surface)
    for tone in ('accent', 'success', 'danger', 'warning', 'lavender'):
        assert contrast(palette[tone], palette[tone + '-soft']) >= 4.5, tone
        assert contrast(palette[tone], palette['on-accent']) >= 4.5, tone
