# Emoji-name extraction

This allocation optimization is ready for review after the authenticated HTTP
comparison below. Earlier app-only matrix regressions remain unexplained and
are retained in full. Claims are limited to the measured workloads; this is not
a general server-throughput or production-latency claim.

Preparing emoji text currently allocates a regular-expression match for each
name, although the metadata path only needs the name's bytes. This patch scans
the fixed `:[a-zA-Z0-9_+-]+:` syntax directly. It preserves non-overlapping
matches, order, duplicates and nil results. Text extraction from posts,
attachments and interactive blocks, reaction names, sorting/deduplication,
custom-emoji reads and cache behavior are unchanged.

The baseline is the original 38-patch source at `c9dbbcc480b2`. The earlier
helper/ordered/isolated studies used candidate `f1cde2185ba8`. Source
`e04cefb93153` adds only the mixed benchmark file; production and existing tests
are byte-identical to that earlier revision. A Go overlay substitutes only the original production file for
baseline runs; both variants use the identical test/benchmark file. This is an
independent contribution, without the other performance PRs. The runner checks
the parent tree so replayed patch commits can have different IDs.

Three alternating before/after pairs ran on Go 1.26.10 with GOMAXPROCS=4 and
local disposable PostgreSQL/Redis. Each variant uses separate helper and
history processes. Six helper inputs run for 300 ms each; ten history cases run
for 300 operations each. History pages are stored and ordered, with normal
priority reads and warmed emoji caches. There are no reactions, files, image
proxy or network previews. The dense message repeats a custom emoji and a
system emoji 100 times per post.

The dense helper falls from 36.229 to 4.257 microseconds and from 206 to 9
allocations. A dense 60-post page measures 12.732 to 13.823 ms, with median
allocations falling from 88,235 to 76,414 and bytes from 5,040,822 to 4,699,385.
This does not establish a whole-server throughput gain.

## Complete history results

Times are medians across three processes, in milliseconds per page. Change is
the ratio of those medians. The last column compares each before/after pair;
those percentages can differ from the ratio of medians. Lower is faster.

| Page | Before ms | After ms | Change | Paired change range |
| --- | ---: | ---: | ---: | ---: |
| plain/posts=1 | 0.263 | 0.270 | +2.9% | -4.8% to +7.2% |
| plain/posts=60 | 0.814 | 0.795 | -2.2% | -5.2% to +0.3% |
| system/posts=1 | 0.399 | 0.404 | +1.3% | -4.4% to +4.4% |
| system/posts=60 | 1.075 | 1.006 | -6.4% | -14.4% to -2.1% |
| custom/posts=1 | 0.404 | 0.415 | +2.7% | -31.2% to +87.9% |
| custom/posts=60 | 1.165 | 1.115 | -4.3% | -6.3% to -1.0% |
| dense/posts=1 | 0.747 | 0.714 | -4.3% | -5.1% to +10.3% |
| dense/posts=60 | 12.732 | 13.823 | +8.6% | -8.7% to +9.4% |
| invalid/posts=1 | 0.605 | 0.830 | +37.2% | +7.1% to +73.7% |
| invalid/posts=60 | 10.093 | 12.260 | +21.5% | +6.4% to +23.9% |

Full samples, all helper cases and slower observations are in
[results.json](results.json); [summary.json](summary.json) also records allocation
medians and every paired timing change. Short-page/control timings vary, so no
general single-post latency improvement is claimed.

## Isolated heavy cases

Each case also ran in its own fresh process, with three alternating before/after
pairs and 500 page preparations per process. All three paired timings improve
for both cases. Their medians are:

| Case | Before ms | After ms | Change |
| --- | ---: | ---: | ---: |
| dense, 60 posts | 12.569 | 11.315 | -10.0% |
| invalid, 60 posts | 12.261 | 9.889 | -19.3% |

[isolated-dense.json](isolated-dense.json) and
[isolated-invalid.json](isolated-invalid.json) preserve every sample. These
results disagree with parts of the ordered matrix. They do not explain its
regressions or establish that those regressions are harmless. Later mixed-loop and HTTP studies below add evidence at different boundaries;
they do not establish the cause of those earlier regressions.

## Controls and initial study

A separate five-pair single-post plain-text control repeats 3,000 operations in
each process. It measures median 0.321 to 0.299 ms, with paired changes ranging
from -16.5% to +9.4%. Both slower and faster cases occur. These controls
show local timing variability; they do not establish a plain-text speedup.
[control.json](control.json) preserves every sample and command.

The initial three-pair study is retained in [initial-results.json](initial-results.json)
and [initial-summary.json](initial-summary.json), including the slower single-post
plain median. A patch-application check overlapped part of its first baseline
helper process. Its history timings ran without concurrent build/test workloads.
The final study above, isolated control and heavy cases ran sequentially after all
race/build/startup checks completed. The runner's baseline selection was made
replay-safe before those final runs; the measured production and test-file
hashes are identical across both studies.

These are local synthetic workloads. Production data, latency tails, concurrency
and complete HTTP throughput have not been measured. Standalone ratios do not
describe the combined performance contribution stack.

## Balanced mixed preparation loop

The added benchmark keeps five stored 60-post pages alive: plain text, system
emoji, custom emoji, dense emoji and malformed emoji text. It makes a balanced,
deterministically shuffled sequence of preparations through the normal app
path. All outputs are checked. It warms each page three times and explicitly
collects the heap after fixture warming, before measurement. GOGC=100 and
GOMAXPROCS=4 are fixed. There are five alternating before/after process pairs,
with 1,000 preparations per process and 200 observations of each page type.

Median total time per preparation changes from 5.153 to 4.787 ms
(-7.1%). Every pair improves, ranging from
-9.4% to -5.3%. Median allocations change from
49,030 to 46,642, and bytes from 4,700,596 to 4,629,578.

Overall ns/op includes output assertions. Per-page p50/p95 samples cover only
the preparation call. Those small synthetic samples are diagnostic observations,
not production latency percentiles or HTTP throughput measurements.

GC CPU and pause counters include process background work around the loop.
Their changes do not consistently track the preparation-time improvement:

| Counter per preparation | Before median | After median | Paired change range |
| --- | ---: | ---: | ---: |
| GC cycles | 0.0560 | 0.0550 | -5.3% to +1.8% |
| GC CPU (ms) | 1.6407 | 1.6241 | -4.3% to +1.7% |
| GC pause (microseconds) | 2.9130 | 2.8360 | -10.3% to +8.9% |

Dense-page p50 improves in every pair. Malformed-text p50 changes in both
directions, so this is not evidence for a general malformed-page speedup.
[mixed-results.json](mixed-results.json) preserves every sample, command and
GC/heap/page metric. [mixed-summary.json](mixed-summary.json) includes every
paired change, including slower page observations.

Go's benchmark harness collects garbage before invoking each benchmark
function, before that function creates and warms its fixtures. The original
cases can therefore still enter timing with fixture/warming garbage present.
This mixed loop collects again after warming, a separate measurement condition.
Its favorable results do not establish that fixture garbage caused the earlier
ordered-matrix regressions, which remain unresolved. The subsequent HTTP study
below measures the actual authenticated history route.

## Authenticated HTTP history

Public baseline/candidate binaries use the production build tag, explicit
non-dev build numbers/hashes and BuildEnterpriseReady=false. The baseline
substitutes only the original production file through a Go overlay. Both pass
the release script's enterprise tag/symbol exclusion criteria.

Each process starts a new loopback-only server and database. Fixtures are made
through public APIs: an owner, a regular reader, a team, five member channels,
a valid PNG custom emoji named scan_custom and 60 posts per channel. Emails,
jobs, plugins, diagnostics and API rate limiting are disabled. Link previews
are off; custom emoji and normal priority reads are on. GOMAXPROCS=4 and
GOGC=100 are fixed. The reader logs in and uses one verified persistent HTTP/1.1
connection, with no conditional requests and Accept-Encoding: identity.

Five alternating before/after pairs each warm 100 requests and then run 1,000
timed GETs to `/api/v4/channels/{id}/posts?page=0&per_page=60&collapsedThreads=false`.
The five page types are equally represented in a fixed shuffled sequence.
Timing spans request send through complete response read, excluding JSON decode
and assertions; whole-loop elapsed time including those checks is also saved.
This is a single local client without TLS or concurrent clients, not a
saturation-throughput or production tail-latency test.

All 10,000 timed requests return HTTP 200 and the expected 60 posts in exact
order, with unchanged messages and correct custom-emoji identity. Full normalized
response hashes match across every process after abstracting fixture IDs and
timestamps. Uncompressed response byte counts also match. The pilot separately
checks the same fixture/output/connection/cleanup path and supplies no timing
claim. Every owned server, database and runtime directory is removed.

The table shows medians of per-process mean completed-response latency, in ms.
Paired ranges compare each corresponding before/after process pair.

| Page type | Before ms | After ms | Change | Paired change range |
| --- | ---: | ---: | ---: | ---: |
| mixed | 8.133 | 7.629 | -6.2% | -6.5% to -5.5% |
| plain | 3.428 | 3.423 | -0.1% | -1.5% to +1.7% |
| system | 3.687 | 3.629 | -1.6% | -2.6% to +0.2% |
| custom | 3.787 | 3.731 | -1.5% | -2.8% to +0.2% |
| dense | 16.720 | 14.693 | -12.1% | -12.2% to -9.1% |
| invalid | 13.057 | 12.483 | -4.4% | -7.3% to -1.9% |

The mixed, dense and malformed-page means improve in every HTTP pair. Ordinary
text is essentially unchanged; individual plain/system/custom pairs include
slower observations. This supports review of the allocation optimization at the
actual API boundary without explaining away the earlier app-only regressions.
It does not establish behavior at other page sizes, traffic mixes, compression
settings, database sizes or concurrency levels.

[http-build.json](http-build.json) records measured binary hashes and commands.
[http-results.json](http-results.json) preserves all request timings, output
fingerprints, response sizes and cleanup results. [http-summary.json](http-summary.json)
retains every paired per-type change, including slower observations. The
baseline and candidate each use a fresh database with the same fixture shapes.

## Behavior and validation

The oracle test compares against the original regex, including exact order,
duplicates and nilness. It covers explicit boundary/invalid-UTF-8/long-name
cases, every combination up to seven bytes from a delimiter/name/invalid-byte
alphabet, and 200,000 deterministic generated strings. A fuzz target supplies
seed checks and can be run for longer. It follows model.EmojiPattern, so future
syntax changes will fail the equivalence test until the scanner is updated.
History benchmarks assert ordered posts, messages and exact custom-emoji
identity as well as metadata presence. Both variants pass these output checks.

At source `f1cde2185ba8`, selected app/API race suites passed 106 parent/subtest
events without failures or skips, including fuzz seeds and existing
metadata/emoji/history checks. Its public backend build, enterprise tag/symbol
exclusions and fresh-database startup/ping/client-config smoke passed. Temporary
resources were removed. These checks retain that tested revision.

The current source adds only the mixed benchmark file, which passes a separate
five-page race execution/output check. Production and existing test files are
byte-identical. All 39 current patches apply cleanly; the original 38 patch
files and their authorship, including Karan Sharma (@mr-karan), remain
byte-identical. [validation.json](validation.json) records commands, source
hashes and the historical/incremental validation scopes.

## Reproduce

Create this branch's unbranded workspace with `just workspace`. Use Go 1.26.10,
set TEST_DATABASE_POSTGRESQL_DSN and TEST_REDIS_ADDR to disposable services,
and keep only server and public in go.work. Set GOPATH/GOCACHE/GOMODCACHE if
needed for your environment. Run from this repository root:

```sh
python3 docs/benchmarks/emoji-name-scan/benchmark.py --output /tmp/emoji-scan-results
python3 docs/benchmarks/emoji-name-scan/control.py --output /tmp/emoji-scan-control
python3 docs/benchmarks/emoji-name-scan/isolated.py --case dense --output /tmp/emoji-scan-dense
python3 docs/benchmarks/emoji-name-scan/isolated.py --case invalid --output /tmp/emoji-scan-invalid
python3 docs/benchmarks/emoji-name-scan/mixed.py --output /tmp/emoji-scan-mixed
python3 docs/benchmarks/emoji-name-scan/http_build.py --output /tmp/emoji-scan-http-build
python3 docs/benchmarks/emoji-name-scan/http_requests.py --build-report /tmp/emoji-scan-http-build/build.json --output /tmp/emoji-scan-http
```

Earlier result files retain their original runner hashes and source revision.
For their exact historical workspace, use root commit `0ee5ad4c7d07`. The current
runner also accepts the added mixed benchmark file.

The HTTP builder accepts --nm-goroot for an SDK with a matching nm tool. On
this host it used /tmp/mattermax-release-goroot, which is selected when present;
otherwise it uses the active Go SDK. Both tag and symbol guards remain required.

The runners check the baseline tree, use a temporary overlay and save all
commands, raw log hashes and measurements. No source files are rewritten.
Public backend validation uses only the production build tag, an explicit
non-dev build number and BuildEnterpriseReady=false. Full branded packaging,
browser flows and deployment are outside this check.
