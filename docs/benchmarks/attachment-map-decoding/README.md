# Attachment map decoding

`Post.Attachments` currently marshals each wire-format map to JSON and then
unmarshals it into a MessageAttachment. Metadata preparation can repeat this
conversion while collecting emoji text, markdown images and attachment image
URLs. A baseline stored-history CPU profile attributes 1.37 seconds beneath
Attachments out of 1.88 seconds beneath PreparePostListForClient, within 2.68
seconds of total sampled CPU. The profile includes setup; its stack attribution
motivates the change and is not a comparative latency measurement.

The patch decodes a strict subset of ordinary JSON maps directly into fresh
objects. It validates keys and scalar types before allocation. Unknown keys,
nonempty actions, structured values, Slack boolean strings/nulls, unusual
numeric IDs, custom values and invalid UTF-8 use the unchanged JSON fallback.
The typed-slice path is unchanged. There is no shared decoded-object cache.

The legacy JSON implementation is retained as a test oracle. Tests compare
200,000 deterministic generated inputs, field copies, Unicode and numeric
edges, nil/empty/null collection behavior, custom marshaling and ownership.
The refined implementation also passed a 30-second fuzz run with 272,177
executions. Unsupported inputs retain the old decoder's normalization/errors.

## Controlled component and stored-history comparison

The candidate is source `9e85f87af81b`, over the original 38-patch parent
`c9dbbcc480b2`. A Go overlay substitutes only the original model/post.go for
baseline runs. The new helper has no initialization side effects and is not
called by the baseline accessor. Test/fixture files are identical. Source and
file hashes, every command and all samples are in [results.json](results.json).

Three alternating before/after pairs ran with Go 1.26.10, GOMAXPROCS=4 and
GOGC=100. Each variant uses separate model and app processes. Model cases run
for 300 ms; history cases run for 200 preparations. These are synthetic local
component/preparation workloads, not production throughput measurements.

Model timings below are microseconds per accessor call. Change is the ratio of
process medians; paired ranges compare corresponding runs.

| Case | Before us | After us | Change | Paired range |
| --- | ---: | ---: | ---: | ---: |
| plain | 0.027 | 0.029 | +5.3% | +3.3% to +11.4% |
| typed | 0.014 | 0.015 | +3.0% | +0.2% to +9.1% |
| fields=0 | 3.337 | 0.531 | -84.1% | -84.7% to -83.1% |
| fields=8 | 12.153 | 1.658 | -86.4% | -87.3% to -85.4% |
| fields=64 | 76.719 | 9.761 | -87.3% | -88.0% to -86.5% |
| actions | 14.098 | 14.697 | +4.2% | +3.9% to +6.8% |
| unknown | 12.802 | 12.926 | +1.0% | -1.0% to +15.6% |
| structured | 12.529 | 12.639 | +0.9% | -1.3% to +1.7% |
| malformed | 12.244 | 12.152 | -0.8% | -3.4% to +6.5% |

History timings below are milliseconds per 60-post page. Fixtures are saved and
read back through SQL to ensure []any/map wire representation. Priority/custom
emoji reads are enabled, link previews are off, caches are warm, and there are
no files or image URLs. Output assertions inspect raw props and metadata,
without calling Attachments again in the timed validation. The timer includes
those assertions. Actions are a nonempty-action fallback control.

| Case | Before ms | After ms | Change | Paired range |
| --- | ---: | ---: | ---: | ---: |
| plain | 0.767 | 0.774 | +1.0% | -28.0% to +4.4% |
| fields=0 | 2.886 | 1.345 | -53.4% | -58.8% to -52.7% |
| fields=8 | 5.862 | 2.395 | -59.1% | -59.2% to -54.9% |
| fields=64 | 20.366 | 9.330 | -54.2% | -55.1% to -53.1% |
| actions | 6.277 | 6.171 | -1.7% | -3.2% to +8.6% |

No ordinary-page or typed-path speedup is claimed. Their accessor differences
are small in absolute time and slower observations remain visible. Fallback
model/history cases have mixed results. [summary.json](summary.json) preserves
allocation medians and all paired changes, including regressions.

## Initial implementation

[initial-results.json](initial-results.json) and
[initial-summary.json](initial-summary.json) preserve the first three-pair study
at source `c0953e036522`. Its scalar-valued rich-history cases improved, but
structured-value and malformed-boolean accessor controls regressed by median
5.9% and 8.8%. The refinement rejects those shapes before walking text/key data.
It keeps the same fast-path domain and output behavior. The original helper is
retained in [initial-helper.go.txt](initial-helper.go.txt), matching the source
hash recorded in that study. No initial slower cases were dropped.

## Reproduce

Create the branch's unbranded workspace with `just workspace`. Use Go 1.26.10
with only server and public in go.work. Set TEST_DATABASE_POSTGRESQL_DSN and
TEST_REDIS_ADDR to disposable services. Set GOPATH/GOCACHE/GOMODCACHE as needed.
From this repository root:

```sh
python3 docs/benchmarks/attachment-map-decoding/benchmark.py --output /tmp/attachment-map-results
```

The runner requires the original parent tree, checks all changed source files,
uses a temporary overlay and saves all samples plus raw log hashes. No source
files are rewritten. These standalone measurements do not establish the
combined contribution stack's throughput and must not be multiplied with other
PR ratios.

## Validation

[validation.json](validation.json) records checks against source
`9e85f87af81bbf7ae1e85d0ea330f4b02ca59cef`: 87 model and 292 selected app/API
race test/subtest passes, with no failures or skips. All five stored-history
benchmark cases executed once under the race detector for coverage only.
The 30-second fuzz run completed 272,177 executions without an oracle mismatch.
All 39 patches apply cleanly; the original 38 patch files are byte-identical.

Both HTTP binaries built with only the production tag, explicit non-dev build
numbers and BuildEnterpriseReady=false. Build-info and symbol checks found no
enterprise/sourceavailable tags or enterprise symbols. These checks cover the
public backend, selected tests and this independent patch. They do not claim a
frontend/full-release build or integration with the other performance PRs.

## Authenticated HTTP comparison

[http-results.json](http-results.json) contains all 10,000 timed request samples;
[http-summary.json](http-summary.json) contains process means and paired changes.
Five alternating before/after pairs used fresh public backend processes and
fresh databases. Each process created 300 posts through the public APIs, warmed
100 requests and measured 1,000 requests, equally split among five page types.
An ordinary team/channel member read each 60-post history page over one verified
persistent HTTP/1.1 connection. Priority/custom emoji reads were enabled;
previews, jobs, plugins, email and diagnostics were disabled.

Timing spans sending the request through reading its complete response body.
JSON decoding, output assertions and fingerprinting happen outside the timer.
All requests returned HTTP 200. Post order, content, raw fields, action/embed
metadata and normalized full responses matched across every process. Response
byte lengths also matched. Normalization replaces generated IDs and timestamps.
All temporary databases, servers and runtime directories were removed.

Timings below are milliseconds per request, taking the median of the five
process means for each variant. Paired ranges compare corresponding processes.

| Page | Before ms | After ms | Change | Paired range |
| --- | ---: | ---: | ---: | ---: |
| plain | 3.695 | 3.668 | -0.7% | -2.9% to -0.4% |
| fields=0 | 6.667 | 4.771 | -28.4% | -29.3% to -27.4% |
| fields=8 | 10.996 | 6.806 | -38.1% | -39.1% to -37.6% |
| fields=64 | 34.724 | 18.317 | -47.3% | -47.7% to -46.6% |
| actions | 11.733 | 11.883 | +1.3% | +0.5% to +3.2% |

The scalar attachment fixtures improved by 28-47% in this HTTP workload.
The action fallback was slower in every pair, with a median increase of 1.3%;
this change adds an eligibility check before the existing JSON path. Plain
pages differ by less than 1% between process medians, and no plain-page gain is
claimed. These are localhost, single-client synthetic history requests without
TLS. They do not establish concurrent throughput or production tail latency.

To reproduce, first build the two public backends, then run requests without
concurrent builds or tests. Provide a matching Go SDK root for symbol inspection
if the active SDK cannot run go tool nm:

```sh
python3 docs/benchmarks/attachment-map-decoding/http_build.py --output /tmp/attachment-http-build --nm-goroot /path/to/matching/go-sdk
python3 docs/benchmarks/attachment-map-decoding/http_requests.py --build-report /tmp/attachment-http-build/build.json --output /tmp/attachment-http-results --trials 5 --requests 1000 --warmup 100
```

The HTTP runner currently expects disposable PostgreSQL in container
`mattermax-upstream-tests` on port 55439, with the fixture credentials shown in
the script. It never uses the database on port 5432. It binds only loopback and
creates its own databases. Both runners use only Python's standard library.
