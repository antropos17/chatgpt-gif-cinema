"""Installed-resource backend proof; fake verification is never reported as a real pass."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'.agents/skills/gif-cinema/scripts'


def load_smoke():
    with patch.object(sys,'path',[str(SCRIPTS),*sys.path]):
        spec=importlib.util.spec_from_file_location('installed_backend_smoke',SCRIPTS/'smoke_backend.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@unittest.skipUnless(importlib.util.find_spec('av') and shutil.which('ffmpeg') and shutil.which('ffprobe'),'PyAV/FFmpeg required')
class BackendSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.smoke=load_smoke()

    def test_real_native_and_gfc_exports_and_completed_resume(self):
        out=self.root/'proof';report=self.smoke.run(out)
        self.assertEqual(report['status'],'passed');self.assertIs(type(report['provider_calls']),int)
        self.assertEqual(report['provider_calls'],0)
        self.assertEqual(report['gfc']['holds_ms'],[10,30,150])
        self.assertEqual(report['native']['frames'],30)
        self.assertEqual(json.loads((out/'verification.json').read_text()),report)
        before={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError,'new directory'):self.smoke.run(out)
        self.assertEqual(before,{p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()})
        # Direct oracle rejects a changed pixel expectation rather than trusting receipt hashes.
        expected=[b'\0'*(256*256*4)]*3
        with self.assertRaisesRegex(ValueError,'RGBA mismatch'):self.smoke.verify_gfc(out/'editor',expected)

    def test_verification_failure_never_publishes_pass_marker_and_preserves_source(self):
        out=self.root/'failed';observed={};ordinary=self.smoke.make_sources
        def sources(root):
            result=ordinary(root);observed['gfc']=(root/'working.gfc').read_bytes();return result
        with patch.object(self.smoke,'make_sources',sources),patch.object(self.smoke,'verify_gfc',side_effect=ValueError('injected pixel mismatch')):
            with self.assertRaisesRegex(ValueError,'injected pixel mismatch'):self.smoke.run(out)
        self.assertFalse((out/'verification.json').exists())
        self.assertEqual((out/'working.gfc').read_bytes(),observed['gfc'])
        self.assertFalse((out/'native').exists())

    def test_changed_sources_never_publish_pass_marker(self):
        out=self.root/'changed';ordinary=self.smoke.verify_native
        def verify(output,project):
            result=ordinary(output,project)
            (output.parent/'working.gfc').write_bytes(b'intentionally changed test source')
            return result
        with patch.object(self.smoke,'verify_native',verify):
            with self.assertRaisesRegex(ValueError,'sources changed'):self.smoke.run(out)
        self.assertFalse((out/'verification.json').exists())

    def test_public_cli_dispatch_failure_cannot_publish_success(self):
        out=self.root/'dispatch-failed';calls=[]
        def refused():
            calls.append(sys.argv[:])
            raise AssertionError('injected public CLI dispatch failure')
        with patch.object(self.smoke.cli,'main',refused):
            with self.assertRaisesRegex(AssertionError,'public CLI dispatch failure'):self.smoke.run(out)
        self.assertEqual(calls,[['gif-cinema','sequence','build',str(out/'native.json'),'--out',str(out/'native')]])
        self.assertTrue((out/'working.gfc').is_file())
        self.assertFalse((out/'native').exists())
        self.assertFalse((out/'verification.json').exists())

    def test_dependency_failure_precedes_fixture_creation(self):
        out=self.root/'missing'
        with patch.object(self.smoke.check_install,'check_runtime',side_effect=ValueError('missing codec')):
            with self.assertRaisesRegex(ValueError,'missing codec'):self.smoke.run(out)
        self.assertFalse(out.exists())

    def test_dotdot_alias_into_skill_rejected_before_any_mkdir(self):
        skill=SCRIPTS.parent
        out=skill.parent/'unused-intermediate'/'..'/skill.name/'should-not-write'
        with patch.object(Path,'mkdir',side_effect=AssertionError('must not create directories')) as mkdir:
            with self.assertRaisesRegex(ValueError,'outside the installed skill'):self.smoke.run(out)
        mkdir.assert_not_called()

    def test_dotdot_outside_skill_is_accepted_for_real_export(self):
        # Canonicalize an owned temporary root, not a supplied source filename.
        out=self.root/'unused-intermediate'/'..'/'outside-proof'
        report=self.smoke.run(out)
        self.assertEqual(report['status'],'passed')
        self.assertTrue((self.root/'outside-proof'/'verification.json').is_file())
        self.assertFalse((self.root/'unused-intermediate').exists())

    def test_skill_or_symlink_destination_rejected(self):
        with self.assertRaisesRegex(ValueError,'outside the installed skill'):self.smoke.run(SCRIPTS/'should-not-exist')
        link=self.root/'alias'
        try:link.symlink_to(self.root,target_is_directory=True)
        except OSError:self.skipTest('symlinks unavailable')
        with self.assertRaisesRegex(ValueError,'symlinks'):self.smoke.run(link/'should-not-exist')
        self.assertFalse((self.root/'should-not-exist').exists())


if __name__=='__main__':unittest.main()
