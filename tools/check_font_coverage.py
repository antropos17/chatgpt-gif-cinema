"""Developer-only exact cmap audit; fontTools is not a runtime dependency."""
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import ImageFont
from gif_cinema import text_fonts


def main():
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        raise SystemExit('This optional development audit needs fontTools; runtime rendering does not.')
    rows = []
    for font_id, descriptor in text_fonts.FONTS.items():
        raw = (ROOT / 'gif_cinema' / 'assets' / 'fonts' / descriptor['file']).read_bytes() if 'file' in descriptor else ImageFont.load_default(size=12).font_bytes
        with TTFont(io.BytesIO(raw)) as font:
            actual = {cp for cp, glyph in font.getBestCmap().items() if font.getGlyphID(glyph) != 0}
        if hashlib.sha256(raw).hexdigest() != descriptor['sha256'] or actual != text_fonts.coverage(font_id):
            raise SystemExit(f'Font bytes or exact cmap coverage changed: {font_id}')
        rows.append({'font_id': font_id, 'sha256': descriptor['sha256'], 'nonzero_cmap_codepoints': len(actual)})
    print(json.dumps({'status': 'verified', 'fonts': rows}, indent=2))


if __name__ == '__main__':
    main()
