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
mirror = ('primary' if 'https://archive.ubuntu.com/' in sources else
          'fallback' if 'https://azure.archive.ubuntu.com/' in sources else 'security')
with open(os.environ['TEST_APT_LOG'], 'a', encoding='utf-8') as log:
    log.write(json.dumps({'args': args, 'sources': sources, 'phase': phase, 'mirror': mirror}) + '\n')
scenario = os.environ['TEST_APT_SCENARIO']
if scenario == 'download_timeout' and phase == 'download' and mirror == 'primary':
    sys.exit(124)
if scenario == 'update_failure' and phase == 'update' and mirror == 'primary':
    sys.exit(100)
if scenario == 'all_fail' and phase == 'download':
    sys.exit(124)
if scenario == 'two_index_failures' and phase == 'update' and mirror != 'security':
    sys.exit(100)
if scenario == 'all_index_failures' and phase == 'update':
    sys.exit(100)
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
        self.brew_log = self.root / 'brew.jsonl'
        self.github_path = self.root / 'github-path'
        self.brew_prefix = self.root / 'homebrew' / 'opt' / 'ffmpeg'
        self.brew = self.root / 'homebrew' / 'bin' / 'brew'
        self.brew.parent.mkdir(parents=True)
        self.brew.write_text('#!' + sys.executable + '\n' + r'''
import json, os
from pathlib import Path
import sys
args = sys.argv[1:]
with open(os.environ['TEST_BREW_LOG'], 'a', encoding='utf-8') as log:
    log.write(json.dumps({'args': args, 'no_update': os.environ.get('HOMEBREW_NO_AUTO_UPDATE'),
                         'curl_retries': os.environ.get('HOMEBREW_CURL_RETRIES')}) + '\n')
scenario = os.environ['TEST_BREW_SCENARIO']
if scenario == 'install_failure' and args[0] == 'install':
    sys.exit(1)
if scenario == 'install_timeout' and args[0] == 'install':
    sys.exit(124)
if args[0] == '--prefix':
    if scenario == 'prefix_failure':
        sys.exit(1)
    print('relative/path' if scenario == 'relative_prefix' else
          '/outside/homebrew' if scenario == 'outside_prefix' else
          os.environ['TEST_BREW_PREFIX'] + ('\n/injected' if scenario == 'multiline_prefix' else ''))
    sys.exit(0)
if args == ['install', '--force-bottle', 'homebrew/core/ffmpeg']:
    bindir = Path(os.environ['TEST_BREW_PREFIX']) / 'bin'
    bindir.mkdir(parents=True)
    for tool in ('ffmpeg', 'ffprobe'):
        if scenario == 'missing_ffprobe' and tool == 'ffprobe':
            continue
        path = bindir / tool
        path.write_text('#!/bin/sh\nexit ' + ('7' if scenario == 'broken_executable' else '0') + '\n')
        path.chmod(0o755)
else:
    sys.exit(9)
''', encoding='utf-8')
        self.brew.chmod(0o755)
        timeout = self.bin / 'timeout'
        timeout.write_text('#!' + sys.executable + '\n' +
                           'import subprocess, sys\n'
                           'assert sys.argv[1:3] == ["--kill-after=5s", "300s"]\n'
                           'sys.exit(subprocess.run(sys.argv[3:]).returncode)\n', encoding='utf-8')
        timeout.chmod(0o755)

    def run_setup(self, scenario='success', existing=(), valid_host=True, unwind_work=False,
                  brew_scenario=None, github_actions=True, github_path=True, brew_override=None):
        for name in existing:
            tool = self.bin / name
            tool.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
            tool.chmod(0o755)
        env = dict(os.environ, PATH=str(self.bin), TMPDIR=str(self.root),
                   TEST_APT_LOG=str(self.log), TEST_APT_BIN=str(self.bin), TEST_APT_SCENARIO=scenario)
        # Host CI variables must never make an ordinary fixture try real Homebrew.
        env.pop('GITHUB_ACTIONS', None)
        env.pop('GITHUB_PATH', None)
        for variable in ('HOMEBREW_API_DOMAIN', 'HOMEBREW_BOTTLE_DOMAIN', 'HOMEBREW_ARTIFACT_DOMAIN',
                         'HOMEBREW_BREW_GIT_REMOTE', 'HOMEBREW_CORE_GIT_REMOTE', 'HOMEBREW_CURLRC'):
            env.pop(variable, None)
        if brew_override:
            env[brew_override] = 'https://example.invalid'
        brew_hook = ''
        if brew_scenario is not None:
            env.update(TEST_BREW=str(self.brew), TEST_BREW_LOG=str(self.brew_log),
                       TEST_BREW_PREFIX=str(self.brew_prefix), TEST_BREW_SCENARIO=brew_scenario)
            if github_actions:
                env['GITHUB_ACTIONS'] = 'true'
            if github_path:
                env['GITHUB_PATH'] = str(self.github_path)
            brew_hook = 'runner_homebrew_binary() { printf "%s\\n" "$TEST_BREW"; }; '
        # Mock only the host gate. Every orchestration branch runs as written.
        # Model older Bash unwinding the local before executing an EXIT trap.
        trap_hook = 'trap() { builtin trap "$@"; unset work; exit 47; }; ' if unwind_work else ''
        result = subprocess.run([shutil.which('bash'), '-c',
                                 'source "$1"; verify_ubuntu_host() { ' +
                                 (':' if valid_host else 'return 1') + '; }; ' + trap_hook + brew_hook +
                                 'install_ubuntu_ffmpeg',
                                 'ci-test', str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()] \
            if self.log.exists() else []
        self.assertFalse(list(self.root.glob('ffmpeg-apt.*')), 'temporary apt sources were retained')
        return result, calls

    def brew_calls(self):
        return [json.loads(line) for line in self.brew_log.read_text().splitlines()] \
            if self.brew_log.exists() else []

    def test_existing_tools_need_no_apt(self):
        result, calls = self.run_setup(existing=('ffmpeg', 'ffprobe'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    def test_cleanup_does_not_depend_on_local_variable_lifetime(self):
        result, calls = self.run_setup(unwind_work=True)
        self.assertEqual(result.returncode, 47, result.stderr)
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
        result, calls = self.run_setup('all_fail')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([(c['mirror'], c['phase']) for c in calls],
                         [('primary', 'update'), ('primary', 'download'),
                          ('fallback', 'update'), ('fallback', 'download'),
                          ('security', 'update'), ('security', 'download')])

    def test_two_index_failures_use_runner_security_archive_with_same_trust(self):
        result, calls = self.run_setup('two_index_failures')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([(c['mirror'], c['phase']) for c in calls],
                         [('primary', 'update'), ('fallback', 'update'),
                          ('security', 'update'), ('security', 'download'), ('security', 'install')])
        for call in calls[-3:]:
            self.assertIn('URIs: https://security.ubuntu.com/ubuntu', call['sources'])
            self.assertIn('Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg', call['sources'])
            self.assertIn('Suites: noble noble-updates noble-security', call['sources'])
            self.assertIn('Dir::Etc::sourceparts=-', call['args'])
            self.assertNotIn('--allow-unauthenticated', call['args'])
            self.assertNotIn('trusted=yes', call['sources'])
        self.assertIn('APT::Update::Error-Mode=any', calls[-3]['args'])
        self.assertEqual(calls[-1]['args'][0], 'apt-get')
        self.assertIn('--no-download', calls[-1]['args'])

    def test_all_index_failures_never_download_or_install(self):
        result, calls = self.run_setup('all_index_failures')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([(c['mirror'], c['phase']) for c in calls],
                         [('primary', 'update'), ('fallback', 'update'), ('security', 'update')])

    def test_failed_dpkg_install_is_not_retried_or_masked(self):
        result, calls = self.run_setup('install_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c['phase'] for c in calls], ['update', 'download', 'install'])

    def test_successful_apt_without_ffprobe_is_not_success(self):
        result, calls = self.run_setup('missing_ffprobe')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c['phase'] for c in calls], ['update', 'download', 'install'])

    def test_acquisition_exhaustion_uses_explicit_core_formula_and_persists_path(self):
        result, calls = self.run_setup('all_index_failures', brew_scenario='success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['phase'] for c in calls], ['update'] * 3)
        brew = self.brew_calls()
        self.assertEqual([c['args'] for c in brew],
                         [['install', '--force-bottle', 'homebrew/core/ffmpeg'],
                          ['--prefix', 'homebrew/core/ffmpeg']])
        self.assertEqual(brew[0]['no_update'], '1')
        self.assertEqual(brew[0]['curl_retries'], '1')
        self.assertEqual(self.github_path.read_text(), str(self.brew_prefix / 'bin') + '\n')

    def test_download_exhaustion_can_use_homebrew(self):
        result, calls = self.run_setup('all_fail', brew_scenario='success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 6)
        self.assertTrue(self.github_path.exists())

    def test_apt_success_never_runs_homebrew(self):
        result, _ = self.run_setup(brew_scenario='success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.brew_calls(), [])
        self.assertFalse(self.github_path.exists())

    def test_brew_append_preserves_existing_path_lines(self):
        self.github_path.write_text('/existing/tool/bin\n')
        result, _ = self.run_setup('all_index_failures', brew_scenario='success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.github_path.read_text(),
                         '/existing/tool/bin\n' + str(self.brew_prefix / 'bin') + '\n')

    def test_dpkg_failure_never_runs_homebrew(self):
        result, calls = self.run_setup('install_failure', brew_scenario='success')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c['phase'] for c in calls], ['update', 'download', 'install'])
        self.assertEqual(self.brew_calls(), [])
        self.assertFalse(self.github_path.exists())

    def test_partial_apt_result_never_runs_homebrew(self):
        result, _ = self.run_setup('missing_ffprobe', brew_scenario='success')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.brew_calls(), [])

    def test_invalid_host_never_runs_homebrew(self):
        result, calls = self.run_setup('all_index_failures', valid_host=False, brew_scenario='success')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertEqual(self.brew_calls(), [])

    def test_missing_github_context_never_runs_homebrew(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='success', github_actions=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.brew_calls(), [])
        result, _ = self.run_setup('all_index_failures', brew_scenario='success', github_path=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.brew_calls(), [])

    def test_unavailable_runner_homebrew_fails_closed(self):
        self.brew.chmod(0o644)
        result, _ = self.run_setup('all_index_failures', brew_scenario='success')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.brew_calls(), [])

    def test_failed_homebrew_install_is_not_retried_or_added_to_path(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='install_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.brew_calls()), 1)
        self.assertFalse(self.github_path.exists())

    def test_homebrew_timeout_is_not_retried(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='install_timeout')
        self.assertEqual(result.returncode, 124)
        self.assertEqual(len(self.brew_calls()), 1)
        self.assertFalse(self.github_path.exists())

    def test_registry_override_is_rejected(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='success',
                                   brew_override='HOMEBREW_BOTTLE_DOMAIN')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.brew_calls(), [])

    def test_failed_prefix_query_does_not_write_path(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='prefix_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.github_path.exists())

    def test_relative_prefix_does_not_write_path(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='relative_prefix')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.github_path.exists())

    def test_outside_prefix_does_not_write_path(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='outside_prefix')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.github_path.exists())

    def test_multiline_prefix_does_not_write_path(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='multiline_prefix')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.github_path.exists())

    def test_missing_brew_ffprobe_does_not_write_path(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='missing_ffprobe')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.github_path.exists())

    def test_broken_brew_executable_does_not_write_path(self):
        result, _ = self.run_setup('all_index_failures', brew_scenario='broken_executable')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.github_path.exists())

    def test_path_append_failure_fails_the_job(self):
        self.github_path.mkdir()
        result, _ = self.run_setup('all_index_failures', brew_scenario='success')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.brew_calls()), 2)


if __name__ == '__main__':
    unittest.main()
