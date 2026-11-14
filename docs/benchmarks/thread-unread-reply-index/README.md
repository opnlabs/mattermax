# Unread-reply timestamp index

Unread replies filter Posts by RootId, DeleteAt and CreateAt. The post root index
contains the first two keys. Appending CreateAt lets PostgreSQL constrain the
timestamp range in the index. The three unread queries use COUNT(*), equivalent
to COUNT(Posts.Id) because Id is a non-null primary key. This permits index-only
scans when PostgreSQL's visibility map allows them. All predicates, timestamp
boundaries and empty-root behavior
stay unchanged. No extra application query branch is required.

Migration 000244 creates (RootId, DeleteAt, CreateAt) concurrently. Migration
000245 drops the original (RootId, DeleteAt) index concurrently. Each statement
has its own nontransactional migration. Downgrade restores the original before
removing the replacement. The steady-state index count stays unchanged; the
replacement is larger and both indexes coexist during upgrade.

This independent contribution starts from the original 38-patch Mattermax
baseline. It adds no HTTP API, configuration or third-party dependency. All
inherited patches remain byte-identical, including Karan Sharma's (@mr-karan) work.

## Real-store measurements

Go 1.26.10, GOMAXPROCS=4, one serial caller and local PostgreSQL. Three process
pairs alternate before/after order, with 500 fixed operations per case. Each
process gets a fresh database from the standard SQL-store test harness. Before
restores the original production file and replaces the candidate index with the
original definition before seeding. Setup, index changes and cleanup are untimed.

The fixture has 30 real root posts, followed memberships and 0, 100 or 1,000
interleaved replies per root. Every seventh reply is deleted. Mostly-read means
the read timestamp is 90% through the history; all-read means at the last reply.
Rows are seeded and analyzed without an explicit VACUUM. Counts, root IDs, root
messages, page size and duplicate IDs are checked throughout timing. Direct
counts, single-thread responses, 30-thread pages, unchanged totals and existing
single-post reply-count lookups are measured.

Values are median samples and full trial ranges in milliseconds per 30-thread
page. [store-results.json](store-results.json) retains all samples and commands.

| Replies per root | Read state | Before ms/page | After ms/page | Median change |
| ---: | --- | ---: | ---: | ---: |
| 0 | mostly_read | 1.390 (1.097 to 1.443) | 1.309 (1.122 to 1.407) | -5.9% |
| 0 | all_read | 1.003 (1.001 to 1.044) | 1.045 (1.026 to 1.052) | +4.2% |
| 100 | mostly_read | 1.204 (1.167 to 1.232) | 1.057 (1.039 to 1.075) | -12.2% |
| 100 | all_read | 1.082 (1.044 to 1.087) | 1.036 (0.997 to 1.077) | -4.3% |
| 1000 | mostly_read | 4.943 (4.632 to 4.975) | 1.799 (1.685 to 1.802) | -63.6% |
| 1000 | all_read | 2.783 (2.639 to 2.824) | 1.071 (1.066 to 1.074) | -61.5% |

Long-thread page ranges do not overlap and improve in every pair. Small cases
and controls vary. These are store calls with result validation, not HTTP
requests or whole-server throughput. Ratios from other PRs must not be multiplied
with these results.

A follow-up isolates each control in its own process: five alternating pairs,
5,000 operations per process, the same source and fixtures. Earlier benchmark
modes do not run in those processes.

| Isolated case | Before ms/op | After ms/op | Median change |
| --- | ---: | ---: | ---: |
| empty_page | 1.065 (1.031 to 1.437) | 1.062 (1.036 to 1.315) | -0.3% |
| reply_count_control | 0.607 (0.583 to 0.766) | 0.628 (0.598 to 0.765) | +3.5% |

The isolated empty-page result has no consistent direction across pairs. The
existing reply-count lookup is slower in four of five pairs, with overlapping
ranges. That cost is retained, not treated as a speedup. See
[isolated-empty_page.json](isolated-empty_page.json) and
[isolated-reply_count_control.json](isolated-reply_count_control.json).

## SQL, writes and storage

The SQL probe uses the full migrated Posts schema and its baseline indexes,
100,000 rows with empty RootId and 100,000 interleaved rows across 100 nonempty
RootId values, with roughly 1 KB messages. It compares COUNT(Id) and COUNT(*)
with both index definitions, deletion-inclusive/live filters and three read
timestamps. Vacuumed and deterministically updated states are separate. All
logical counts match across variants. Every read group has three warmups and
15 EXPLAIN ANALYZE samples; three alternating trials retain plans and buffers.

The schema initializer was the previously validated public PR #54 backend. Its
Posts columns and indexes match the shared baseline. The portable runner also
accepts the current public backend and normalizes the target index before
seeding. [sql-results.json](sql-results.json) records binary and runner hashes,
index definitions, PostgreSQL settings, plans, raw samples and cleanup.

Each write sample gets a fresh table with identical rows and bulk-built baseline
indexes. The measured operation runs after setup. Inserts add 5,000 rows; edits
change messages on 1,000 reply rows; soft deletes update the same reply set.

| SQL operation | Before batch ms | After batch ms | Median change |
| --- | ---: | ---: | ---: |
| insert_roots | 495.116 (451.769 to 563.461) | 464.977 (461.327 to 499.158) | -6.1% |
| insert_replies | 474.600 (452.180 to 560.890) | 485.472 (481.591 to 667.958) | +2.3% |
| edit | 34.983 (34.435 to 45.744) | 46.346 (38.688 to 46.361) | +32.5% |
| delete | 116.131 (106.994 to 117.977) | 126.766 (117.539 to 136.685) | +9.2% |

Write ranges overlap, but the higher reply-insert, edit and soft-delete medians
are material tradeoffs. WAL also increases. These bulk SQL measurements do not
measure the complete posting/editing API. Existing total-reply-count SQL controls
also vary across visibility states; all are retained in the raw report.
The net index growth is 8,691,712 bytes (8.29 MiB), 2.17% of the
fixture's baseline total relation size. Storage and write costs depend on data
distribution. No unchanged-write-cost or production-capacity claim is made.

## Validation

Selected race suites pass with 302 parent/subtest pass events and no failures or
skips. They include the complete ThreadStore and PostStore suites, compatibility
for all three unread callers, null/deleted/boundary rows, empty roots, staged
concurrent migration downgrade/upgrade, thread follow/read/removal/reinvite and
history API checks. All 39 patches apply cleanly. The public production backend
builds, passes the release script's enterprise tag/symbol exclusion criteria and
starts/migrates a fresh database with the settings overlay. Ping and anonymous
client config return HTTP 200 and the expected build number.

Both public runners pass execution/output checks, including the current backend
schema initialization and complete cleanup. Full branded packaging, browser flows
and production load tests were not run. [validation.json](validation.json) records
commands, counts, source hashes and scopes.

## Reproduce

Use Go 1.26.10, disposable PostgreSQL/Redis test services and the standalone PR
branch. Set TEST_DATABASE_POSTGRESQL_DSN to its PostgreSQL URL and TEST_REDIS_ADDR.
After just workspace and just check, keep only server and public in go.work.
From the patch repository root:

```sh
python3 docs/benchmarks/thread-unread-reply-index/benchmark.py --workspace work/src/server --baseline HEAD^ --iterations 500 --trials 3 --output /tmp/unread-store/results.json
```

Use --bench and --expected-cases 1 to isolate a case; exact filters are retained
in the isolated reports. Each isolated run used --iterations 5000 --trials 5.

Build the public production backend with a non-dev build number, source hash and
BuildEnterpriseReady=false, applying the unchanged release script's tag/symbol
exclusion checks. Then run:

```sh
python3 docs/benchmarks/thread-unread-reply-index/sql_benchmark.py --workspace work/src/server --binary /path/to/public/server --container disposable-postgres --output /tmp/unread-sql/results.json
```

The SQL runner creates and removes its own database. It uses the URL's host, port
and credentials for the temporary backend and the Docker container's local socket
for psql. Git-am commit IDs can differ; compare tree and file hashes when reconstructing a workspace.
