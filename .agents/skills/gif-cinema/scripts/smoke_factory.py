"""Build and independently audit the bundled offline collection; reviews stay pending."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch
import zipfile

sys.dont_write_bytecode = True

from gif_cinema import cli
import check_install


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def factory_cli(*arguments):
    """Use the same public parser and dispatcher as the installed command."""
    output = io.StringIO()
    with patch.object(sys, 'argv', ['gif-cinema', 'factory', *map(str, arguments)]), redirect_stdout(output):
        cli.main()
    return json.loads(output.getvalue())


def check_collection(root, manifest, plan, verification):
    """Audit this smoke's fresh collection against its pinned source plan.

    This helper also supports deliberate tampering tests. Runtime verification
    separately checks decoded GIFs, regenerated preview pixels and safe HTML.
    """
    root, manifest = Path(root), Path(manifest)
    catalog = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
    require(catalog['manifest_sha256'] == sha(manifest) == plan['manifest_sha256'],
            'Catalog does not identify the actual manifest')
    require(catalog['title'] == plan['title'] and catalog['provider_calls'] == 0 and
            catalog['visual_review'] == 'pending', 'Catalog changed its plan or review status')
    require('user acceptance remain pending' in catalog['notice'], 'Acceptance must remain pending')
    require([item['id'] for item in catalog['items']] == [entry['id'] for entry in plan['entries']],
            'Catalog item inventory differs from the plan')
    expected = {'index.html'}
    for entry, item in zip(plan['entries'], catalog['items']):
        sid = entry['id']
        paths = {'gif': f'gifs/{sid}.gif', 'poster': f'previews/{sid}-poster.png',
                 'sheet': f'previews/{sid}-sheet.png'}
        require(all(item[key] == value for key, value in paths.items()), 'Unexpected item paths')
        expected.update(paths.values())
        require(item['title'] == entry['title'] and
                item['group'] == entry.get('group', 'Collection') and
                item['caption'] == entry.get('caption', entry['title']), 'Item description changed')
        if entry['kind'] == 'gif':
            require((root / item['gif']).read_bytes() == (manifest.parent / entry['gif']).read_bytes(),
                    'Imported GIF bytes changed')
            require(item['gif_info'] == entry['expected'], 'Imported GIF metadata changed')
            provenance = {'kind': 'existing-gif', 'source_sha256': entry['sha256']}
        else:
            provenance = {'kind': 'local-layer-render', **entry['signature']}
            require(all(item['gif_info'][key] == entry['expected'][key]
                        for key in ('width', 'height', 'duration_ms')) and
                    item['gif_info']['loop'] == (0 if entry['expected']['loop'] else None),
                    'Scene output differs from planned dimensions, duration or loop')
        require(item['provenance'] == provenance, 'Input provenance changed')
    require(set(catalog['files']) == expected, 'Unexpected catalog file inventory')
    expected |= {'catalog.json', 'collection.zip'}
    actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
    require(actual == expected, 'Actual collection file inventory differs')
    require(not any(path.is_symlink() for path in root.rglob('*')), 'Collection contains a symlink')
    hashes = {}
    for name in sorted(expected):
        data = (root / name).read_bytes()
        record = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        hashes[name] = record
        if name in catalog['files']:
            require(record == catalog['files'][name], f'Output hash/length mismatch: {name}')
    require(verification['status'] == 'verified' and verification['provider_calls'] == 0 and
            verification['visual_review'] == 'pending' and
            verification['items'] == len(plan['entries']) and
            verification['files_verified'] == len(expected) - 1 and
            verification['zip_sha256'] == hashes['collection.zip']['sha256'],
            'CLI verification disagrees with actual collection')
    members = {'collection/' + name for name in expected - {'collection.zip'}}
    with zipfile.ZipFile(root / 'collection.zip') as archive:
        entries = archive.infolist()
        require(len(entries) == len(members) and {entry.filename for entry in entries} == members,
                'ZIP inventory must match exactly, without duplicate members')
        for entry in entries:
            require(not entry.is_dir() and entry.compress_type == zipfile.ZIP_STORED and
                    entry.date_time == (2026, 1, 1, 0, 0, 0) and entry.external_attr >> 16 == 0o100644,
                    'ZIP metadata changed')
            require(archive.read(entry) == (root / entry.filename.removeprefix('collection/')).read_bytes(),
                    f'ZIP member bytes differ: {entry.filename}')
    return {'files': hashes, 'output_hashes_verified': len(hashes),
            'zip_members_matched': len(members), 'visual_review': 'pending', 'user_acceptance': 'pending'}


def run(root):
    """Block Python networking/provider entry points even when imported by tests."""
    with patch('gif_cinema.cli.urlopen', side_effect=AssertionError('Network prohibited')), \
            patch('urllib.request.urlopen', side_effect=AssertionError('Network prohibited')), \
            patch('socket.socket', side_effect=AssertionError('Network prohibited')), \
            patch('gif_cinema.cli.request_gif', side_effect=AssertionError('Provider prohibited')):
        return _run(root)


def _run(root):
    root = Path(root).resolve()
    skill = Path(__file__).resolve().parents[1]
    require(not root.is_relative_to(skill), 'Smoke output belongs outside the installed skill directory')
    require(not root.exists(), 'Smoke output must be a new directory')
    require(all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')),
            'FFmpeg and ffprobe are required for the mixed GIF/scene factory smoke; use smoke_media.py for a no-encoder check')
    installation = {'package': check_install.verify_files(), 'runtime': check_install.check_runtime()}
    manifest = skill / 'assets/example/factory.json'
    inputs = [manifest, manifest.parent / 'shot-01.gif', manifest.parent / 'stroke-reveal.json']
    before = {path.name: sha(path) for path in inputs}
    collection = root / 'collection'
    with patch('subprocess.Popen', side_effect=AssertionError('Dry-run must not launch subprocesses')):
        plan = factory_cli('build', manifest, '--out', collection, '--dry-run')
    require(not root.exists() and plan['status'] == 'planned' and plan['provider_calls'] == 0 and
            plan['visual_review'] == 'pending', 'Dry-run wrote output or changed expected status')
    require([entry['kind'] for entry in plan['entries']] == ['gif', 'scene'], 'Mixed-input example changed')
    built = factory_cli('build', manifest, '--out', collection)
    verified = factory_cli('verify', collection)
    require(built == verified, 'Build and public verify disagree')
    audited = check_collection(collection, manifest, plan, verified)
    require(before == {path.name: sha(path) for path in inputs}, 'Bundled inputs changed')
    report = {'status': 'passed', 'provider_calls': 0, 'network': 'blocked in Python process',
              'ffmpeg_required': True, 'cli_entrypoint_checked': True, 'dry_run_no_output': True,
              'sources_unchanged': True, 'source_hashes': before, 'installation': installation,
              'collection': audited, 'visual_review': 'pending', 'user_acceptance': 'pending',
              'scope': 'Technical mixed-input collection and archive verification, not artistic acceptance.'}
    (root / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.out), indent=2))


if __name__ == '__main__':
    main()
