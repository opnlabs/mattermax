# Read-receipt preference inputs

Read-receipt input loading fetches the channel and current members, then loads
one privacy preference per member. Replace that preference loop with one
category/name query restricted to the current member IDs. An array-bound ANY
predicate keeps the parameter count fixed and uses the existing preference
primary key. No schema, index, cache or third-party dependency is added.

The app initializes every member's missing-row default, then parses returned
values with the existing parser and timestamp. Off, malformed and future values
remain off; stored enable timestamps remain intact. The query returns only
stored preferences for the requested users/category/name. Empty input performs
no SQL, missing rows are omitted and duplicate user IDs do not duplicate rows.
The error path returns no partially defaulted inputs and preserves the existing
500 error identifier. Disabled receipts and public/private channels keep their
existing early returns. Visibility checks, payloads and publishing stay intact.

Each preference set now comes from one statement snapshot on the same replica
path as the former individual reads. This adds no synchronization with
concurrent consent changes or queued event delivery.

## Reproduce

Prepare work/src with this patch. Set TEST_DATABASE_POSTGRESQL_DSN to a
disposable PostgreSQL test database as required by the upstream Go tests. The
test helper initializes databases; do not use a production database. From the
Mattermax patch repository:

```sh
python3 -I docs/benchmarks/read-receipt-inputs/benchmark.py \
  --workspace work/src --iterations 500 --trials 3 \
  --output /tmp/read-receipt-inputs-results.json
```

The same SQL-store benchmark compares individual Get calls with the batch
method, including privacy-map construction and parsing on both paths. A full
map equality preflight precedes each timed loop; each timed call checks errors
and member cardinality. All calls use the complete migrated schema. No app
suite or race suite ran during measurement; timing excludes race instrumentation.

Synthetic sets contain two, four or eight member IDs. In input order, values
cycle through off, absent (default on since zero), and stored on since zero.
The benchmark seeds no channel memberships because it measures only the
preference portion of input loading. Seeding and cleanup are outside timing.
Three paired trials alternate individual/batch process order, with 500
sequential input loads per member count. [results.json](results.json) records
raw benchmark lines, source hashes and host/runtime details.

## Observed results

Values are median benchmark samples. Parentheses give the full trial range in
milliseconds per preference input load, including PostgreSQL and driver work.

| Members | Individual reads, ms | Batched read, ms |
| --- | ---: | ---: |
| 2 | 0.410 (0.404 to 0.441) | 0.219 (0.212 to 0.220) |
| 4 | 0.686 (0.571 to 0.699) | 0.215 (0.138 to 0.220) |
| 8 | 1.063 (0.897 to 1.131) | 0.214 (0.153 to 0.239) |

Median Go allocations per input load:

| Members | Individual bytes | Batched bytes | Individual allocations | Batched allocations |
| --- | ---: | ---: | ---: | ---: |
| 2 | 14929 | 6702 | 262 | 123 |
| 4 | 29154 | 7786 | 522 | 145 |
| 8 | 58281 | 9793 | 1043 | 168 |

This replaces two, four or eight preference statements with one for these
fixtures. The measurements are warm, sequential microbenchmarks on a shared
host with a mix of stored and absent preferences. They exclude channel/member
reads, HTTP, authorization, preference mutations and WebSocket delivery, and do
not establish full endpoint latency, production throughput, request percentiles
or sustained-concurrency capacity. PostgreSQL memory and CPU are excluded.
Fixture distribution, cache state and host activity limit extrapolation.

## Validation

The store tests check user/category/name isolation, absent rows, duplicate IDs
and empty input. App mocks require exactly one bulk call, check privacy defaults
and enable timestamps, and verify database errors return no partial inputs.
Existing API tests cover opt-out visibility, re-enable floors, public/private
channels, nonmembers, group messages and WebSocket publishing. Store and app/API
suites ran with the race detector; see [validation.json](validation.json).

This complements Karan Sharma's (@mr-karan) read-receipts feature in #20.
Existing feature patches retain their original content and authorship. Only
public Team Edition code was used. The full branded packaging build was not run.
