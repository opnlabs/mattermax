# Mini-preview dispatch

The batch preview helper starts a goroutine for every FileInfo, while the
single-file generator immediately returns for text, SVG and already-previewed
images. Use the same eligibility predicate before dispatch and in the generator.
Create the wait group only when an image needs work, and pass it directly to
workers so the no-work path does not retain a captured bookkeeping pointer.

Pending raster previews still run concurrently. Dispatch waits for their work,
including persistence, before returning. Missing files remain eligible for a
later attempt. Input entries and order are unchanged, and single-file calls use
the same predicate as before. No worker pool, cache, schema, setting, dependency
or public API change is added. SQL statement count stays the same.

## Reproduce

Prepare work/src with this patch as the last workspace commit. Set
TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL test database and start
Redis at the upstream test defaults. The test helper initializes databases;
do not point it at production. From the Mattermax patch repository:

```sh
python3 -I docs/benchmarks/mini-preview-dispatch/benchmark.py \
  --workspace work/src --baseline HEAD^ --iterations 2000 --trials 5 \
  --output /tmp/mini-preview-matrix.json
python3 -I docs/benchmarks/mini-preview-dispatch/benchmark.py \
  --workspace work/src --baseline HEAD^ --mode warm --benchtime 1s --trials 5 \
  --output /tmp/mini-preview-warm.json
```

The Go overlay restores only the original file.go. Both variants use the same
real App.PreparePostForClientWithEmbedsAndImages benchmark, migrated SQL store,
file cache, runtime and test settings. Existing post-metadata preparation is
unchanged and still performs its two file passes in this recorded workspace.
This experiment is independent of the metadata-reuse contribution in #43.
Source hashes and the unchanged post_metadata.go hash are included.

Fixtures contain zero, one or ten text attachments, or PNG FileInfo rows with
an existing valid 8x8 JPEG mini-preview. They store metadata, not original image
bytes. Every timed call validates file count, order and existing preview bytes.
Setup, fixture updates and preflight are outside timing. Preflight warms the
normal cache; master mode sets IsNewPost and bypasses it for nonempty attachments.
Both modes use the same PostgreSQL instance, rather than a replication topology.
Zero-attachment controls perform no file/master query or preview dispatch.

Five alternating-order paired trials cover the full matrix at 2,000 sequential
preparations per sample. Cached operations also have five duration-based pairs,
with at least one second per sample and Go's automatic iteration calibration.
No other app or race suite ran during timing; the race detector is off for
measurement. Raw lines, source hashes and host/runtime details are in
[results.json](results.json) and [warm-duration-results.json](warm-duration-results.json).

## Duration-based cached results

Values are median samples, with full trial ranges in parentheses. Times are
microseconds per post preparation, including app/cache work.

| Metadata | Files | Existing, us | Filtered dispatch, us |
| --- | ---: | ---: | ---: |
| text | 0 | 1.561 (1.492 to 1.592) | 1.571 (1.531 to 1.601) |
| text | 1 | 7.239 (7.113 to 7.406) | 4.713 (4.663 to 6.140) |
| text | 10 | 38.692 (36.867 to 52.765) | 30.348 (29.626 to 38.450) |
| ready_image | 0 | 1.622 (1.569 to 2.078) | 1.594 (1.582 to 2.005) |
| ready_image | 1 | 7.756 (7.504 to 10.609) | 5.088 (5.021 to 6.354) |
| ready_image | 10 | 42.569 (40.093 to 55.824) | 33.825 (32.692 to 40.239) |

The no-attachment control medians are similar and their ranges overlap. The
cached attachment medians are lower. Ten-file ranges have some overlap, so the
shared-host results should not be treated as a production latency guarantee.
Median Go allocations from the duration-based samples were:

| Metadata | Files | Existing bytes | Filtered bytes | Existing allocations | Filtered allocations |
| --- | ---: | ---: | ---: | ---: | ---: |
| text | 0 | 1297 | 1297 | 29 | 29 |
| text | 1 | 2643 | 2466 | 63 | 57 |
| text | 10 | 15339 | 13852 | 325 | 283 |
| ready_image | 0 | 1297 | 1297 | 29 | 29 |
| ready_image | 1 | 3973 | 3796 | 67 | 61 |
| ready_image | 10 | 28641 | 27147 | 365 | 323 |

## Master-read results and limits

The full fixed-count matrix retains all cached and master samples. Its master
medians and ranges, in milliseconds per preparation, are:

| Metadata | Files | Existing, ms | Filtered dispatch, ms |
| --- | ---: | ---: | ---: |
| text | 0 | 0.001545 (0.001518 to 0.002400) | 0.002282 (0.001516 to 0.002493) |
| text | 1 | 1.179496 (1.048773 to 1.232969) | 1.023307 (0.978609 to 1.261175) |
| text | 10 | 1.263829 (1.112023 to 1.459315) | 1.112741 (1.026075 to 1.333140) |
| ready_image | 0 | 0.002226 (0.001527 to 0.003308) | 0.002412 (0.001489 to 0.002575) |
| ready_image | 1 | 1.087346 (1.012488 to 1.315850) | 1.041560 (0.970958 to 1.081515) |
| ready_image | 10 | 1.225582 (1.091614 to 1.649772) | 1.128649 (1.105299 to 1.250548) |

The master ranges overlap, and SQL work is unchanged. These results establish
no master-read latency improvement. Preliminary short samples were mixed;
the fixed-count matrix and longer cached repetitions retain that distinction.

These are sequential app microbenchmarks on a shared host. HTTP encoding,
authorization, uploads, actual post creation, image decoding and WebSocket
fanout are outside the timing scope. PostgreSQL CPU/memory and production
throughput, request percentiles and sustained concurrency were not measured.
Pending-image generation is functionally tested with tiny PNGs, not timed here.
Host activity, cache state, fixture metadata and test-helper background work
limit extrapolation.

## Validation

The mixed batch regression uses real PNG files and checks preview bytes are
persisted before return. Text, SVG and existing-preview metadata remain
unchanged; entries keep their order and identity. A missing image remains
pending, then succeeds after its bytes are supplied on a later call. Completed
and empty batches are also exercised. This same functional test passes with
the original file.go restored, checking behavior preservation on both paths.

Selected app and API suites ran with the race detector, covering uploads,
drafts, file-info retrieval and attachment-policy filtering for drafts and
scheduled posts. All 12 checks passed without skips. The baseline functional
control also passed. [validation.json](validation.json) records commands and
outcomes. All 38 existing Mattermax patch files and author credits are unchanged,
including Karan Sharma's (@mr-karan) feature work. Only public Team Edition code
was used. The full branded packaging build was not run.
