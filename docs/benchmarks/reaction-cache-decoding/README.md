# Reaction cache decoding

This change uses the cache's existing msgp.Unmarshaler fast path for private
reaction reads. Stored bytes and writers stay unchanged. Older readers and
new readers can consume the same Redis entries; public models and interfaces
do not change. LRU and Redis reads return independent reaction values and
remote-ID pointees. Unknown fields and malformed entries fall back to SQL,
so an upstream model addition cannot silently drop metadata.

This contribution builds on [PR #45](https://github.com/opnlabs/mattermax/pull/45),
which builds on [PR #43](https://github.com/opnlabs/mattermax/pull/43).
Only reaction-cache-decoding.patch is new. The 40 inherited patches remain
byte-identical, preserving their original authorship and behavior.

## Measurements

Three alternating-order paired processes per variant, each benchmark running
for one second. A Go overlay restores only the earlier reaction_layer.go;
both variants use identical writes, SQL, benchmark fixtures and validation.
The machine runs Go 1.26.10 with GOMAXPROCS=4, PostgreSQL 17 and local LRU
caches. Raw samples, ranges, code hashes and CPU details are in
[cache.json](cache.json) and [history.json](history.json).

The populated-cache benchmark reads three reactions per post. It validates
post IDs, result counts and a remote ID. Its short synthetic IDs isolate the
cache layer; the history benchmark uses real stored IDs.

| Case | Before µs/op | After µs/op | Before B/op | After B/op | Before allocs/op | After allocs/op |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| posts=1 | 1.848 | 0.441 | 592 | 448 | 23 | 18 |
| posts=60 | 120.080 | 34.996 | 42408 | 33768 | 1535 | 1235 |

The ordered-history benchmark calls the real App.PreparePostListForClient,
including default priority and acknowledgement reads. It checks order and
reaction metadata. Cold cases purge all local store caches outside the timer.
No HTTP, files, custom emoji or remote-link work is included.

| Case | Before µs/op | After µs/op | Before B/op | After B/op | Before allocs/op | After allocs/op |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| posts=1/cold | 429.238 | 480.307 | 29175 | 29178 | 498 | 498 |
| posts=1/warm | 271.936 | 270.242 | 17158 | 17014 | 311 | 306 |
| posts=10/cold | 664.354 | 704.510 | 79976 | 79967 | 1370 | 1370 |
| posts=10/warm | 363.804 | 419.648 | 43247 | 41806 | 901 | 851 |
| posts=60/cold | 1336.726 | 1356.626 | 373043 | 373042 | 6039 | 6039 |
| posts=60/warm | 829.459 | 765.346 | 194039 | 185393 | 4064 | 3764 |

The warm 60-post history median falls by about 8%, with a lower time in each
pair. Cache-only reads show a larger reduction because page preparation also
includes database reads and other metadata work. Smaller-page and cold-page
results vary, including slower medians. These runs support no speedup claim
for those controls or for server throughput under concurrent load.

The first matrix's single-post cold median was about 12% slower. That path
misses the reaction cache and does not execute the decoder. A longer targeted
control used five alternating pairs with two-second benchmark durations:

| Case | Before µs/op | After µs/op | Before B/op | After B/op | Before allocs/op | After allocs/op |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| posts=1/cold | 457.607 | 462.593 | 29172 | 29178 | 498 | 498 |

The longer control has overlapping ranges and about a 1% median difference.
Both runs are retained. [cold-control.json](cold-control.json) records every
sample. The change targets populated-cache reads; cold reads retain their
existing database path and allocation counts.

## Validation

Selected cache/app/API race suites passed 154 parent/subtest events with no
failures or skips. LRU and actual Redis format/isolation checks ran. A short
differential fuzz run executed 80,637 inputs, comparing every accepted value
with ordinary msgpack decoding. Truncation, future fields, nil/empty values,
nil elements, remote IDs and timestamp extremes are covered. Existing tests
cover cache invalidation, bypass, reactions, history and hidden metadata.

The public backend builds with only the production tag and passes the
enterprise tag/symbol checks. All 41 patches apply cleanly. No new dependency,
API, schema or configuration change is introduced.

[validation.json](validation.json) records exact revisions, commands and
scopes, including the final patch's import-only test cleanup and fresh cache
race check. The measured production code and test declarations are unchanged.
Full frontend packaging and concurrent-load capacity are outside these checks.

## Reproduce

Set TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL test database.
Set TEST_REDIS_ADDR to a disposable Redis address to include the Redis check;
without it, TestReactionCacheProviders checks LRU only. Use the normal public
server/public go.work, without enterprise modules or build tags.

From the Mattermax repository root after just workspace:

```sh
python3 docs/benchmarks/reaction-cache-decoding/benchmark.py --workspace work/src --baseline HEAD^ --suite cache --duration 1s --trials 3 --output /tmp/reaction-cache.json
python3 docs/benchmarks/reaction-cache-decoding/benchmark.py --workspace work/src --baseline HEAD^ --suite history --duration 1s --trials 3 --output /tmp/reaction-history.json
python3 docs/benchmarks/reaction-cache-decoding/benchmark.py --workspace work/src --baseline HEAD^ --suite history --case posts=1/cold --duration 2s --trials 5 --output /tmp/reaction-cold.json
```

Run the race and fuzz commands in validation.json from work/src/server.
Benchmarks of standalone PR branches do not measure the combined stack;
do not multiply their ratios together.
