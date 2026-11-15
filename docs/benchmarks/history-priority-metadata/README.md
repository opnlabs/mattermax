# Combined priority and acknowledgement metadata reads

A combined-stack plain-history profile attributes 1.20s to
GetPriorityForPostList and 0.97s to GetAcknowledgementsForPostList within 3.16s
beneath PreparePostListForClient. These are overlapping call-stack samples from
one workload, not a before/after improvement. The profile motivates reducing the
two independent replica reads made during list preparation.

This independent candidate starts from the original 38-patch parent. It adds
an optional PostPriorityMetadataReader capability to the existing priority
store. PostgreSQL reads both metadata tables with one UNION ALL query per
200-ID chunk. The union avoids multiplying priority rows by acknowledgement
counts. Streaming scans retain nullable flags and remote IDs, negative nonzero
acknowledgement times, missing IDs and duplicate IDs across chunks.

New optional forwarding methods preserve the existing retry limit/backoff and
store timing. An unavailable capability is not counted as a failed store
operation. Base store interfaces, generated wrappers and mocks are unchanged.
The app fetches the priority store once and tries the capability. If unavailable
or failed, it performs the two existing reads independently and keeps each
successful result. Partial results returned with an error remain discarded.
Failure fallback can perform extra queries; no unchanged failure-path latency
claim is made. The feature-disabled branch still skips metadata reads.

## Targeted correctness checks

The first selected race run passed 40 parent/subtest events across app, SQL,
retry and timing packages, with no failures or skips. Tests cover actual store
capability reachability through decorators, metadata output and lookup counts,
independent fallback errors, partial results, nullable flags/remote IDs,
zero/NULL/negative acknowledgement times, missing/duplicate IDs, 200-ID chunk
boundaries, output ownership and scan failure after a successful earlier chunk.
The retry checks include serialization/deadlock errors, exhaustion and ordinary
errors. Timing checks include success/failure, nil metrics and unavailable
capability forwarding.

## Controlled preparation comparison

The runner uses three alternating before/after pairs, each in a fresh app test
process with Go 1.26.10, GOMAXPROCS=4, GOGC=100 and TZ=UTC. Each of 18 cases runs
100 preparations: 1, 60 or 201 SQL-read posts, each with empty, priority-only,
acknowledgement-only, mixed, dense or feature-disabled metadata. Setup is outside
timing. Priority/custom emoji reads are enabled except the disabled control;
previews and image proxying are off. There are no files, attachments or reactions.

A Go overlay restores the original post_metadata.go for the baseline. That
entry point uses the original independent reads. Both variants compile the new
capability files, including their shared error sentinel, and identical fixtures.
The capability is not called by the baseline preparation entry point. Source,
overlay, producer and raw-log hashes are saved with all samples.

Output checks run inside the preparation timer. They inspect ordered pages and
all priority/acknowledgement fields. The SQL store does not promise acknowledgement
row order; checks preserve all values and multiplicity without assuming a query
plan's row order. Generated users/post IDs differ across fresh processes.
These are synthetic preparation measurements, separate from HTTP or concurrent
throughput. Every case, including slower disabled controls, stays in the report.

## Preparation results

All six processes passed their output checks. results.json retains every raw
sample and summary.json reports medians and all paired changes. On 60-post
pages, median preparation time fell 24.2% for empty metadata, 25.7% for
priorities, 23.3% for acknowledgements, 23.5% for mixed metadata and 24.7% for
dense metadata. One empty-metadata pair was 7.4% slower; the other two were
24.2% and 29.4% faster. Across all enabled fixtures the paired changes range
from 41.3% faster to 7.4% slower. Disabled controls range from 34.4% faster to
11.1% slower, with unchanged allocation counts. No disabled-path speed claim
is made.

The candidate source commit is bc6b1680c1dbdeb42f3e48357e091605f44ae6a4,
with tree 63b61682cedda27cc44c992cb7dd0ddada72d68b. Its original38 parent is
c9dbbcc480b242f7349cb7f4e9dcb6ea35cf6404, with tree
a2da7f25de10aadbb8974f5f6191aa082ec6e6e6. Fresh exports can have different
commit IDs while retaining these source trees.

## Reproduce

Create this branch's unbranded workspace with just workspace. Use Go 1.26.10
with only server and public in go.work, and set TEST_DATABASE_POSTGRESQL_DSN and
TEST_REDIS_ADDR to disposable services. Set GOPATH/GOCACHE/GOMODCACHE as needed.
From the repository root:

```sh
python3 docs/benchmarks/history-priority-metadata/benchmark.py --output /tmp/history-priority-results
```

The runner checks the original parent's source tree rather than its local
commit ID, so a fresh git-am workspace can reproduce it. Results must not be
multiplied with other PR ratios or presented as combined server throughput.

The HTTP runners perform a separate isolated comparison. They create
priority and acknowledgement fixtures through public APIs, then switch the
single priority setting once through the admin API before warmup. The ordinary
reader and three known acknowledgement users remain explicit in validation;
acknowledgement timestamps and all fields are checked against creation responses.
Acknowledgement array order is canonicalized only for cross-process fingerprints;
all raw acknowledgement fields and multiplicity are checked first. Enabled and
disabled feature runs have separate reports.

## Broader correctness and public builds

The broader selected race run passed 175 parent/subtest events with no failures
or skips: retrylayer 14, timerlayer 6, sqlstore 37, app 90 and api4 28.
Packages ran serially. race-tests.json records the exact selection and source
revision; this is not a full server-suite run.

Both before/after public production binaries built successfully with explicit
non-dev build numbers and BuildEnterpriseReady=false. Build metadata and symbol
checks excluded enterprise/sourceavailable tags and enterprise symbols. The new
preparation entry point is absent from the baseline binary and present in the
candidate. http-build.json records the producer and binary hashes.

Both enabled and disabled HTTP pilots passed strict output checks on 60-post
pages for empty, priority-only, acknowledgement-only, mixed and dense fixtures.
Each process seeded 300 posts and 420 acknowledgements through public APIs.
The reader is an ordinary team/channel member. Disposable databases, server
processes and runtime directories are removed after each run.

## Authenticated HTTP comparison

The enabled study completed five alternating pairs, with 1,000 measured and
100 warmup requests per fresh server process. Across 10,000 measured requests,
the median of per-process mean latency fell 7.1%, from 3.588ms to 3.333ms.
All five aggregate pairs improved, ranging from 3.6% to 10.7%. The per-fixture
median reductions were 6.8% empty, 6.9% priority-only, 6.8% acknowledgements,
7.3% mixed and 9.0% dense. All response fingerprints and field checks passed.
See http-enabled.json and http-enabled-summary.json for all samples.

These are localhost HTTP/1.1 requests without TLS or concurrent clients. Timing
ends after the complete response body is read, before JSON decoding and output
assertions. The process wall-loop time includes those checks. The comparison
supports a local latency claim for these fixtures; it does not estimate
production throughput or tail latency.

Reproduce public binary builds, then the enabled comparison and summary:

```sh
python3 docs/benchmarks/history-priority-metadata/http_build.py --output /tmp/history-priority-build
python3 docs/benchmarks/history-priority-metadata/http_requests.py --build-report /tmp/history-priority-build/build.json --output /tmp/history-priority-http-enabled --priority enabled
python3 docs/benchmarks/history-priority-metadata/summarize_http.py /tmp/history-priority-http-enabled/http.json --output /tmp/history-priority-http-enabled/summary.json
```

The HTTP harness expects owned disposable PostgreSQL in the Docker container
named mattermax-upstream-tests, listening on localhost port 55439. Use the
fixture credentials in the runner only for this disposable service. The build
runner's --nm-goroot option accepts the GOROOT matching the build toolchain
when the default go tool nm cannot decode that binary's object format.
Use --priority disabled with a separate output directory for the control.

The separate disabled study also completed five alternating pairs and 10,000
measured requests with all output checks passing. The median of process means
changed -0.56%, with paired changes ranging from
-2.00% to +2.40%.
These mixed controls support no disabled-path speed claim. All samples remain
in http-disabled.json and http-disabled-summary.json.
