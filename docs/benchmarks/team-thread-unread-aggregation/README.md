# Aggregate team thread unread counts in one query

GetTeamsUnreadForUser runs two aggregate queries, or three when urgent mentions
are enabled. Each filters the same followed threads and memberships. One grouped
query computes the unread-thread count and mention sums together. This removes
the per-call query goroutines and uses one database statement and connection
at a time instead of two or three concurrent statements.

The urgent-enabled query left-joins PostsPriority. Its PostId primary key
prevents row multiplication. The disabled branch does not reference that table.
Channel-membership filtering, DM/GM exceptions, deleted/followed rules and
zero-valued team groups retain their existing behavior. TeamUnread.TeamId stays
empty at the store layer; the map key identifies the team, as before. Failures
still discard the result and propagate an error.

This contribution is independent of the other performance PRs. It starts from
the original 38-patch Mattermax baseline. All inherited patches remain
byte-identical, preserving their features and authorship. No API, schema,
configuration or dependency changes.

## Measurements

Three alternating-order process pairs use Go 1.26.10, GOMAXPROCS=4 and loopback
PostgreSQL. A Go overlay restores only thread_store.go for baseline; benchmark
fixtures and output checks are identical. Each case uses 1,000 fixed iterations,
with fixture creation outside the timer. [results.json](results.json) contains
every sample, median, range, command and source hash.

Fixtures contain zero, ten or one thousand followed threads for one user/team,
with half unread, varying mention counts and urgent priority on every fourth
thread. They seed the public query tables directly and are SQL-store fixtures,
not complete HTTP scenarios. Every operation validates map shape and all count
fields. The empty case verifies a non-nil empty map.

The pool allows eight open and eight idle connections. Serial cases have one
caller. Parallel cases use testing.B.RunParallel with four workers sharing that
pool. Their ns/op measures amortized wall time per completed operation, not
per-request latency. Both variants use the same pool limit and caller count.

| Threads | Urgent count | Mode | Before ms/op | After ms/op | Before allocs/op | After allocs/op |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 0 | false | parallel | 0.164467 | 0.141734 | 367 | 200 |
| 0 | false | serial | 0.591600 | 0.520212 | 366 | 200 |
| 0 | true | parallel | 0.234153 | 0.171086 | 568 | 215 |
| 0 | true | serial | 0.727804 | 0.559860 | 561 | 215 |
| 10 | false | parallel | 0.168765 | 0.153695 | 379 | 209 |
| 10 | false | serial | 0.666740 | 0.471522 | 380 | 209 |
| 10 | true | parallel | 0.261279 | 0.194143 | 588 | 225 |
| 10 | true | serial | 0.800354 | 0.607371 | 581 | 225 |
| 1000 | false | parallel | 0.827292 | 0.718051 | 381 | 210 |
| 1000 | false | serial | 3.039900 | 2.547562 | 380 | 210 |
| 1000 | true | parallel | 1.382738 | 1.098427 | 589 | 227 |
| 1000 | true | serial | 4.294517 | 2.930703 | 583 | 227 |

All twelve cases improve in every pair, with non-overlapping timing ranges.
All allocation ranges also fall. With 1,000 threads and urgent counting enabled,
the serial median falls from 4.294517 to 2.930703 ms/op, about 32%. Parallel
amortized time falls from 1.382738 to 1.098427 ms/op, about 21%. These results
cover the measured local store workload, not whole-server throughput or
production capacity. They are not combined-stack measurements, and ratios
from separate PRs must not be multiplied together.

## Validation

The complete existing thread-store race suite and new edge-case tests pass.
The two selected unread API race suites also pass. The new tests pass with the
unchanged production file restored through a Go overlay, characterizing empty
and duplicate team IDs, multiple teams, null timestamps, null/negative mention
counts, deleted/unfollowed threads, other users, orphan memberships, lost
channel membership, DM exceptions and zero-valued read groups.

The twelve benchmark cases also pass execution/output checks under the race
detector, with serial and parallel calls. Those timings are not performance
evidence. [validation.json](validation.json) records exact counts, commands,
source revisions and check scopes.

All 39 patches apply cleanly. The public backend builds with the production tag
and passes the release script's enterprise tag/symbol exclusion criteria.
Full branded packaging, browser flows and production load tests were not run.

## Reproduce

Use Go 1.26.10 and the normal public server/public go.work. Set
TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL test service. After
just workspace, run from this repository's root:

```sh
GOMAXPROCS=4 python3 docs/benchmarks/team-thread-unread-aggregation/benchmark.py --workspace work/src --baseline HEAD^ --iterations 1000 --trials 3 --output /tmp/team-thread-unread-aggregation/results.json
```

Run the race commands in validation.json from work/src/server. Compare source
tree hashes when reconstructing the workspace, since git-am commit IDs can differ.
