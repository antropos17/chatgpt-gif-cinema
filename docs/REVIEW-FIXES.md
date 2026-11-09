# Offline review and regression fixes

Independent review found and reproduced four edge cases. All four were fixed
in the reviewed source and retained in this source-only publication:

1. A 2 × 2 output canvas hid oversized 2048 × 2048 layer rasters from the original
   compositing budget. Separate per-layer, aggregate, supersampling and active
   raster-pixel-frame budgets now reject the scene before image allocation or
   decoding. Premultiplication is cached once rather than repeated per frame.
2. A valid 1500-frame / 16-layer export produced a receipt larger than the verifier's
   previous 4 MiB reader limit. Both sides now share a 16 MiB limit, and the writer
   checks serialized size before completing output. The original 1500-frame case
   passes full verification.
3. A named pipe supplied as a scene or image could block reading indefinitely.
   Local inputs must be regular files. Nonblocking open and descriptor checks
   cover a regular-file-to-FIFO replacement race on POSIX.
4. A compact valid scene could expand beyond the previous limit when default
   properties and indentation were saved. Input/output scene JSON now share a
   bounded 512 KiB limit. Saving validates and serializes before creating the
   destination. The original 214,786-byte normalized scene saves and reopens.

The source-only publication retains regression tests for all four cases and the
frame-by-frame verifier. Its test results are reported on the pull request for the
exact published commit; historical tests of a larger unpublished preview are not
claimed for this smaller package. No showcase media or archive is included here.
Visual acceptance remains a human decision.

This is a scoped review, not a claim that the prototype has no remaining bugs.
