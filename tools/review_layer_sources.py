"""Review every selected native drawing from a verified layered export, offline.

This complements final-GIF review: source drawings precede scene transforms,
occlusion, output-grid sampling and encoding. It never records visual approval.
"""
import argparse
import html
import io
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw, __version__ as PILLOW_VERSION
from gif_cinema import layer_gifs, layer_sprites, layers, sprites
from tools.verify_layered_scene import unique_fields, verify

FORMAT = 'gif-cinema-native-source-review'
MAX_DRAWINGS = 512
MAX_NATIVE_PIXELS = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
PER_SHEET = 8
NOTICE = ('Native source drawings only: no scene placement, transforms, occlusion or final encoding. '
          'Review the delivered animation separately. Technical verification is not visual approval or user acceptance.')


def json_bytes(value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('Native review manifest exceeds JSON budget')
    return raw


def canonical(value):
    """JSON-type-aware equality: True, 1 and 1.0 are distinct manifest facts."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def load_export(directory):
    directory = Path(directory).resolve()
    # The existing verifier requires complete media/source/frame inventory and
    # rerenders every timeline PNG. A receipt alone cannot authorize this pack.
    verified = verify(directory)
    scene_raw = layers.read_regular(directory / 'editable/scene.json', layers.MAX_SCENE_BYTES)
    receipt_raw = layers.read_regular(directory / 'receipt.json', layers.MAX_RECEIPT_BYTES)
    receipt = json.loads(receipt_raw, object_pairs_hook=unique_fields)
    scene = layers.parse_scene(scene_raw)
    assets = layers.read_assets(scene, directory / 'editable')
    records, groups, total_pixels = [], [], 0
    for layer in scene['layers']:
        if layer['type'] not in ('gif', 'sprites'):
            continue
        asset = assets[layer['source']]
        sequence = asset if layer['type'] == 'gif' else layer_sprites.sequence(layer)
        selection = layer_gifs.selection_report(sequence, layer, 1000 // scene['fps'])
        start, end = selection['source_range_ms']
        starts = [0, *sequence['ends_ms'][:-1]]
        group = {'id': layer['id'], 'name': layer['name'], 'type': layer['type'],
                 'source_sha256': asset['sha256'], 'playback': layer['playback'],
                 'source_duration_ms': sequence['duration_ms'], **selection, 'drawings': []}
        for source_index, delay in zip(selection['selected_source_indices'], selection['selected_delays_ms']):
            size = (asset['frames'][source_index].size if layer['type'] == 'gif'
                    else layer['frames'][source_index]['rect'][2:])
            total_pixels += size[0] * size[1]
            index = len(records)
            if index >= MAX_DRAWINGS or total_pixels > MAX_NATIVE_PIXELS:
                raise ValueError('Native source review exceeds 512 drawings / 64 megapixel-frames; review a smaller scene or source range')
            record = {'index': index, 'layer_id': layer['id'], 'source_index': source_index,
                      'native_range_ms': [starts[source_index], sequence['ends_ms'][source_index]],
                      'included_range_ms': [max(start, starts[source_index]), min(end, sequence['ends_ms'][source_index])],
                      'duration_ms': delay, 'width': size[0], 'height': size[1],
                      'sampled_in_export': source_index in selection['sampled_source_indices'],
                      'filename': f'drawings/{index:04}.png'}
            records.append(record); group['drawings'].append(index)
        groups.append(group)
    if not groups:
        raise ValueError('Native source review requires at least one GIF or sprite layer')
    facts = {'format': FORMAT, 'schema_version': 1, 'visual_review': 'pending', 'user_acceptance': 'pending',
             'api_calls': 0, 'notice': NOTICE, 'title': scene['title'],
             'review_renderer': {'pillow': PILLOW_VERSION, 'thumbnail_sampling': 'Lanczos', 'sheet_schema': 1},
             'export_receipt_sha256': layers.digest(receipt_raw), 'scene_sha256': layers.digest(scene_raw),
             'preview_sha256': {name: receipt['outputs'][name] for name in ('preview.gif', 'preview.mp4')},
             'verified_export_frames': verified['frames_reopened_and_matched'],
             'native_pixel_frames': total_pixels, 'drawing_count': len(records),
             'layers': groups, 'drawings': records}
    return facts, scene, assets


def drawing(record, scene, assets):
    layer = next(layer for layer in scene['layers'] if layer['id'] == record['layer_id'])
    asset = assets[layer['source']]
    if layer['type'] == 'gif':
        return asset['frames'][record['source_index']]
    x, y, width, height = layer['frames'][record['source_index']]['rect']
    return asset['rgba'].crop((x, y, x + width, y + height))


def sheet_specs(facts):
    for group in facts['layers']:
        for start in range(0, len(group['drawings']), PER_SHEET):
            yield f'sheets/{group["id"]}-{start // PER_SHEET:03}.png', group['drawings'][start:start + PER_SHEET]


def sheet_image(indices, facts, scene, assets):
    # At most eight paired thumbnails; full-resolution drawings remain separate.
    sheet = Image.new('RGB', (816, ((len(indices) + 1) // 2) * 232), '#dce3ee')
    pen = ImageDraw.Draw(sheet)
    for offset, index in enumerate(indices):
        record = facts['drawings'][index]
        frame = drawing(record, scene, assets)
        thumb = frame.copy(); thumb.thumbnail((192, 192), Image.Resampling.LANCZOS)
        x, y = (offset % 2) * 408 + 6, (offset // 2) * 232 + 6
        label = f'{record["layer_id"]} / source {record["source_index"]} / {record["duration_ms"]} ms'
        pen.text((x, y), label, fill='#111827')
        for side, color in enumerate(('#ffffff', '#111827')):
            panel = Image.new('RGB', (192, 192), color)
            panel.paste(thumb, ((192 - thumb.width) // 2, (192 - thumb.height) // 2), thumb.getchannel('A'))
            sheet.paste(panel, (x + side * 198, y + 25))
    return sheet


def player(facts):
    # Paths/IDs are generated; author text is escaped or assigned through textContent.
    data = json.dumps({'layers': facts['layers'], 'drawings': facts['drawings']}, ensure_ascii=True).replace('<', '\\u003c')
    links = ' · '.join(f'<a href="{name}">{html.escape(name)}</a>' for name, _ in sheet_specs(facts))
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Native layer drawing review</title><style>
body{font:16px system-ui;background:#172030;color:#edf4ff;margin:24px}a{color:#a9d7ff}button,select{font:inherit;margin:4px;padding:8px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.view{overflow:auto;min-height:240px;padding:12px}.light{background:white}.dark{background:#111827}
img{display:block;max-width:100%;height:auto;margin:auto}body.native img{max-width:none}.note{max-width:1100px;color:#ced9e8}@media(max-width:700px){.pair{grid-template-columns:1fr}}
</style><h1>Native layer drawings</h1><p>TITLE</p><p class="note">NOTICE</p><p>SHEETS</p>
<label>Layer <select id="layer"></select></label><button id="prev">Previous</button><button id="next">Next</button><button id="play">Play selected interval</button>
<label><input type="checkbox" id="repeat">Repeat selected interval</label><label><input type="checkbox" id="native">Native display size</label>
<p id="status" aria-live="polite"></p><p><a id="original" target="_blank" rel="noopener">Open native RGBA PNG</a></p>
<div class="pair"><div class="view light"><img id="light" alt="Native drawing on white"></div><div class="view dark"><img id="dark" alt="Native drawing on dark blue"></div></div>
<p class="note">The player starts paused. Source holds at trim boundaries may be shorter than original holds. Playback is a browser preview, not the final scene timeline; slow devices may skip scheduled updates. Step through every drawing and inspect native pixels. Manual stepping wraps for seam inspection. No approval is recorded here.</p>
<script>const data=DATA;const el=id=>document.getElementById(id);let layer=0,position=0,timer=null,playing=false;
function row(){return data.drawings[data.layers[layer].drawings[position]];}
function draw(){const r=row();for(const id of ['light','dark'])el(id).src=r.filename;el('original').href=r.filename;el('status').textContent='Source index '+r.source_index+' | included '+r.included_range_ms.join('..')+' ms | '+r.duration_ms+' ms hold | '+(r.sampled_in_export?'sampled in export':'NOT sampled in export')+' | '+r.width+' x '+r.height;}
function stop(){clearTimeout(timer);timer=null;playing=false;el('play').textContent='Play selected interval';}
function schedule(){timer=setTimeout(()=>{if(position===data.layers[layer].drawings.length-1&&!el('repeat').checked){stop();return;}position=(position+1)%data.layers[layer].drawings.length;draw();schedule();},row().duration_ms);}
for(let i=0;i<data.layers.length;i++){const option=document.createElement('option');option.value=i;option.textContent=data.layers[i].name+' ('+data.layers[i].drawings.length+' drawings)';el('layer').appendChild(option);}
function select(){stop();layer=Number(el('layer').value);position=0;el('repeat').checked=data.layers[layer].playback==='loop';draw();}el('layer').onchange=select;
for(const [id,step] of [['prev',-1],['next',1]])el(id).onclick=()=>{stop();position=(position+step+data.layers[layer].drawings.length)%data.layers[layer].drawings.length;draw();};
el('play').onclick=()=>{if(playing){stop();return;}playing=true;el('play').textContent='Pause';schedule();};el('native').onchange=()=>document.body.classList.toggle('native',el('native').checked);document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});select();</script></html>'''
    # One template pass only: author strings resembling placeholders must never
    # undergo another substitution after being escaped/JSON-encoded.
    replacements = {'DATA': data, 'SHEETS': links, 'NOTICE': html.escape(NOTICE), 'TITLE': html.escape(facts['title'])}
    return re.sub(r'\b(?:DATA|SHEETS|NOTICE|TITLE)\b', lambda match: replacements[match[0]], page).encode('utf-8')


def extract(render_directory, output, *, dry_run=False):
    output = Path(output).absolute()
    if output.exists() or any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError('Native review output must be a new directory without symlinks')
    if type(dry_run) is not bool:
        raise ValueError('dry_run must be boolean')
    # Verification can take time. Do not silently adopt a parent that was
    # renamed, replaced or turned into a symlink while it ran.
    ancestors = {path: sprites.directory_identity(path) if path.exists() else None for path in output.parents}
    def check_ancestors():
        for path, identity in ancestors.items():
            if identity is None:
                if path.exists() or path.is_symlink():
                    raise ValueError('Native review output ancestor changed during verification')
            elif sprites.directory_identity(path) != identity:
                raise ValueError('Native review output ancestor changed during verification')
    facts, scene, assets = load_export(render_directory)
    check_ancestors()
    if dry_run:
        return {**facts, 'status': 'planned'}
    for path in reversed(output.parents):
        if ancestors[path] is None:
            check_ancestors(); path.mkdir(exist_ok=False)
            ancestors[path] = sprites.directory_identity(path)
    check_ancestors(); output.mkdir(exist_ok=False)
    identities = {**ancestors, output: sprites.directory_identity(output)}
    artifacts, total = {}, 0
    def identity_check():
        for path, identity in identities.items():
            if sprites.directory_identity(path) != identity:
                raise ValueError('Native review output directory changed; partial data retained')
    def save(name, raw, track=True):
        nonlocal total
        identity_check(); path = output / name
        if path.parent not in identities:
            path.parent.mkdir(exist_ok=False)
            identities[path.parent] = sprites.directory_identity(path.parent)
        identity_check(); total += len(raw)
        if total > MAX_OUTPUT_BYTES:
            raise ValueError('Native review output exceeds 512 MiB; partial data retained')
        with path.open('xb') as handle:
            handle.write(raw)
        if track:
            artifacts[name] = layers.digest(raw)
    def save_image(name, image):
        stream = io.BytesIO(); image.save(stream, format='PNG'); save(name, stream.getvalue())
    for record in facts['drawings']:
        frame = drawing(record, scene, assets)
        record['rgba_sha256'] = layers.digest(frame.tobytes())
        save_image(record['filename'], frame)
    for name, indices in sheet_specs(facts):
        save_image(name, sheet_image(indices, facts, scene, assets))
    save('index.html', player(facts))
    # Reuse complete export verification again before writing the completion
    # manifest. A changed final export must not receive a completed review pack.
    current, _, _ = load_export(render_directory)
    initial = {**facts, 'drawings': [{k: v for k, v in row.items() if k != 'rgba_sha256'} for row in facts['drawings']]}
    if canonical(current) != canonical(initial):
        raise ValueError('Layered export changed during native review; partial data retained')
    identity_check()
    save('manifest.json', json_bytes({**facts, 'artifacts': artifacts}), track=False)
    identity_check()
    return {**facts, 'artifacts': artifacts, 'status': 'prepared'}


def check(render_directory, output):
    output = Path(output).resolve()
    raw = layers.read_regular(output / 'manifest.json', MAX_JSON_BYTES)
    manifest = json.loads(raw, object_pairs_hook=unique_fields)
    if not isinstance(manifest, dict):
        raise ValueError('Native review manifest must be an object')
    facts, scene, assets = load_export(render_directory)
    if manifest.get('review_renderer') != facts['review_renderer']:
        raise ValueError('Native review renderer differs; use its original Pillow version or extract a new review')
    for record in facts['drawings']:
        record['rgba_sha256'] = layers.digest(drawing(record, scene, assets).tobytes())
    artifacts = manifest.get('artifacts')
    if canonical({key: value for key, value in manifest.items() if key != 'artifacts'}) != canonical(facts):
        raise ValueError('Native review facts differ from the verified layered export')
    names = {'index.html'} | {row['filename'] for row in facts['drawings']} | {name for name, _ in sheet_specs(facts)}
    if not isinstance(artifacts, dict) or set(artifacts) != names:
        raise ValueError('Native review artifact inventory is incomplete or unexpected')
    total = len(raw)
    if total > MAX_OUTPUT_BYTES:
        raise ValueError('Native review exceeds output byte budget')
    def read(name):
        nonlocal total
        path = output / name
        if path.is_symlink() or not path.resolve().is_relative_to(output):
            raise ValueError('Native review artifact escapes its output directory')
        value = layers.read_regular(path, 32 * 1024 * 1024)
        total += len(value)
        if total > MAX_OUTPUT_BYTES:
            raise ValueError('Native review exceeds output byte budget')
        expected = artifacts[name]
        if not isinstance(expected, str) or re.fullmatch(r'[0-9a-f]{64}', expected) is None or layers.digest(value) != expected:
            raise ValueError(f'Native review artifact changed: {name}')
        return value
    def verify_image(name, expected):
        with Image.open(io.BytesIO(read(name))) as image:
            if image.format != 'PNG' or image.size != expected.size or image.mode != expected.mode or getattr(image, 'n_frames', 1) != 1:
                raise ValueError(f'Native review PNG metadata changed: {name}')
            if image.tobytes() != expected.tobytes():
                raise ValueError(f'Native review PNG pixels differ from source: {name}')
            # Generated drawings/sheets carry no display metadata. Equal RGBA
            # alone misses EXIF rotation or color profiles affecting a viewer.
            # Check after load(), including chunks stored after image data.
            if image.info:
                raise ValueError(f'Native review PNG has unexpected display metadata: {name}')
    if read('index.html') != player(facts):
        raise ValueError('Native review player differs from source facts')
    for row in facts['drawings']:
        verify_image(row['filename'], drawing(row, scene, assets))
    for name, indices in sheet_specs(facts):
        verify_image(name, sheet_image(indices, facts, scene, assets))
    return {'status': 'verified', 'api_calls': 0, 'drawings_verified': len(facts['drawings']),
            'artifacts_verified': len(names), 'visual_review': 'pending', 'user_acceptance': 'pending', 'notice': NOTICE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('extract', 'check'):
        command = commands.add_parser(name)
        command.add_argument('render_directory', type=Path)
        command.add_argument('review_directory', type=Path)
        if name == 'extract':
            command.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = (extract(args.render_directory, args.review_directory, dry_run=args.dry_run)
                  if args.command == 'extract' else check(args.render_directory, args.review_directory))
        print(json.dumps(report, indent=2, ensure_ascii=False)); return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Error: {error}', file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
