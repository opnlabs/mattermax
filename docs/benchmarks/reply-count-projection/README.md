# Index-only reply counts on save

Save delegates to SaveMultiple, which fetches grouped counts for every saved
reply. Its query reads RootId and counts non-deleted rows. Posts.Id is a non-null
primary key, so COUNT(*) returns the same values as COUNT(Id). It lets the existing
RootId/DeleteAt index cover the query without fetching Id from the table.
PostgreSQL still checks heap visibility where its visibility map requires it.

The production change is one expression. Filters, grouping, root deduplication,
query chunking, missing-root zero values and error handling stay unchanged. No
schema, index, HTTP API, configuration or third-party dependency changes. This
contribution is independent of PR #55 and uses the original 38-patch baseline.
All inherited patches remain byte-identical, including @mr-karan's work.

## Method

Go 1.26.10, GOMAXPROCS=4, local PostgreSQL, one serial caller. Three process pairs
alternate before/after order with 200 fixed operations per case. Each process
gets a fresh database. The baseline overlay restores only the original production
file. Fixtures, validation and index definitions are shared; the runner checks
that definitions match across all processes. [results.json](results.json) records
every sample, command, index definition, plan, source hash and log digest.

Fixtures have one or ten real root posts and initially 0, 1,000 or 10,000 replies
per root. Reply rows are interleaved, messages are roughly 700 bytes, and every
seventh reply is deleted. Vacuumed cases explicitly VACUUM ANALYZE Posts; fresh
cases only ANALYZE after seeding. Autovacuum and later writes can change visibility,
so before/after plans are retained for each method.

Populate invokes the actual helper without writes. Save uses the real Save method
for one root, or SaveMultiple for ten roots, adding one reply per root each time.
Every returned ReplyCount is checked as history grows, including warmup/calibration
writes. Root controls save one new root and skip the changed aggregate. Seeding,
visibility preparation, expected-count setup, plans and cleanup are untimed.

## Count-helper timings

Values are medians and complete trial ranges in ms per aggregate call.

| Initial replies/root | Roots | Preparation | Before ms | After ms | Median change |
| ---: | ---: | --- | ---: | ---: | ---: |
| 0 | 1 | vacuumed | 0.208 (0.206 to 0.228) | 0.207 (0.203 to 0.234) | -0.4% |
| 0 | 1 | fresh | 0.252 (0.252 to 0.252) | 0.255 (0.227 to 0.259) | +1.1% |
| 0 | 10 | vacuumed | 0.314 (0.293 to 0.318) | 0.294 (0.284 to 0.332) | -6.4% |
| 0 | 10 | fresh | 0.303 (0.302 to 0.306) | 0.308 (0.295 to 0.310) | +1.8% |
| 1000 | 1 | vacuumed | 0.415 (0.386 to 0.419) | 0.285 (0.284 to 0.299) | -31.3% |
| 1000 | 1 | fresh | 0.430 (0.421 to 0.444) | 0.421 (0.417 to 0.426) | -2.0% |
| 1000 | 10 | vacuumed | 3.046 (3.028 to 3.079) | 1.076 (1.066 to 1.078) | -64.7% |
| 1000 | 10 | fresh | 3.424 (3.156 to 3.462) | 3.313 (3.211 to 3.326) | -3.2% |
| 10000 | 1 | vacuumed | 2.020 (1.969 to 2.039) | 0.688 (0.645 to 0.690) | -66.0% |
| 10000 | 1 | fresh | 2.386 (2.349 to 2.484) | 2.368 (2.280 to 2.851) | -0.7% |
| 10000 | 10 | vacuumed | 16.072 (15.234 to 16.406) | 5.582 (5.310 to 6.420) | -65.3% |
| 10000 | 10 | fresh | 19.847 (19.669 to 20.242) | 19.369 (19.197 to 19.441) | -2.4% |

## Full saves and controls

Each save operation writes one or ten replies as described above. Each control
writes one root. These complete-store timings include transaction, channel and
thread work. Controls also move, so the full timing differences do not isolate
the changed aggregate. They support no whole-server write-latency or capacity
claim. All cases, including slower results, remain below and in the raw report.

| Initial replies/root | Roots | Preparation | Operation | Before ms | After ms | Median change |
| ---: | ---: | --- | --- | ---: | ---: | ---: |
| 0 | 1 | vacuumed | save | 27.309 (19.280 to 37.888) | 25.403 (23.589 to 36.359) | -7.0% |
| 0 | 1 | vacuumed | root_control | 15.391 (14.915 to 16.949) | 14.359 (14.081 to 16.887) | -6.7% |
| 0 | 1 | fresh | save | 31.904 (22.705 to 32.833) | 25.532 (20.234 to 26.506) | -20.0% |
| 0 | 1 | fresh | root_control | 15.066 (14.214 to 16.675) | 15.723 (15.467 to 16.166) | +4.4% |
| 0 | 10 | vacuumed | save | 105.983 (102.112 to 106.976) | 103.301 (91.728 to 109.270) | -2.5% |
| 0 | 10 | vacuumed | root_control | 14.765 (14.255 to 19.481) | 15.380 (14.394 to 16.945) | +4.2% |
| 0 | 10 | fresh | save | 98.609 (93.261 to 104.206) | 112.636 (94.089 to 122.025) | +14.2% |
| 0 | 10 | fresh | root_control | 15.004 (13.888 to 16.897) | 16.610 (14.919 to 18.736) | +10.7% |
| 1000 | 1 | vacuumed | save | 24.685 (21.089 to 60.648) | 26.230 (23.959 to 31.410) | +6.3% |
| 1000 | 1 | vacuumed | root_control | 14.365 (13.223 to 15.169) | 15.935 (13.710 to 17.629) | +10.9% |
| 1000 | 1 | fresh | save | 24.233 (23.179 to 24.488) | 22.671 (21.889 to 24.410) | -6.4% |
| 1000 | 1 | fresh | root_control | 17.001 (13.494 to 18.417) | 14.897 (14.363 to 15.105) | -12.4% |
| 1000 | 10 | vacuumed | save | 98.726 (83.479 to 105.515) | 110.086 (92.751 to 113.641) | +11.5% |
| 1000 | 10 | vacuumed | root_control | 13.886 (12.524 to 16.235) | 16.792 (15.298 to 17.750) | +20.9% |
| 1000 | 10 | fresh | save | 103.157 (93.977 to 105.364) | 113.152 (103.487 to 149.676) | +9.7% |
| 1000 | 10 | fresh | root_control | 14.359 (13.072 to 36.497) | 15.923 (12.484 to 16.668) | +10.9% |
| 10000 | 1 | vacuumed | save | 28.117 (26.320 to 69.607) | 26.867 (20.547 to 29.120) | -4.4% |
| 10000 | 1 | vacuumed | root_control | 16.802 (14.346 to 17.859) | 15.716 (13.111 to 21.649) | -6.5% |
| 10000 | 1 | fresh | save | 26.512 (25.575 to 27.360) | 28.506 (27.804 to 29.398) | +7.5% |
| 10000 | 1 | fresh | root_control | 14.742 (14.030 to 15.503) | 14.942 (14.430 to 15.406) | +1.4% |
| 10000 | 10 | vacuumed | save | 92.064 (85.708 to 102.469) | 98.078 (91.507 to 116.546) | +6.5% |
| 10000 | 10 | vacuumed | root_control | 13.358 (11.224 to 16.914) | 17.902 (15.480 to 20.043) | +34.0% |
| 10000 | 10 | fresh | save | 107.001 (105.724 to 142.929) | 115.113 (110.376 to 149.271) | +7.6% |
| 10000 | 10 | fresh | root_control | 18.025 (15.919 to 22.053) | 14.452 (13.866 to 29.947) | -19.8% |

## Isolated save/control follow-up

The following cases run in separate fresh processes, with three alternating
pairs and 200 operations per process. Earlier helper/write modes do not execute
in those processes. Full raw reports retain the exact filters and plans.

| Case | Before ms | After ms | Median change |
| --- | ---: | ---: | ---: |
| fresh_single_save | 24.167 (24.112 to 36.980) | 30.351 (29.057 to 33.675) | +25.6% |
| fresh_single_control | 14.391 (13.994 to 20.084) | 16.714 (16.120 to 26.395) | +16.1% |
| vacuumed_batch_save | 105.053 (102.312 to 119.820) | 73.986 (73.273 to 101.419) | -29.6% |
| vacuumed_batch_control | 12.338 (10.013 to 13.118) | 10.618 (10.255 to 11.117) | -13.9% |

The isolated vacuumed batch improves in every pair, but its unchanged root
control also improves. Fresh single saves and controls have higher medians with
overlapping ranges. These results do not isolate every full-write difference.
The primary claim is less count-query work when index-only scans are eligible;
there is no unconditional posting-latency improvement claim.

## Query work

For one vacuumed root with 10,000 initial replies, the first paired plan uses a
sequential table scan before and the existing-index-only scan after. The plan
records 1,326 versus 9 shared buffer hits, and zero heap fetches for the new scan.
This is a representative plan, not a production-wide I/O ratio. All plan nodes
and visibility states are retained in results.json. Index definitions are
identical; no additional index or index-maintenance work is introduced.

## Validation

Selected race suites pass with 495 parent/subtest pass events and no failures or
skips. They include complete PostStore checks through SQL/cache, SQL ThreadStore,
count equivalence and forced chunking, plus selected posting/history/thread API
suites. The first local-time run exposed an existing date-test assumption: the
original production code also fails PostCountsByDuration in Asia/Kolkata after
local midnight. Its baseline passes under UTC. The complete current race run
uses TZ=UTC; no date-test or production workaround is included. Both runner
variants pass all 36 single-iteration execution/output checks.
All 39 patches apply cleanly; the 38 inherited patch files are byte-identical.

The public production backend builds with a non-dev build number and source hash,
BuildEnterpriseReady=false and the unchanged release script's enterprise tag/symbol
exclusion criteria. A loopback instance migrates a fresh database, loads the
settings overlay and answers ping/client-config probes with HTTP 200 and the
expected build number. Server, database and temporary runtime are removed.
Full branded packaging, browser flows and production load tests were not run.
[validation.json](validation.json) records exact commands and revision scopes.

## Reproduce

Use the standalone PR branch, Go 1.26.10 and disposable PostgreSQL/Redis services.
Set TEST_DATABASE_POSTGRESQL_DSN and TEST_REDIS_ADDR. Use TZ=UTC for the selected
race suites to match the date-grouping test assumption. After just workspace and
just check, keep only server and public in go.work. From the patch repository:

```sh
python3 docs/benchmarks/reply-count-projection/benchmark.py --workspace work/src/server --baseline HEAD^ --iterations 200 --trials 3 --output /tmp/reply-count-projection/results.json
```

The runner supports --bench and --expected-cases for selected cases. Timing data
comes from non-race execution; race and single-iteration runs only check behavior.
Git-am commit IDs can differ. Compare source trees and file hashes when rebuilding.
