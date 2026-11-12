"""Durable, output-scoped receipts for direct paid generation.

No credentials, prompts, response bodies or exception text are stored here.
"""
import hashlib
import json

from .durability import durable_write, sync_directory


def journal_path(output):
    return output.with_name(output.name + '.attempts.json')


def load(output):
    from .cli import read_local_bytes
    path = journal_path(output)
    if not path.exists() and not path.is_symlink():
        return {'version': 1, 'attempts': []}
    try:
        data = json.loads(read_local_bytes(path, 1024 * 1024, 'Generation journal'))
        if (not isinstance(data, dict) or data.get('version') != 1 or
                not isinstance(data.get('attempts'), list) or
                any(not isinstance(a, dict) or a.get('status') not in
                    {'started', 'unknown', 'succeeded'} for a in data['attempts'])):
            raise ValueError('invalid schema')
        return data
    except (ValueError, OSError) as exc:
        raise ValueError('Cannot read generation journal; preserve it and inspect before retrying') from exc


def check(output, force=False):
    data = load(output)
    if data['attempts'] and not force:
        raise ValueError('A paid generation attempt is already recorded for this output; '
                         'outcome/cost may be unknown. Review provider history, then use '
                         '--force only to authorize a new paid request. Use --resume for verified output.')
    return data


def save(output, data):
    raw = json.dumps(data, sort_keys=True, indent=2).encode('utf-8')
    if len(raw) > 1024 * 1024:
        raise ValueError('Generation journal is full; preserve and review it before another request')
    durable_write(journal_path(output), raw)


def create_directory(root):
    missing, parent = [], root
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    root.mkdir(parents=True, exist_ok=True)
    for directory in missing:
        sync_directory(directory.parent)


def start(output, payload, force=False):
    data = check(output, force)
    data['attempts'].append({'status': 'started', 'parameters_sha256': hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()})
    save(output, data)  # Must finish before the request can leave this process.
    return data
