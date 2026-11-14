# Aggregate user-thread response counts

The user-thread response requests up to four separate counts before returning
totals and a page. One internal store method computes total threads, unread
threads, mentions and optional urgent mentions with one aggregate statement.
Individual getters remain available to notification and other callers. The
application copies only the count fields, so the concurrent page result remains
separate.

The method reuses the existing team/DM, deletion and membership filters.
Unread keeps its legacy duplicate total. ThreadsOnly skips all count queries;
TotalsOnly skips the page; both flags together keep the existing empty response.
The disabled priority branch does not reference PostsPriority, whose PostId
primary key prevents row multiplication when the urgent join is enabled.

This contribution is independent of the other performance PRs and starts from
the original 38-patch Mattermax baseline. All inherited patches remain
byte-identical. The internal store interface, generated timing/retry adapters
and mock are extended. No HTTP API, schema, configuration or runtime dependency
changes.

## Measurements

Three alternating-order process pairs use Go 1.26.10, GOMAXPROCS=4 and local
PostgreSQL/Redis services. A Go overlay restores only `channels/app/user.go`'s original
count dispatcher. The added store method and adapters remain compiled but are
unused by that baseline path. All other production code, fixtures and output
checks are identical. [results.json](results.json) records every sample,
median, range, command and exact source.

Each case uses 1,000 fixed iterations. Real users, team/channel memberships,
root posts, replies, thread memberships and optional priorities are created
outside the timer through existing store/App helpers. The dataset has zero,
ten or one thousand followed threads, with half unread, varying mention
counts and urgent priority on every fourth thread when enabled.

Both totals-only and paged responses are validated. Paged cases check the
returned roots, replies, member read state and urgency flags. Threads-only
controls exercise the unchanged no-count path. Every operation checks all
count fields, page size and data.

The database pool allows eight open/eight idle connections. Serial cases use
one caller; 1,000-thread cases also run four callers sharing the same pool.
Parallel ns/op is amortized wall time per completed operation, not per-request
latency. The application method is timed, without HTTP authentication/transport.

| Priority | Threads | Response | Callers | Before ms/op | After ms/op | Before allocs/op | After allocs/op |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| false | 0 | page | serial | 1.153125 | 1.118425 | 985 | 613 |
| false | 0 | threads_only | serial | 1.091994 | 0.768627 | 383 | 383 |
| false | 0 | totals | serial | 0.616715 | 0.500951 | 604 | 231 |
| false | 10 | page | serial | 1.391656 | 1.375411 | 1506 | 1133 |
| false | 10 | threads_only | serial | 1.322764 | 1.155756 | 903 | 903 |
| false | 10 | totals | serial | 0.662785 | 0.627733 | 604 | 231 |
| false | 1000 | page | parallel | 3.802913 | 1.616036 | 2530 | 2149 |
| false | 1000 | page | serial | 6.174863 | 5.982920 | 2521 | 2148 |
| false | 1000 | threads_only | parallel | 2.220248 | 1.542310 | 1916 | 1916 |
| false | 1000 | threads_only | serial | 5.370873 | 5.123072 | 1916 | 1916 |
| false | 1000 | totals | parallel | 1.890110 | 0.720215 | 614 | 234 |
| false | 1000 | totals | serial | 3.740814 | 2.042243 | 607 | 234 |
| true | 0 | page | serial | 1.514318 | 1.333267 | 1261 | 687 |
| true | 0 | threads_only | serial | 1.400243 | 0.892624 | 441 | 441 |
| true | 0 | totals | serial | 0.988194 | 0.656918 | 821 | 247 |
| true | 10 | page | serial | 2.051628 | 1.617373 | 1781 | 1207 |
| true | 10 | threads_only | serial | 1.678005 | 1.073670 | 961 | 961 |
| true | 10 | totals | serial | 1.089654 | 0.775917 | 821 | 247 |
| true | 1000 | page | parallel | 2.770508 | 1.179903 | 2810 | 2223 |
| true | 1000 | page | serial | 7.669721 | 6.777702 | 2797 | 2223 |
| true | 1000 | threads_only | parallel | 2.067156 | 1.108841 | 1974 | 1974 |
| true | 1000 | threads_only | serial | 6.474336 | 3.264557 | 1974 | 1974 |
| true | 1000 | totals | parallel | 1.728814 | 0.810564 | 836 | 251 |
| true | 1000 | totals | serial | 3.978597 | 2.577315 | 825 | 251 |

The full-matrix timing results require caution: threads-only controls show
large gains despite skipping counts in both variants. This matrix is retained
in full but is not used for causal latency claims.

A follow-up isolates each response mode into its own process, with 1,000
followed threads, priority enabled, serial calls, the same eight-connection pool,
1,000 fixed iterations and three alternating pairs. No earlier mode executes in
that process. [isolated-results.json](isolated-results.json) retains all samples
and commands.

| Isolated mode | Before ms/op | After ms/op | Median change |
| --- | ---: | ---: | ---: |
| Totals only | 4.036405 | 3.745213 | 7.2% lower |
| Paged | 7.522236 | 7.199269 | 4.3% lower |
| Threads only, no counts | 6.626779 | 6.311404 | 4.8% lower |

Totals-only and paged calls improve in every isolated pair, with non-overlapping
ranges. The no-count control has overlapping ranges and one slightly slower
pair. Its variation means the paged timing gain cannot be assigned solely to
count aggregation. The primary claim is reduced database work and allocation
use: up to four count statements become one, and priority-enabled totals-only
calls use 251 allocations instead of 825 in the 1,000-thread fixture. The
threads-only control retains its allocation counts.

These results cover this standalone source and the specified workload, not
whole-server throughput or production capacity. They are not combined-stack
measurements; ratios from separate PRs must not be multiplied together.

## Validation

The SQL comparison covers 64 flag/team combinations against the unchanged
individual count methods, with null/negative values, deleted/unfollowed threads,
lost membership, orphan rows and DM exceptions. App tests verify count/page
flags, unread duplication, priority propagation, error identity and page data
isolation. Existing thread-store, thread API, membership-removal/reinvite,
follow/read and root-post sanitization suites pass under the race detector.

The old App dispatcher also passes selected existing API and root-sanitization
checks through the baseline overlay. The 24 benchmark cases pass race execution/
output checks; those timings are not performance evidence. [validation.json](validation.json)
records counts, commands and source scopes.

All 39 patches apply cleanly. The public production backend builds and passes
the release script's enterprise tag/symbol exclusion criteria. Full branded
packaging, browser flows and production load testing were not run.

## Reproduce

Use Go 1.26.10 and the normal server/public go.work. Set
TEST_DATABASE_POSTGRESQL_DSN and TEST_REDIS_ADDR to disposable local test services.
After just workspace, run from this repository's root:

```sh
GOMAXPROCS=4 python3 docs/benchmarks/user-thread-count-aggregation/benchmark.py --workspace work/src --baseline HEAD^ --iterations 1000 --trials 3 --output /tmp/user-thread-count-aggregation/results.json
```

Run the isolated follow-up separately:

```sh
GOMAXPROCS=4 python3 docs/benchmarks/user-thread-count-aggregation/benchmark.py --workspace work/src --baseline HEAD^ --iterations 1000 --trials 3 --isolated --output /tmp/user-thread-count-isolated/results.json
```

Run the validation commands from work/src/server. Store layers use
`go generate ./channels/store`; mocks use the project-pinned mockery v2.53.4
configuration. Compare source tree hashes when reconstructing the workspace,
since git-am commit IDs can differ.
