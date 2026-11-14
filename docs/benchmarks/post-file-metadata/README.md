# Post attachment metadata reuse

PreparePostForClientWithEmbedsAndImages calls ordinary post preparation, adds
embed/image metadata, then prepares file metadata again. The ordinary path
already loaded file information, restored stored attachment order, applied its
accessibility filtering and attempted mini-preview generation.

Reuse that file result when the first preparation succeeded and survived.
Keep the existing second attempt after store failures, pending image previews
and metadata resets. The private preparation helper reports whether reuse is
safe; both public method signatures remain unchanged. Standalone preparation
keeps its existing single-attempt behavior. New/edit flags still select master
reads, include-deleted behavior stays intact, and the later per-user attachment
sanitization is unchanged. No schema, index, cache or dependency is added.

getEmbedsAndImages does not replace the outer post's file metadata. The reuse
path therefore removes the second successful snapshot rather than moving
permission checks or skipping a failed first read. It adds no synchronization
with concurrent attachment changes. Deleted and unrevealed burn-on-read paths
retain their existing final lookup, even when ordinary preparation cleared the
metadata. A missing mini-preview after the first attempt also retains the
second attempt because generation failures are logged instead of returned.

## Reproduce

Prepare work/src with this patch as the last workspace commit. Set
TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL test database and start
Redis at the upstream test defaults. The test helper initializes databases;
do not point it at production. From the Mattermax patch repository:

```sh
python3 -I docs/benchmarks/post-file-metadata/benchmark.py \
  --workspace work/src --baseline HEAD^ --iterations 1000 --trials 3 \
  --output /tmp/post-file-metadata-results.json
```

The harness restores only the original post_metadata.go through a Go overlay.
Both variants use the same real app benchmark, migrated SQL store, file cache,
Go runtime and test configuration. The benchmark uses synthetic stored posts
with zero, one or ten text attachments. It stores FileInfo rows, not file bytes.
Link previews are disabled and the message has no links. All timed calls check
the returned file count and order. Setup, stored fixture updates and preflight
are outside timing. No other app test or race suite ran during measurement;
the timing run excludes race instrumentation.

Warm mode preloads the existing file-info cache. Master mode sets IsNewPost,
which bypasses that cache and refreshes the stored post/file IDs for nonempty
attachments. Both use the same disposable PostgreSQL instance; this does not
test replication lag or a separate replica topology. Zero-attachment controls
perform no file or master queries in either mode. The test does not measure
image decoding, uploads, remote embed fetches or failing/retry paths.

Three paired trials alternate process order, with 1,000 sequential preparations
per case. [results.json](results.json) records every benchmark line, source
hashes, resolved workspace revisions and host/runtime details.

## Observed results

Values are median benchmark samples. Parentheses give the full trial range in
microseconds per post preparation, including app and applicable store/driver work.

| Files | Mode | Existing, us | Reuse, us |
| --- | --- | ---: | ---: |
| 0 | warm | 2.526 (2.421 to 2.678) | 2.444 (1.569 to 2.505) |
| 0 | master | 2.402 (2.004 to 2.583) | 1.573 (1.561 to 1.639) |
| 1 | warm | 9.448 (8.212 to 11.121) | 6.004 (5.502 to 8.793) |
| 1 | master | 1070.406 (1009.594 to 1125.536) | 804.735 (592.511 to 806.707) |
| 10 | warm | 45.388 (43.278 to 50.613) | 21.570 (19.464 to 21.892) |
| 10 | master | 1181.797 (1127.045 to 1281.509) | 605.398 (592.063 to 752.285) |

Median Go allocation measurements per preparation:

| Files | Mode | Existing bytes | Reuse bytes | Existing allocations | Reuse allocations |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 | warm | 1296 | 1296 | 29 | 29 |
| 0 | master | 1296 | 1296 | 29 | 29 |
| 1 | warm | 2677 | 1968 | 63 | 46 |
| 1 | master | 72196 | 36781 | 921 | 475 |
| 10 | warm | 15481 | 8430 | 325 | 177 |
| 10 | master | 118762 | 60009 | 1427 | 728 |

The change avoids repeated cache decoding, ordering and mini-preview dispatch
for ordinary successful reads. New/edit reads also avoid another post query
and file query. The negative-control regression observes two file-info reads
with the original source and one with reuse. Master-selection mocks observe
the corresponding post-read count.

These are warm, sequential app microbenchmarks on a shared host. The
zero-attachment timing differences are controls, not evidence of a production
latency gain. PostgreSQL CPU/memory, HTTP encoding, authorization, actual post
creation, uploads, image decoding and WebSocket fanout are outside the measured
scope. The results establish no whole-server throughput, request percentile,
production sizing or sustained-concurrency claim. Host activity, cache state,
synthetic metadata and test-helper background activity limit extrapolation.

## Validation

The app regression covers successful reuse, master selection, include-deleted
flags, attachment order, source-post immutability, standalone calls, deleted
content, unrevealed recipient resets, first-read errors, failed image previews
and retained metadata after repeated errors. Restoring the original source
makes its ordinary-read count assertion fail with two calls instead of one.

Selected app and attachment-policy API suites ran with the race detector,
including image proxies, permalink sanitization, burn-on-read sender expiry,
file-info retrieval and per-user file policy filtering. All 102 checks passed
without skips. [validation.json](validation.json) records commands and outcomes.
All 38 existing Mattermax patch files and their original authorship are
unchanged. Only public Team Edition code was used. The full branded packaging
build was not run.
