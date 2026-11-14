# Slowmode lookup index

`GetLastCreateAtForUserInChannel` filters by channel, user, lower creation-time
bound and non-system type, then reads the maximum timestamp. The query includes
deleted posts. Migration 243 adds a matching partial B-tree index without
changing that query or its result.

The existing PostgreSQL plan can implement MAX through a backward scan of the
global creation-time index. When the expected matching row is absent, that scan
can visit unrelated channels/users throughout the time window. In this fixture,
quiet-user and system-only lookups filtered 1,333,512 unrelated rows per call.
The new index restricted the scan to channel/user/time and filtered zero rows.

## Reproduce

Prepare the Mattermax workspace, including this patch. Use a disposable
PostgreSQL container with an existing database and a role that can create a
schema. The script creates only a randomly named benchmark schema and removes
it in a finally block. It uses Docker, psql inside the container, and Python's
standard library. It does not install Python or Go dependencies.

Run from the Mattermax patch repository:

```sh
python3 -I docs/benchmarks/slowmode-lookup/benchmark.py \
  --workspace work/src/server \
  --container mattermax-upstream-tests \
  --user mmuser --database mattermost_test \
  --rows 1000000 --samples 20 --trials 3 \
  --output /tmp/slowmode-results.json
```

The fixture uses the Posts DDL and relevant existing indexes from migrations
20/80/102. It adds 1,000,000 recent posts by other users, 90,000 actor posts in
other channels, 333,333 recent system messages, and two target posts. This is a
sparse synthetic post table, rather than a complete production database. Source
hashes, settings, samples and plans are in [results.json](results.json).

Three paired trials alternate variant order. Each case validates its expected
answer and performs three warmups before twenty EXPLAIN ANALYZE measurements.
The recorded timings are PostgreSQL execution time, excluding planning,
Docker/client startup and HTTP. No application tests ran during this execution.

## Observed results

The table gives medians of the three trial mean execution times in milliseconds.

| Case | Existing indexes | Added index |
| --- | ---: | ---: |
| No recent post by the user in this channel | 337.322 | 0.059 |
| Latest post already matches | 0.038 | 0.059 |
| Only system posts match the user/channel | 324.130 | 0.058 |
| Latest eligible post is deleted | 35.803 | 0.059 |

The active-user case was already fast and became about 0.02 ms slower in this
run. This is a targeted fix for filtering unrelated rows, not a universal query
speedup or an end-to-end server throughput measurement.

After the read trials, three alternating-order pairs measured 5,000-row bulk
INSERT statements with EXPLAIN ANALYZE, BUFFERS and WAL. Median batch time was
144.394 ms before and 175.785 ms after; the trial ranges were 141.897 to 240.183 ms
and 153.928 to 216.401 ms. The ranges overlap. These sparse bulk inserts omit the
application's counter, queue and notification work and do not establish
per-request write cost. Every eligible post now maintains another index.

The final index occupied 94,912,512 bytes (about 90.5 MiB), after all 30,000
write-probe rows were added. The fixture started with 1,423,335 rows. Storage and
migration time on a 100M-post installation have not been validated here. Shared
host activity, cache state, synthetic correlations and fixture row width limit
these observations. Keep those limits when quoting the results.

The harness checks index readiness/validity, repeats the up/down/up operations
and verifies the deleted-post result afterward. The separate store regression
checks the exclusive timestamp cutoff, author/channel isolation, system-message
exclusion and retained deleted-post cooldowns. Existing post-store and posting-
rule API suites also run with the Go race detector.

## Migration operation

The up/down migrations use CONCURRENTLY and are marked nontransactional. They
add/drop only this index. Creation intentionally has no IF NOT EXISTS clause:
an interrupted concurrent build can leave an invalid index, which must not be
silently accepted on retry. Inspect that named index and remove an invalid one
with the down migration's statement before retrying. An existing index with the
same name also needs inspection before applying the migration.

Only public Team Edition code was used. Existing feature patches retain their
original authorship; this index complements Karan Sharma's slowmode patch.
