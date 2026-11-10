"""Check author-declared story facts across shots, without interpreting images.

This is a sidecar ledger for a storyboard or film script. It makes no provider
calls, reads no credentials, and cannot establish visual or user acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

MAX_JSON_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 512 * 1024 * 1024
MAX_FACTS = 128
ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}')
FACT_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}\.[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}')


def read_regular(path, limit):
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Inputs must be regular local files')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'Input exceeds its {limit}-byte limit')
    return raw


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f'Duplicate JSON field: {key}')
        value[key] = item
    return value


def load_json(path):
    try:
        value = json.loads(read_regular(path, MAX_JSON_BYTES).decode('utf-8-sig'),
                           object_pairs_hook=unique_object)
        # Reject non-finite numbers, including those outside the fields we use.
        json.dumps(value, allow_nan=False)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Expected bounded UTF-8 JSON') from exc
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def digest_json(value):
    """Whitespace/key order/line-ending independent, not a raw file checksum."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def fields(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'{label}: expected an object with only documented fields')


def text(value, label, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label}: expected nonempty text, at most {limit} characters')
    return value


def sha(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError(f'{label}: expected lowercase SHA-256')
    return value


def local_input(root, name):
    text(name, 'Local source path', 4096)
    if '://' in name or '\x00' in name:
        raise ValueError('Sources must be local file paths, not URLs')
    return (root / name).resolve()


def story_inputs(path):
    """Read only the identity/order/source subset, not render request validity."""
    path = Path(path).resolve()
    story = load_json(path)
    if type(story.get('schema_version')) is not int or story['schema_version'] != 1:
        raise ValueError('story schema_version must be 1')
    shots = story.get('shots')
    if not isinstance(shots, list) or not 1 <= len(shots) <= 64:
        raise ValueError('story shots must contain 1..64 entries')
    seen, source_hashes, total, summaries = set(), {}, 0, []
    for shot in shots:
        if not isinstance(shot, dict):
            raise ValueError('Invalid story shot')
        sid = shot.get('id')
        if not isinstance(sid, str) or not ID.fullmatch(sid) or sid.lower() in seen:
            raise ValueError('Shot IDs must be unique safe ASCII identifiers')
        seen.add(sid.lower())
        kinds = set(shot) & {'source', 'generate', 'title', 'prompt'}
        if len(kinds) != 1:
            raise ValueError(f'{sid}: expected exactly one source, generate, title or prompt')
        kind = next(iter(kinds))
        if kind == 'source':
            raw = read_regular(local_input(path.parent, shot['source']), MAX_SOURCE_BYTES)
            total += len(raw)
            if total > MAX_TOTAL_SOURCE_BYTES:
                raise ValueError('Sources exceed the combined 512 MiB input budget')
            source_hashes[sid] = hashlib.sha256(raw).hexdigest()
            if 'source_sha256' in shot and sha(shot['source_sha256'], f'{sid}.source_sha256') != source_hashes[sid]:
                raise ValueError(f'{sid}: storyboard source SHA-256 mismatch')
        summaries.append({'shot_id': sid, 'kind': kind,
                          'action': shot.get('action', shot.get('caption', ''))})
    return story, summaries, source_hashes


def make_template(story_path):
    story, shots, hashes = story_inputs(story_path)
    return {'schema_version': 1, 'story_sha256': digest_json(story), 'source_hashes': hashes,
            'facts': [], 'shots': [{'shot_id': shot['shot_id'], 'requires': {},
                                   'changes': [], 'handoff_changes': []} for shot in shots]}


def check_story(story_path, ledger_path):
    story, shots, hashes = story_inputs(story_path)
    ledger = load_json(Path(ledger_path))
    fields(ledger, {'schema_version', 'story_sha256', 'source_hashes', 'facts', 'shots'}, 'ledger')
    if type(ledger.get('schema_version')) is not int or ledger['schema_version'] != 1:
        raise ValueError('ledger schema_version must be 1')
    if sha(ledger.get('story_sha256'), 'story_sha256') != digest_json(story):
        raise ValueError('Storyboard changed; reconcile a new ledger template before checking')
    if ledger.get('source_hashes') != hashes:
        raise ValueError('Source hashes changed or are incomplete; review changed footage and reconcile a new ledger')
    definitions = ledger.get('facts')
    if not isinstance(definitions, list) or len(definitions) > MAX_FACTS:
        raise ValueError('facts must contain at most 128 entries')
    values, fixed, origins, seen = {}, set(), {}, set()
    for definition in definitions:
        fields(definition, {'id', 'initial', 'fixed'}, 'fact')
        key = definition.get('id')
        if not isinstance(key, str) or not FACT_ID.fullmatch(key) or key.lower() in seen:
            raise ValueError('Fact IDs must be unique entity.attribute identifiers')
        seen.add(key.lower())
        values[key] = text(definition.get('initial'), f'{key}.initial')
        if type(definition.get('fixed', False)) is not bool:
            raise ValueError(f'{key}.fixed must be boolean')
        if definition.get('fixed', False):
            fixed.add(key)
        origins[key] = 'initial'
    entries = ledger.get('shots')
    if (not isinstance(entries, list) or len(entries) != len(shots)
            or [item.get('shot_id') if isinstance(item, dict) else None for item in entries]
            != [shot['shot_id'] for shot in shots]):
        raise ValueError('Ledger shots must cover every story shot exactly once, in story order')
    issues, timeline, unchecked, assertions, change_count = [], [], [], 0, 0

    def known_fact(key):
        if key not in values:
            raise ValueError(f'Undeclared fact: {key}')

    def apply_changes(changes, sid, phase):
        nonlocal change_count
        if not isinstance(changes, list) or len(changes) > MAX_FACTS:
            raise ValueError(f'{sid}.{phase} must be a list of at most 128 changes')
        used = set()
        for change in changes:
            fields(change, {'fact', 'from', 'to', 'reason'}, f'{sid}.{phase}')
            key = change.get('fact')
            text(key, 'Change fact', 81)
            known_fact(key)
            if key in used:
                raise ValueError(f'{sid}.{phase}: duplicate change for {key}')
            used.add(key)
            expected = text(change.get('from'), f'{sid}.{key}.from')
            after = text(change.get('to'), f'{sid}.{key}.to')
            text(change.get('reason'), f'{sid}.{key}.reason', 1000)
            problem = None
            if values[key] != expected:
                problem = 'change-from-mismatch'
            elif key in fixed and after != values[key]:
                problem = 'fixed-fact-change'
            if problem:
                issues.append({'shot_id': sid, 'phase': phase, 'fact': key, 'code': problem,
                               'carried': values[key], 'declared_from': expected, 'proposed': after,
                               'last_set_by': origins[key]})
                # Never repair an invalid change silently or propagate a false state.
                continue
            values[key], origins[key] = after, f'{sid}:{phase}'
            change_count += 1

    for shot, entry in zip(shots, entries):
        sid = shot['shot_id']
        fields(entry, {'shot_id', 'requires', 'changes', 'handoff_changes'}, sid)
        carried = dict(values)
        issue_start = len(issues)
        apply_changes(entry.get('handoff_changes', []), sid, 'handoff_changes')
        before = dict(values)
        required = entry.get('requires', {})
        if not isinstance(required, dict) or len(required) > MAX_FACTS:
            raise ValueError(f'{sid}.requires must be an object of at most 128 facts')
        for key, expected in required.items():
            known_fact(key)
            text(expected, f'{sid}.requires.{key}')
            assertions += 1
            if values[key] != expected:
                issues.append({'shot_id': sid, 'phase': 'requires', 'fact': key,
                               'code': 'requirement-mismatch', 'carried': values[key],
                               'required': expected, 'last_set_by': origins[key]})
        if not required:
            unchecked.append(sid)
        apply_changes(entry.get('changes', []), sid, 'changes')
        timeline.append({**shot, 'carried_in': carried, 'before': before, 'after': dict(values),
                         'last_set_by': dict(origins), 'declared_requirements': len(required),
                         'handoff_changes': entry.get('handoff_changes', []),
                         'changes': entry.get('changes', []), 'issue_count': len(issues) - issue_start})
    status = ('conflicts' if issues else 'untracked' if not values or not assertions
              else 'declared-facts-consistent')
    return {'schema_version': 1, 'provider_calls': 0, 'status': status,
            'story_sha256': digest_json(story), 'ledger_sha256': digest_json(ledger),
            'source_hashes': hashes, 'fact_count': len(values), 'requirement_count': assertions,
            'valid_change_count': change_count, 'shots_without_requirements': unchecked,
            'issues': issues, 'timeline': timeline, 'final_state': dict(values),
            'visual_acceptance': 'not-established',
            'scope': 'Author-declared string facts only. Unstated facts are not checked. Source hashes bind exact bytes, not their depicted contents. No image interpretation, story inference, rendering or provider calls.'}


def write_new(path, value):
    from . import cli
    path = Path(path)
    if os.path.lexists(path):
        raise ValueError('Output must be a new file; existing work is never overwritten')
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    cli.write_result(path, raw)


def initialize(args):
    template = make_template(args.story)
    write_new(args.output, template)
    print(json.dumps({'output': str(args.output), 'provider_calls': 0, 'status': 'untracked',
                      'note': 'Template only. Add author-declared facts and requirements before checking.'}, indent=2))


def check(args):
    result = check_story(args.story, args.ledger)
    if args.output:
        write_new(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] != 'declared-facts-consistent':
        raise SystemExit(2)


def add_parser(sub):
    parser = sub.add_parser('story-state', help='Track authored story facts; not visual continuity verification')
    commands = parser.add_subparsers(dest='story_state_command', required=True)
    init = commands.add_parser('init', help='Create a hash-pinned blank ledger; no inferred facts')
    init.add_argument('story', help='Version 1 storyboard or film script')
    init.add_argument('-o', '--output', required=True)
    init.set_defaults(func=initialize)
    check_parser = commands.add_parser('check', help='Report contradictory declared facts across the shot order')
    check_parser.add_argument('story')
    check_parser.add_argument('ledger')
    check_parser.add_argument('-o', '--output', help='Optional new JSON report file')
    check_parser.set_defaults(func=check)
