# Preference batch upserts

`SqlPreferenceStore.Save` normalizes and validates copied unique-key records,
sorts them by user/category/name, and writes multi-row upserts in one transaction.
The existing parameter-limit helper splits large batches into chunks. Sorting
before chunking gives concurrent batches the same row-lock order. One failed
chunk rolls back all writes. No schema migration or dependency is added.

Single records and batches containing duplicate keys retain the existing
sequential path. This preserves last-value-wins behavior and errors from earlier
overwritten records, including database rejection of NUL text. These batches
also retain their existing statement count and lock order. The change does not
eliminate deadlocks with every other preference-writing path.

The caller's slice is unchanged, so normalization and sorting do not change
submitted preference values or order in application events. The API tests cover
existing validation, event and sidebar behavior. Normalization and validation
for unique-key batches finish before opening the transaction; invalid inputs
are not benchmarked.

## Reproduce

Prepare `work/src` with this patch as its last workspace commit. Set
`TEST_DATABASE_POSTGRESQL_DSN` to a disposable PostgreSQL database as required by
the upstream Go tests. They initialize test databases. Do not point this at a
production database. Start Redis on the test defaults if running the API suite.
Run from the Mattermax patch repository, with Go and the existing module cache:

```sh
python3 -I docs/benchmarks/preference-batches/benchmark.py \
  --workspace work/src --baseline HEAD^ --iterations 500 --trials 3 \
  --output /tmp/preference-results.json
```

The harness restores only the baseline preference-store source through a Go
overlay. Both variants use the same benchmark test, package, Go runtime and
PostgreSQL test setup. It checks complete output for all three sizes and a
passing terminal result. [results.json](results.json) records source hashes,
resolved workspace revisions, hardware/runtime and every benchmark line.

Each sample updates existing keys with 32-byte values, including transaction
commit. Each variant initializes the SQL test store in its own process. Three
paired trials alternate variant order and run 500 sequential updates per size.
Seeding and cleanup are outside the measured loop. No application suite or
reference server ran during the benchmark. The race detector is off for timing;
separate correctness suites use it.

## Observed results

Values below are medians across three benchmark samples. Parentheses give the
full trial range in milliseconds per committed Save call.

| Records | Existing store, ms | Batched store, ms |
| --- | ---: | ---: |
| 1 | 6.707 (5.087 to 7.476) | 7.330 (6.628 to 8.609) |
| 10 | 8.914 (6.642 to 9.960) | 9.389 (7.467 to 10.053) |
| 100 | 19.286 (17.052 to 20.467) | 10.275 (10.214 to 10.456) |

The 100-record batch used one upsert instead of 100. Its median elapsed time
fell by about 47% in this run. The smaller-batch medians increased and their
ranges overlapped; these timings establish no small-batch speedup. The
single-record SQL path is unchanged. Shared-host activity and database commit
latency vary throughout the run.

The Go benchmark's median allocation measurements per call were:

| Records | Existing bytes | Batched bytes | Existing allocations | Batched allocations |
| --- | ---: | ---: | ---: | ---: |
| 1 | 7004 | 6998 | 130 | 130 |
| 10 | 63794 | 24759 | 1165 | 373 |
| 100 | 632706 | 224669 | 11515 | 2872 |

These measurements include Go SQL-store and database-driver work, rather than
HTTP, authorization, receipt stamping, sidebar updates, plugin hooks or event
delivery. PostgreSQL memory is excluded. They do not establish production
throughput, request percentiles, insert performance, duplicate-batch performance
or sustained-concurrency capacity. Sparse fixtures, host activity and local
Docker/PostgreSQL behavior limit extrapolation.

## Correctness checks

The store suite covers normalization without mutating event input, mixed users
and categories, empty names, duplicate model/database errors, successful
chunking, rollback after a later chunk fails, and ten pairs of opposite-order
concurrent updates with two records per chunk. Each successful pair leaves one
whole batch's values. The same concurrency test fails with PostgreSQL deadlock
40P01 when the original source is restored through an overlay.

The focused store race run passed 40 checks and the preference API race run
passed 31 checks, with no skips. [validation.json](validation.json) records the
commands and outcomes. Existing patch files retain their original authorship;
this patch changes only the public preference store and its tests.
