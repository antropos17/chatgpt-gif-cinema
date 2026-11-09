"""Pinned packaged fonts and fail-closed glyph coverage for layer text.

No system-font search, downloads, arbitrary font paths or shaping fallback.
Coverage manifests are generated offline from nonzero cmap glyph IDs and bound
by both their own SHA-256 and the exact font-byte SHA-256.
"""
from functools import lru_cache
from importlib import resources
import hashlib
import io
import json
from pathlib import Path
import unicodedata

LEGACY_FONT = 'pillow-default'
NOTO_FONT = 'noto-sans-regular-2.004'
FONTS = {
    LEGACY_FONT: {
        'sha256': '69853909b940023570964e29cffe30da95aea8de3627736b5cd15ab30143169f',
        'coverage': 'pillow-default-aileron.coverage.json',
        'coverage_sha256': '0bf4aedb68dccc08f1938f46e462ec2ebf04abd55557137b6556be0a4b0cd0ed',
        'license': 'Pillow bundled Aileron; font metadata: No Rights Reserved.'},
    NOTO_FONT: {
        'sha256': '89c3c497f618fdaa0b2d1e98fef93582f28c71debd2c4a8cdf41f190ced2909d',
        'file': 'NotoSans-Regular.ttf',
        'coverage': 'noto-sans-regular-2.004.coverage.json',
        'coverage_sha256': '9c4f199e73ab97edb72bbfbb8c8364100e0019dd59c218e4e1b106ba0df833c7',
        'license': 'SIL Open Font License 1.1; assets/fonts/OFL.txt'},
}


def _read_asset(name, limit):
    resource = resources.files('gif_cinema').joinpath('assets', 'fonts', name)
    try:
        if isinstance(resource, Path):
            # Reuse the regular-file/FIFO protection for unpacked wheels.
            from .layers import read_regular
            raw = read_regular(resource, limit)
        else:
            # A zipped package resource is read from its archive, not a font URL.
            if not resource.is_file():
                raise ValueError('Packaged font resource is missing')
            with resource.open('rb') as handle:
                raw = handle.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('Packaged font resource exceeds its byte budget')
    except (OSError, ValueError) as exc:
        raise ValueError(f'Cannot read packaged font resource {name}; reinstall this exact package') from exc
    return raw


def _descriptor(font_id):
    if not isinstance(font_id, str) or font_id not in FONTS:
        raise ValueError(f'font_id must be {LEGACY_FONT!r} or {NOTO_FONT!r}; font paths are not supported')
    return FONTS[font_id]


@lru_cache(maxsize=2)
def coverage(font_id):
    descriptor = _descriptor(font_id)
    raw = _read_asset(descriptor['coverage'], 64 * 1024)
    if hashlib.sha256(raw).hexdigest() != descriptor['coverage_sha256']:
        raise ValueError(f'Packaged glyph coverage changed for {font_id}')
    manifest = json.loads(raw)
    if manifest.get('font_sha256') != descriptor['sha256']:
        raise ValueError(f'Glyph coverage is not bound to the selected font {font_id}')
    return frozenset(manifest['codepoints'])


@lru_cache(maxsize=1)
def _noto_bytes():
    descriptor = FONTS[NOTO_FONT]
    raw = _read_asset(descriptor['file'], 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
        raise ValueError('Packaged Noto font checksum changed; refusing a silent replacement')
    return raw


def normalize_text_layer(layer):
    """Return explicit, stable text/font metadata before any raster allocation."""
    font_id = layer.get('font_id', LEGACY_FONT)
    descriptor = _descriptor(font_id)
    if layer.get('font_sha256', descriptor['sha256']) != descriptor['sha256']:
        raise ValueError(f'Scene font_sha256 does not match the packaged font {font_id}')
    text = unicodedata.normalize('NFC', layer['text'])
    unsupported = sorted({ord(c) for c in text if ord(c) not in coverage(font_id)
                          or unicodedata.category(c).startswith(('M', 'C'))})
    if unsupported:
        codes = ', '.join(f'U+{cp:04X}' for cp in unsupported[:8])
        hint = f'; for Russian/Azerbaijani choose font_id {NOTO_FONT!r}' if font_id == LEGACY_FONT else ''
        raise ValueError(f'Unsupported text for {font_id}: {codes}{hint}. No missing-glyph substitution is allowed')
    return {'text': text, 'font_id': font_id, 'font_sha256': descriptor['sha256']}


@lru_cache(maxsize=16)
def load_font(font_id, size):
    from PIL import ImageFont
    descriptor = _descriptor(font_id)
    if type(size) is not int or not 8 <= size <= 480:
        raise ValueError('Font raster size must be an integer in 8..480')
    if font_id == NOTO_FONT:
        font = ImageFont.truetype(io.BytesIO(_noto_bytes()), size=size, layout_engine=ImageFont.Layout.BASIC)
    else:
        try:
            font = ImageFont.load_default(size=size)
        except TypeError as exc:
            raise ValueError('Legacy text requires Pillow 10.1+ with the known bundled Aileron font') from exc
        raw = getattr(font, 'font_bytes', None)
        if raw is None or hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
            raise ValueError('This Pillow default font is not the recorded Aileron font; select the packaged Noto font explicitly')
        if font.layout_engine != ImageFont.Layout.BASIC:
            raise ValueError('Legacy font layout engine changed; refusing a silent text-layout change')
    return font


def renderer_identity():
    import PIL
    from PIL import features
    freetype = features.version_module('freetype2')
    if not freetype:
        raise ValueError('FreeType is required for reproducible text rendering')
    return {'layout_engine': 'BASIC', 'normalization': 'NFC', 'pillow': PIL.__version__, 'freetype': freetype}


def bind_renderer(scene):
    has_text = any(layer['type'] == 'text' for layer in scene['layers'])
    if not has_text:
        if 'text_renderer' in scene:
            raise ValueError('text_renderer requires at least one text layer')
        return
    current = renderer_identity()
    if scene.get('text_renderer', current) != current:
        raise ValueError('Saved text_renderer differs from this Pillow/FreeType environment; use the recorded versions or explicitly migrate the scene')
    scene['text_renderer'] = current


def font_receipt(scene):
    return {layer['font_id']: {'sha256': layer['font_sha256'], 'license': FONTS[layer['font_id']]['license']}
            for layer in scene['layers'] if layer['type'] == 'text'}
