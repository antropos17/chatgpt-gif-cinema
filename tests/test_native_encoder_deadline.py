"""Bound actual pipe stalls without timing frame generation or changing exports."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from gif_cinema import shots
from test_native_shots import fixture


class PipeDeadlineTests(unittest.TestCase):
    def external(self, body):
        code = "import sys,time,json,threading\nfrom unittest.mock import patch\nfrom PIL import Image\nfrom gif_cinema import shots\n"+body
        child = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        try:
            out, err = child.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            if os.name == 'posix': os.killpg(child.pid, signal.SIGKILL)
            else: child.kill()
            child.communicate()
            self.fail('Outer safety guard fired; encoder input did not return')
        self.assertEqual(child.returncode, 0, err.decode(errors='replace'))
        return json.loads(out)

    def test_real_full_pipe_write_expires_and_closes_generator(self):
        row = self.external('''closed=[]
def images():
 try: yield Image.new('RGB',(1024,1024))
 finally: closed.append(True)
t=time.monotonic()
with patch.object(shots,'ENCODER_PIPE_TIMEOUT',.15):
 try: shots.encode([sys.executable,'-c','import time;time.sleep(30)'],images())
 except TimeoutError as e: error=str(e)
 else: raise AssertionError('no timeout')
print(json.dumps(dict(error=error,elapsed=time.monotonic()-t,closed=closed,workers=[x.name for x in threading.enumerate() if x.name=='gif-cinema-encoder-io'])))
''')
        self.assertIn('write exceeded 0.15 seconds', row['error'])
        self.assertLess(row['elapsed'], 5); self.assertEqual(row['closed'], [True]); self.assertEqual(row['workers'], [])

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux pipe capacity API required')
    def test_real_buffered_close_expires_not_just_frame_writes(self):
        row = self.external('''import fcntl
real=shots.subprocess.Popen;holder=[]
def launch(*a,**kw):
 p=real(*a,**kw);holder.append(p);return p
class Bytes:
 def __init__(self,n):self.n=n
 def tobytes(self):return b'x'*self.n
def images():
 yield Bytes(fcntl.fcntl(holder[0].stdin.fileno(),fcntl.F_GETPIPE_SZ))
 yield Bytes(1)
t=time.monotonic()
with patch.object(shots,'ENCODER_PIPE_TIMEOUT',.15),patch.object(shots.subprocess,'Popen',launch):
 try:shots.encode([sys.executable,'-c','import time;time.sleep(30)'],images())
 except TimeoutError as e:error=str(e)
 else:raise AssertionError('no timeout')
print(json.dumps(dict(error=error,elapsed=time.monotonic()-t,exited=holder[0].poll() is not None)))
''')
        self.assertIn('close exceeded 0.15 seconds', row['error']); self.assertTrue(row['exited']); self.assertLess(row['elapsed'], 5)

    def test_slow_generation_and_serialization_are_not_pipe_deadlines(self):
        row = self.external('''class Slow:
 def tobytes(self):time.sleep(.15);return b'abc'
def images():
 for _ in range(2):time.sleep(.15);yield Slow()
with patch.object(shots,'ENCODER_PIPE_TIMEOUT',.1):
 shots.encode([sys.executable,'-c','import sys;assert len(sys.stdin.buffer.read())==6'],images())
print(json.dumps(dict(workers=[x.name for x in threading.enumerate() if x.name=='gif-cinema-encoder-io'])))
''')
        self.assertEqual(row['workers'], [])

    def test_concurrent_encoders_have_independent_deadlines_and_cleanup(self):
        row = self.external("""results=[]
def stalled():
 try:shots.encode([sys.executable,'-c','import time;time.sleep(30)'],[Image.new('RGB',(1024,1024))])
 except TimeoutError:results.append('timeout')
def healthy():
 class Bytes:
  def tobytes(self):return b'abc'
 def frames():time.sleep(.3);yield Bytes()
 shots.encode([sys.executable,'-c','import sys;assert sys.stdin.buffer.read()==b"abc"'],frames())
 results.append('success')
with patch.object(shots,'ENCODER_PIPE_TIMEOUT',.15):
 threads=[threading.Thread(target=fn) for fn in (stalled,healthy)]
 for thread in threads:thread.start()
 for thread in threads:thread.join()
print(json.dumps(dict(results=sorted(results),workers=[x.name for x in threading.enumerate() if x.name=='gif-cinema-encoder-io'])))
""")
        self.assertEqual(row['results'],['success','timeout']);self.assertEqual(row['workers'],[])

    def test_disarm_cancels_expiry_and_each_operation_gets_its_own_deadline(self):
        process = Mock()
        with shots._EncoderPipeDeadline(process, .1) as deadline:
            for _ in range(12): deadline.call('write', time.sleep, .01)
            time.sleep(.15)  # More than one IO deadline while not writing.
            deadline.call('close', lambda: None)
        process.kill.assert_not_called(); self.assertFalse(deadline.thread.is_alive())

    def test_expiry_is_not_replaced_by_broken_pipe_or_reused_for_next_operation(self):
        process = Mock(); released = threading.Event(); process.kill.side_effect = released.set
        def blocked():
            self.assertTrue(released.wait(2)); raise BrokenPipeError('killed encoder')
        with shots._EncoderPipeDeadline(process, .05) as deadline:
            with self.assertRaisesRegex(TimeoutError, 'write exceeded') as error: deadline.call('write', blocked)
            self.assertIsInstance(error.exception.__cause__, BrokenPipeError)
            operation = Mock()
            with self.assertRaises(TimeoutError): deadline.call('write', operation)
            operation.assert_not_called()
        process.kill.assert_called_once(); self.assertFalse(deadline.thread.is_alive())

    def test_source_and_pipe_errors_and_keyboard_interrupt_stop_watchdog(self):
        for error in (ValueError('source'), BrokenPipeError('pipe'), KeyboardInterrupt()):
            process = Mock()
            with self.assertRaises(type(error)):
                with shots._EncoderPipeDeadline(process, 1) as deadline:
                    deadline.call('write', Mock(side_effect=error))
            process.kill.assert_not_called(); self.assertFalse(deadline.thread.is_alive())

    def test_expired_success_return_still_raises_timeout(self):
        process = Mock(); released = threading.Event(); process.kill.side_effect = released.set
        with shots._EncoderPipeDeadline(process, .05) as deadline:
            with self.assertRaises(TimeoutError): deadline.call('write', released.wait, 2)
        process.kill.assert_called_once()

    def test_watchdog_start_failure_still_reaps_child_and_closes_iterator(self):
        process = Mock(); process.poll.return_value = None
        # A closeable iterator, not a generator that has never been entered.
        class Input:
            closed = False
            def __iter__(self): return self
            def __next__(self): raise StopIteration
            def close(self): self.closed = True
        images = Input()
        with patch.object(shots.subprocess, 'Popen', return_value=process), patch.object(shots.threading.Thread, 'start', side_effect=RuntimeError('thread start failed')):
            with self.assertRaisesRegex(RuntimeError, 'thread start failed'): shots.encode(['test'], images)
        process.terminate.assert_called_once(); process.wait.assert_called_once_with(timeout=5)
        process.stdin.close.assert_called_once(); self.assertTrue(images.closed)

    def test_benchmark_rejects_unknown_reference_before_execution(self):
        path = Path(__file__).resolve().parents[1]/'tools/benchmark_encoder_deadline.py'
        spec = importlib.util.spec_from_file_location('deadline_benchmark', path)
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td).resolve()/'bad.py'; bad.write_text('raise AssertionError("must not execute")')
            with self.assertRaisesRegex(ValueError, 'exact 658e446'): tool.reference(bad)

    def test_successful_io_does_not_terminate_encoder(self):
        process = Mock()
        with shots._EncoderPipeDeadline(process, 1) as deadline:
            self.assertEqual(deadline.call('write', lambda x: len(x), b'abcd'), 4)
        process.kill.assert_not_called(); self.assertFalse(deadline.thread.is_alive())


@unittest.skipUnless(shutil.which('ffmpeg') and importlib.util.find_spec('av'), 'FFmpeg and PyAV required')
class ExportDeadlineTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.root=Path(t.name).resolve()
        self.path=self.root/'project.json'; self.path.write_text(json.dumps(fixture(self.root)))

    def test_stalled_assembly_preserves_scenes_and_can_resume(self):
        row = PipeDeadlineTests.external(self, """import contextlib,io
from pathlib import Path
path=Path(%r);out=path.parent/'out';ordinary=shots.encode
closed=[]
def stalled(command,images):
 if 'libx264' in command:
  def padded():
   try:
    for image in images:yield Image.new('RGB',(1024,1024))
   finally:images.close();closed.append(True)
  with patch.object(shots,'ENCODER_PIPE_TIMEOUT',.15):
   return ordinary([sys.executable,'-c','import time;time.sleep(30)'],padded())
 return ordinary(command,images)
with contextlib.redirect_stdout(io.StringIO()),patch.object(shots,'encode',stalled):
 try:shots.build_project(path,out)
 except TimeoutError:pass
 else:raise AssertionError('no timeout')
assert not (out/'film.mp4').exists() and not (out/'build-receipt.json').exists()
state=shots.read_json(out/'checkpoint.json')
assert len(state['completed'])==2 and 'ready' not in state
with contextlib.redirect_stdout(io.StringIO()):result=shots.build_project(path,out,resume=True)
print(json.dumps(dict(closed=closed,scene_exports=result['scene_exports'],verification=shots.verify_project(out)['status'])))
""" % str(self.path))
        self.assertEqual(row['closed'],[True])
        self.assertEqual(row['scene_exports'],dict(rendered=0,reused=0,resumed=2))
        self.assertEqual(row['verification'],'verified')

    def test_real_exports_keep_rgb_clock_pcm_and_mp4(self):
        class Immediate:
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def call(self,operation,function,*args):return function(*args)
        for label in ('before','after'):
            with contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                if label=='before':stack.enter_context(patch.object(shots,'_EncoderPipeDeadline',Immediate))
                shots.build_project(self.path,self.root/label)
        a=shots.read_json(self.root/'before/build-receipt.json');b=shots.read_json(self.root/'after/build-receipt.json')
        self.assertEqual(a['audio_sha256'],b['audio_sha256']);self.assertEqual((self.root/'before/film.mp4').read_bytes(),(self.root/'after/film.mp4').read_bytes())
        from tools.benchmark_bounded_blur import decoded
        self.assertEqual(decoded(self.root/'before',a),decoded(self.root/'after',b))
        self.assertEqual(shots.verify_project(self.root/'after')['status'],'verified')
