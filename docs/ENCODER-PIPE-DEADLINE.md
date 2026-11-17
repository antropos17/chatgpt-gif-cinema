# Native encoder input deadlines

A native sequence build streams RGB frames to a directly launched FFmpeg process.
The existing `process.wait(timeout=180)` limits the final encoder drain, but cannot
be reached if `stdin.write()` or buffered `stdin.close()` is already blocked on a
full pipe. A live encoder that stops reading could therefore stall the build before
its wait timeout. A real non-reading child reproduced this path; the diagnostic
outer guard stopped it after 2 seconds. That probe did not wait 180 seconds or
claim that the final-wait timer had itself failed.

`shots.encode()` now has one watchdog thread per encoder, armed only during each
input write and buffered close. Each operation has **180 seconds**. The timer is
reset for the next operation; it is not a total film/render deadline. Frame
production and `image.tobytes()` are outside the armed interval, so a slow scene
or a long film does not consume an input-write deadline before transfer starts.
The existing separate final-drain timeout remains unchanged.

On expiry the watchdog kills only its owned encoder process. It never closes the
buffered pipe from another thread: doing so can block on the writer's own lock.
The caller reports `TimeoutError`, closes its frame iterator, reaps the process,
and stops/joins the watchdog. A terminated encoder's `BrokenPipeError` does not
replace the timeout. Unexpected source errors and interruption keep their normal
cleanup path. Failure to start the watchdog also enters encoder cleanup.

## Publication and recovery

No codec, frame generation, source clock, audio or verification setting changes.
Failed attempts stay private/partial; they are not marked complete. Previously
verified scenes remain available for a compatible resume. The regression suite
forces a real stalled assembly, confirms that no final movie or completed receipt
was published, then resumes the unchanged project and verifies the resulting film.
Existing source-change and engine-identity checks remain mandatory. When installing
a changed engine, keep old outputs and choose a new build directory rather than
forcing an incompatible interrupted resume.

## Boundaries

- This is a reliability fix, **not a rendering speedup** or a hard real-time SLA.
- It targets a directly launched FFmpeg child. An arbitrary wrapper can spawn a
  descendant that keeps the pipe's read end open after the wrapper dies. Killing
  only the direct child cannot guarantee release in that situation. Do not claim
  universal process-tree timeout handling or run untrusted wrappers on that basis.
- OS process-kill failure or an uninterruptible kernel operation is not solved.
- A single write that legitimately needs more than 180 seconds is aborted even if
  it made partial progress. This is a per-operation deadline, not a byte-progress
  detector. The limit is internal, not a new project/CLI option.
- Tests use shortened deadlines to exercise real blocked writes and buffered
  closes, with an outer test-process safety guard. These are fault injections,
  not a claim that FFmpeg routinely hangs. Native Windows/macOS execution has not
  been performed; the explicit pipe-capacity fixture is Linux-only.

## Reproduction and overhead

`tests/test_native_encoder_deadline.py` covers blocked write/close, source delays,
separate deadlines, late-expiry handling, source/pipe errors, cancellation, thread
start failure, cleanup, resume and actual RGB/PTS/hold/PCM/MP4 equality.

`tools/benchmark_encoder_deadline.py` compares full fresh native builds. Its frozen
reference must be `shots.py` from local commit `658e446`, Git blob
`97dade53139c4732be9dd17588dd2edfd9c27dba`. The hash is checked before executing the
reference. Both variants retain the current build engine and verification; only
`encode()` is replaced by the old function for the baseline. Output hashing for
comparison follows the timed region. RSS refers to the Python process, not the
sum of its FFmpeg children.

```sh
# From a source checkout use PYTHONPATH=.; or use the installed wheel externally.
python tools/benchmark_encoder_deadline.py project.json \
  --baseline-source baseline_shots.py --out new-deadline-comparison --repeats 3
```

Review all repeated raw measurements, not only a favorable pair. No new frames,
character identity, face lock, smoother motion or artistic approval is implied.
