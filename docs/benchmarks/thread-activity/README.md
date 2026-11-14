# Thread auto-archive activity lookup

Auto-archive needs the later of root creation and the thread's last reply time.
The legacy path hydrates a full post through GetSingle (including a live reply
count) and then reads thread metadata, including participants. The scalar path
reads GREATEST(Posts.CreateAt, COALESCE(Threads.LastReplyAt, 0)) in one LEFT JOIN
using the existing post and thread primary keys. It adds no schema, index,
cache or third-party dependency.

Missing thread metadata falls back to root creation time. Missing/deleted roots
retain ErrNotFound, which the app allows through for normal post validation.
Other database errors keep the existing 500 error identifier. The activity
comparison, exemptions, policy ordering and user-facing archive message remain
unchanged. The scalar read uses the same request-selected database as the old
root read, and gets both timestamps from one statement snapshot. It does not
introduce synchronization with concurrent replies or rule changes.

## Reproduce

Prepare work/src with this patch. Set TEST_DATABASE_POSTGRESQL_DSN to a
disposable PostgreSQL test database as required by the upstream Go tests. The
test helper initializes databases; do not use a production database. From the
Mattermax patch repository:

```sh
python3 -I docs/benchmarks/thread-activity/benchmark.py \
  --workspace work/src --iterations 500 --trials 3 \
  --output /tmp/thread-activity-results.json
```

Each variant uses the same real SQL-store benchmark and complete migrated
schema. The legacy benchmark invokes the unchanged GetSingle and Thread.Get
methods and computes the same maximum as the original app. Both variants
validate the expected timestamp before and throughout timing. No app test or
race suite ran during measurement; timing excludes race instrumentation.

Each process seeds a channel and synthetic thread with zero, 1,000 or 10,000
replies. Root messages are 1,300 bytes and thread metadata has one participant.
Reply timestamps are synthetic future offsets from root creation. The fixture
measures activity retrieval, rather than the policy decision for those dates.
Preparation and cleanup are outside timing. Three paired trials alternate
legacy/scalar process order, with 500 sequential reads per case. Raw benchmark
lines, source hashes and host/runtime details are in [results.json](results.json).

## Observed results

Values are median benchmark samples. Parentheses give the full trial range in
milliseconds per activity lookup, including PostgreSQL and Go driver work.

| Replies | Legacy, ms | Scalar, ms |
| --- | ---: | ---: |
| 0 | 0.622 (0.535 to 0.667) | 0.308 (0.291 to 0.315) |
| 1000 | 0.726 (0.632 to 0.934) | 0.419 (0.409 to 0.425) |
| 10000 | 1.101 (1.093 to 1.117) | 0.268 (0.240 to 0.311) |

Median Go allocations per lookup:

| Replies | Legacy bytes | Scalar bytes | Legacy allocations | Scalar allocations |
| --- | ---: | ---: | ---: | ---: |
| 0 | 25534 | 6949 | 293 | 118 |
| 1000 | 25873 | 6944 | 305 | 118 |
| 10000 | 25865 | 6951 | 305 | 118 |

The scalar path avoids a database round trip, post decoding, participant
decoding and a reply-count scan. These are synthetic, warm, sequential
store microbenchmarks on a shared host. PostgreSQL memory/CPU, HTTP, permission
checks, post insertion, notifications and event delivery are outside these
measurements. They establish no end-to-end server throughput or request
percentile improvement, production capacity, large-participant scaling or
sustained-concurrency capacity. Host activity, cache state and fixture width
limit extrapolation.

## Validation

The store regression covers absent metadata, newer replies, metadata older than
the root, reply deletion, and missing/deleted roots. It compares activity after
deletion with the original two-read result. App tests cover missing-root
handling, fail-closed database errors and recent/idle outcomes. Existing
post/thread suites and posting-rule API tests ran with the race detector,
including administrator reopening, DM exemptions and slowmode interactions.
See [validation.json](validation.json) for commands and outcomes.

This complements Karan Sharma's (@mr-karan) thread auto-archive work in #22.
Existing feature patches retain their original content and authorship. Only
public Team Edition code was used. The full branded packaging build was not run.
