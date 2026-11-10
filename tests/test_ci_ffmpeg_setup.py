"""Exercise CI setup orchestration without root, network, apt or system changes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/ci_install_ffmpeg_ubuntu.sh'


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'POSIX shell fixture required')
class UbuntuFFmpegSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ffmpeg setup '$; ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'
        for command in ('mktemp', 'chmod', 'rm'):
            (self.bin / command).symlink_to(shutil.which(command))
        sudo = self.bin / 'sudo'
        sudo.write_text('#!' + sys.executable + '\n' + r'''
import json, os
from pathlib import Path
import sys
args = sys.argv[1:]
source = next(Path(a.split('=', 1)[1]) for a in args if a.startswith('Dir::Etc::sourcelist='))
sources = source.read_text()
phase = 'update' if 'update' in args else ('download' if '--download-only' in args else 'install')
mirror = 'primary' if 'https://archive.ubuntu.com/' in sources else 'fallback'
with open(os.environ['TEST_APT_LOG'], 'a', encoding='utf-8') as log:
    log.write(json.dumps({'args': args, 'sources': sources, 'phase': phase, 'mirror': mirror}) + '\n')
scenario = os.environ['TEST_APT_SCENARIO']
if scenario == 'download_timeout' and phase == 'download' and mirror == 'primary':
    sys.exit(124)
if scenario == 'update_failure' and phase == 'update' and mirror == 'primary':
    sys.exit(100)
if scenario == 'both_fail' and phase == 'download':
    sys.exit(124)
if scenario == 'install_failure' and phase == 'install':
    sys.exit(100)
if phase == 'install':
    for tool in ('ffmpeg', 'ffprobe'):
        if scenario == 'missing_ffprobe' and tool == 'ffprobe':
            continue
        path = Path(os.environ['TEST_APT_BIN']) / tool
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o755)
''', encoding='utf-8')
        sudo.chmod(0o755)

    def run_setup(self, scenario='success', existing=(), valid_host=True, unwind_work=False):
        for name in existing:
            tool = self.bin / name
            tool.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
            tool.chmod(0o755)
        env = dict(os.environ, PATH=str(self.bin), TMPDIR=str(self.root),
                   TEST_APT_LOG=str(self.log), TEST_APT_BIN=str(self.bin), TEST_APT_SCENARIO=scenario)
        # Mock only the host gate. Every orchestration branch runs as written.
        # Model older Bash unwinding the local before executing an EXIT trap.
        trap_hook = 'trap() { builtin trap "$@"; unset work; }; ' if unwind_work else ''
        result = subprocess.run([shutil.which('bash'), '-c',
                                 'source "$1"; verify_ubuntu_host() { ' +
                                 (':' if valid_host else 'return 1') + '; }; ' + trap_hook +
                                 'install_ubuntu_ffmpeg',
                                 'ci-test', str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()] \
            if self.log.exists() else []
        self.assertFalse(list(self.root.glob('ffmpeg-apt.*')), 'temporary apt sources were retained')
        return result, calls

    def test_existing_tools_need_no_apt(self):
        result, calls = self.run_setup(existing=('ffmpeg', 'ffprobe'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    def test_cleanup_does_not_depend_on_local_variable_lifetime(self):
        result, calls = self.run_setup(unwind_work=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_rejected_host_does_not_start_apt(self):
        result, calls = self.run_setup(valid_host=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_partial_install_is_repaired_and_only_downloads_are_time_bounded(self):
        result, calls = self.run_setup(existing=('ffmpeg',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['phase'] for c in calls], ['update', 'download', 'install'])
        self.assertEqual(calls[0]['args'][:3], ['timeout', '--kill-after=5s', '90s'])
        self.assertEqual(calls[1]['args'][:3], ['timeout', '--kill-after=5s', '150s'])
        self.assertEqual(calls[2]['args'][0], 'apt-get')
        self.assertIn('--no-download', calls[2]['args'])
        for call in calls:
            self.assertIn('Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg', call['sources'])
            self.assertIn('Suites: noble noble-updates noble-security', call['sources'])
            self.assertIn('Dir::Etc::sourceparts=-', call['args'])
            self.assertNotIn('--allow-unauthenticated', call['args'])
            self.assertNotIn('trusted=yes', call['sources'])
        self.assertIn('APT::Update::Error-Mode=any', calls[0]['args'])

    def test_download_timeout_tries_one_official_fallback(self):
        result, calls = self.run_setup('download_timeout')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([(c['mirror'], c['phase']) for c in calls],
                         [('primary', 'update'), ('primary', 'download'),
                          ('fallback', 'update'), ('fallback', 'download'), ('fallback', 'install')])
        self.assertIn('URIs: https://azure.archive.ubuntu.com/ubuntu', calls[-1]['sources'])

    def test_failed_index_update_does_not_install_from_stale_lists(self):
        result, calls = self.run_setup('update_failure')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([(c['mirror'], c['phase']) for c in calls],
                         [('primary', 'update'), ('fallback', 'update'),
                          ('fallback', 'download'), ('fallback', 'install')])

    def test_exhausted_downloads_fail_without_installing(self):
        result, calls = self.run_setup('both_fail')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c['phase'] for c in calls], ['update', 'download', 'update', 'download'])

    def test_failed_dpkg_install_is_not_retried_or_masked(self):
        result, calls = self.run_setup('install_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c['phase'] for c in calls], ['update', 'download', 'install'])

    def test_successful_apt_without_ffprobe_is_not_success(self):
        result, calls = self.run_setup('missing_ffprobe')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c['phase'] for c in calls], ['update', 'download', 'install'])


if __name__ == '__main__':
    unittest.main()
