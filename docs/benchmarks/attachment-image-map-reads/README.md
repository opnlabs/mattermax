# Attachment image URL map reads

The combined twenty-contribution attachment-history profile still attributes
3.88s beneath Attachments out of 4.65s beneath PreparePostListForClient.
InteractiveBlocksImageURLs accounts for 1.38s beneath those stacks: it decodes
all attachment fields to read only image_url, thumb_url, author_icon and
footer_icon. The profile includes setup and selects a bottleneck, rather than
measuring an improvement. Its source and reports are retained in the
[combined checkpoint](https://github.com/rhnvrm/mattermax/tree/7cd0d0515d3e4be3a233d08bd231132e6ccbf676/docs/verification/performance-series/profiles).

This experiment is stacked on standalone PR #58. It shares that patch's strict
map validator between attachment decoding and image URL collection. Eligible
maps expose their four validated URL strings without constructing attachment
objects or field copies. The accepted map domain is unchanged.

Unsupported elements use the original JSON fallback, extracted into a shared
helper. Elements are handled in order, so custom marshalers can still observe
and change later input values in the same order as before. There is no
whole-collection retry, decoded-object cache or shared output slice. Typed
attachment slices keep their existing image collection behavior. Interactive
block traversal and its feature flag are unchanged.

## Semantic checks

The model oracle compares complete URL lists, including duplicates, ordering,
interactive-block prefixes and nilness. Cases cover valid/invalid maps,
nullable fields/actions, Slack boolean coercions, structured values, invalid
UTF-8, numeric boundaries, custom marshaling and mixed collections. Generated
checks exercise 100,000 URL inputs alongside PR #58's 200,000 decoder inputs.
Ownership and concurrent property replacement checks run under the race
detector. A callback-order check changes earlier and later maps while the
collection is decoded, then compares the captured URL snapshots to the legacy
implementation.

Both JSON-oracle fuzz targets passed 30-second stress runs: 458,526 decoder
executions and 436,500 image-URL executions. Full validation scopes and source
revisions are recorded below.

## Controlled comparison

The baseline is source 9e85f87af81bbf7ae1e85d0ea330f4b02ca59cef from PR #58.
The runner restores its original post.go and message_attachment_decode.go with
a Go overlay. The new image helper file also includes unused validator and JSON
fallback declarations in the baseline overlay so the shared tests compile.
The baseline production methods do not call those extra declarations, and none
has an initializer. Both variants use identical test and history fixture files.
Source hashes, overlay hashes, commands and every sample are saved by the runner.

Three alternating before/after pairs use Go 1.26.10, GOMAXPROCS=4, GOGC=100 and
TZ=UTC. Each variant uses fresh model and app processes. Model cases run for
300ms; history cases run for 200 preparations of 60 SQL-stored posts. Existing
decoder controls and unsupported/mixed image-reader cases remain in the set.
The history fixtures have no image URLs or files, priority/custom emoji reads
are enabled and remote previews are disabled. These are synthetic component
and preparation measurements, separate from HTTP or concurrent throughput.

## Reproduce

Create this branch's unbranded workspace with just workspace. Use Go 1.26.10
with only server and public in go.work. Set TEST_DATABASE_POSTGRESQL_DSN and
TEST_REDIS_ADDR to disposable services. Set GOPATH/GOCACHE/GOMODCACHE as needed.
From this repository root, run:

```sh
python3 docs/benchmarks/attachment-image-map-reads/benchmark.py --output /tmp/attachment-image-results
```

The runner recognizes the standalone PR #58 parent tree and the combined
twenty-contribution parent tree. Git-am commit IDs can differ; tree contents
must match. It records the exact context and source revisions for every study.
Ratios must not be multiplied with other PRs' measurements.

## Preparation results in both contexts

The same four changed source files and the same history fixture are byte-identical
across the standalone and combined experiments. These comparisons measure only
the incremental image-reader change in each context. They do not compare the
entire combined stack with the original server.

### Standalone PR #58 parent

[results.json](results.json) contains all samples; [summary.json](summary.json) contains every model/preparation case, allocation medians and paired changes.

History timings are milliseconds per 60-post preparation. Change compares
process medians; paired ranges compare corresponding runs.

| Page | Before ms | After ms | Change | Paired range |
| --- | ---: | ---: | ---: | ---: |
| actions | 6.142 | 6.328 | +3.0% | +2.3% to +4.0% |
| fields=0 | 1.335 | 1.343 | +0.6% | -8.2% to +6.3% |
| fields=64 | 9.479 | 9.386 | -1.0% | -3.6% to -0.7% |
| fields=8 | 2.608 | 2.489 | -4.6% | -5.9% to +2.3% |
| plain | 0.692 | 0.772 | +11.5% | -1.6% to +52.1% |

### Combined twenty-contribution parent

[combined-results.json](combined-results.json) contains all samples; [combined-summary.json](combined-summary.json) contains every model/preparation case, allocation medians and paired changes.

History timings are milliseconds per 60-post preparation. Change compares
process medians; paired ranges compare corresponding runs.

| Page | Before ms | After ms | Change | Paired range |
| --- | ---: | ---: | ---: | ---: |
| actions | 5.265 | 5.331 | +1.3% | -3.3% to +2.9% |
| fields=0 | 0.791 | 0.771 | -2.5% | -8.3% to -1.3% |
| fields=64 | 3.925 | 3.595 | -8.4% | -9.2% to -4.9% |
| fields=8 | 1.245 | 1.218 | -2.2% | -2.7% to -1.0% |
| plain | 0.490 | 0.489 | -0.2% | -1.7% to +1.7% |

The standalone 64-field history gain is about 1%. Its action case is slower in
all pairs; the plain median is slower, with one +52.1% pair and mixed later
pairs. These results are retained without a standalone broad speedup claim.

With the earlier Markdown/image and emoji-scan contributions present, the
64-field history fixture improves by median 8.4%, with every pair improving by
4.9-9.2%. Plain history is essentially unchanged. The action history control
has mixed pairs and a slower median. Model URL fallback controls also include
slower observations, particularly actions, unknown keys and malformed fields in
the combined context. Their allocation counts and all samples remain published.

For eligible 64-field maps without URLs, the image accessor removes 67
allocations per call. When URLs are present, the returned URL slice still owns
its storage. The full attachment decoder's field allocations remain unchanged.
The HTTP comparison below measures the incremental change in the combined
context. Its gain is smaller than the image-accessor gain.

The standalone study used the exact [producer snapshot](measured-runner.py.txt),
whose hash matches results.json. The current runner replaces the producer's
commit-ID guard with stable parent-tree guards and records the detected context;
the measurement protocol is unchanged. This allows a fresh git-am workspace to
reproduce either study without requiring the original local commit IDs.

To reproduce the combined context, create an unbranded workspace from fork
checkpoint 7cd0d0515d3e4be3a233d08bd231132e6ccbf676, apply this contribution's
patch with git am in work/src, and copy benchmark.py under the same docs path
in that checkout. Run it there against disposable services. The resulting
workspace has the combined parent plus this image-reader change; the standalone
runner invocation above uses this contribution's normal patch series.

## Authenticated HTTP comparisons

### Combined twenty-contribution context

[http-results.json](http-results.json) preserves all 10,000 request timings;
[http-summary.json](http-summary.json) records process means and paired changes.
This study compares source 787f4bbe440f (combined twenty contributions) with
73c65c133bb9 (the same stack plus this image-reader change). The separate
standalone-parent study follows below. The four changed source files
and the history fixture are byte-identical across the two component contexts.

Five alternating before/after pairs used fresh public backends and databases.
Each process created 300 posts through the public APIs, warmed 100 requests and
measured 1,000 requests equally split across five page types. An ordinary team
and channel member read 60-post history pages over one verified persistent
HTTP/1.1 connection. Attachments contain no image URLs in this fixture. Model
oracles and app tests cover the URL-present paths separately. Priority/custom
emoji reads are enabled; previews, jobs, plugins, emails and diagnostics are off.

Timing spans sending the request through reading its full response body.
JSON decoding, assertions and fingerprinting happen outside the timer. All
responses were HTTP 200. Post order/content, raw fields, action/embed metadata,
normalized full-response fingerprints and byte lengths matched across every
process. Normalization replaces generated IDs and timestamps. All temporary
servers, databases and runtime directories were removed.

Times are milliseconds per request, taking the median of five process means
for each variant. Paired ranges compare corresponding processes.

| Page | Before ms | After ms | Change | Paired range |
| --- | ---: | ---: | ---: | ---: |
| plain | 3.372 | 3.344 | -0.9% | -1.2% to +2.9% |
| fields=0 | 4.231 | 4.186 | -1.1% | -2.9% to +0.4% |
| fields=8 | 5.512 | 5.462 | -0.9% | -2.0% to +1.0% |
| fields=64 | 12.983 | 12.662 | -2.5% | -6.0% to -1.6% |
| actions | 10.819 | 10.783 | -0.3% | -1.1% to +0.5% |

Only the 64-field page improves in every HTTP pair, by 1.6-6.0%, with a 2.5%
change between process medians. Other page types have mixed pairs and changes
around 1% or less between medians. No plain-page or action-page gain is claimed.
Both studies use localhost synthetic requests with one client and no TLS. They
do not establish concurrent throughput or production tail latency. The slower
standalone history and model fallback results remain part of this report.

### Standalone PR #58-only context

[standalone-http-results.json](standalone-http-results.json) contains a separate
10,000-request comparison, using the same producer and fixture protocol over
source 9e85f87af81b (PR #58) and a4a496745bb3 (the publication source). Fresh
public before/after builds passed the same exclusion and helper-symbol checks.
Both pilots passed. Full-response fingerprints and byte lengths matched in
all ten measured processes; reader/persistent-connection and cleanup checks
passed. This comparison is not pooled with the combined-context measurements.

| Page | Before ms | After ms | Change | Paired range |
| --- | ---: | ---: | ---: | ---: |
| plain | 3.628 | 3.637 | +0.3% | -0.8% to +2.8% |
| fields=0 | 4.788 | 4.756 | -0.7% | -1.2% to +1.4% |
| fields=8 | 6.754 | 6.806 | +0.8% | -0.3% to +1.5% |
| fields=64 | 18.338 | 18.122 | -1.2% | -5.3% to -0.1% |
| actions | 11.954 | 11.911 | -0.4% | -1.0% to +1.0% |

The standalone 64-field page improves in all five pairs, with a 1.2% change
between process medians. The eight-field median is 0.8% slower and four of five
pairs are slower. Other page types have mixed pairs and small median changes.
These results support a targeted allocation reduction with modest request gains
for the largest fixture. They do not support an ordinary-page speedup claim.

## Validation and source scope

[validation.json](validation.json) records 229 selected race test/subtest passes
with no failures or skips in the combined context (model: 102, app: 110, API: 17),
alongside the two stress fuzz runs. The standalone candidate content also passed
93 selected model race tests/subtests before its source commit. Those passes
are separate and are not added to the combined-context count. Tests include
metadata preparation, image/proxy handling, custom emoji extraction, history
APIs and incoming webhook content.

The validator, decoded-object construction and fallback bodies match their
original source regions after normalizing whitespace and the stated return
plumbing. These text checks supplement the runtime oracles; they do not replace
them. The publication source is a4a496745bb3, stacked on PR #58. Its four changed
source files match the combined test/HTTP source byte-for-byte.

Both HTTP backends built with production tags, explicit non-dev build numbers
and BuildEnterpriseReady=false. Build-info and symbol checks found no enterprise
or sourceavailable tags or enterprise symbols. The baseline's extra validation
and JSON helper declarations are absent from its linked symbols, confirming
they are unused. The candidate links all three new helper functions.

All 40 publication patches apply cleanly, and the previous 39 patch files are
byte-identical. There are no changes to dependencies, settings, schema,
branding, copyright headers or release guards. Both standalone public backends also build and pass symbol exclusions. No
frontend/full-release build or complete-repository test run is claimed.

For standalone HTTP measurements, use this contribution's normal unbranded
workspace. For the combined study, use the combined context described above and
copy http_build.py and http_requests.py under the same docs path. Provide a
matching Go SDK root if the active SDK cannot run go tool nm:

```sh
python3 docs/benchmarks/attachment-image-map-reads/http_build.py --output /tmp/attachment-image-http-build --nm-goroot /path/to/matching/go-sdk
python3 docs/benchmarks/attachment-image-map-reads/http_requests.py --build-report /tmp/attachment-image-http-build/build.json --output /tmp/attachment-image-http-results --trials 5 --requests 1000 --warmup 100
```

The HTTP runner expects disposable PostgreSQL in container
mattermax-upstream-tests on port 55439, with the fixture credentials shown in
the script. It binds loopback and creates/removes its own databases. Both
runners use Python's standard library. Run timing without concurrent builds or
tests. The build runner recognizes either documented parent tree and records
the chosen context; it does not silently combine measurements from them.
