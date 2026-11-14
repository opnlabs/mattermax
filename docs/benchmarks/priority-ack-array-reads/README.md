# Fixed priority and acknowledgement reads

History preparation reads priority and acknowledgement metadata for its post
IDs. These queries currently build an IN placeholder and argument for every
ID. Fixed SQL with an existing lib/pq array parameter removes that construction
work. The query text stays constant as the batch size changes; no prepared-plan
reuse is assumed or required.

The two methods keep their 200-ID boundaries, replica selection and SQL wrapper.
The wrapper still applies timeouts, tracing, rebinding and error handling.
Duplicates within a batch and across batches retain their existing behavior.
AcknowledgedAt <> 0 still excludes NULL/zero rows and includes negative legacy
values. Nullable priority flags and remote fields retain their values.

This patch is independent of the other performance PRs and starts from the
original 38-patch baseline. All inherited patches remain byte-identical,
preserving their features and authorship. There are no interface, public API,
schema, configuration or dependency changes.

## Measurements

Three alternating-order paired processes per variant, with 1,000 timed
iterations per case. Fixed iteration counts keep leaf benchmark calibration
and fixture creation counts equal. A Go overlay restores only the two store
production files for baseline. Other production code, fixtures and validation
are identical. Go 1.26.10, GOMAXPROCS=4 and a disposable local PostgreSQL 17
service are used. [results.json](results.json) contains every raw sample,
range, allocation count and source hash.

The store benchmark executes both real database reads. Empty has no matching
metadata, sparse has metadata for one in 20 IDs, and dense has it for every ID.
The 201-ID case crosses the existing boundary and performs two batches per
method. Timed loops validate returned IDs, fields and result counts.

| Case | Before µs/op | After µs/op | Before allocs/op | After allocs/op |
| --- | ---: | ---: | ---: | ---: |
| empty/ids=1 | 348.543 | 338.549 | 249 | 109 |
| empty/ids=60 | 348.508 | 283.308 | 625 | 119 |
| empty/ids=200 | 617.780 | 345.254 | 1485 | 124 |
| empty/ids=201 | 899.898 | 632.838 | 1733 | 233 |
| sparse/ids=1 | 268.586 | 248.930 | 280 | 139 |
| sparse/ids=60 | 399.149 | 224.385 | 714 | 208 |
| sparse/ids=200 | 657.198 | 371.911 | 1767 | 407 |
| sparse/ids=201 | 958.372 | 707.076 | 2047 | 547 |
| dense/ids=1 | 265.174 | 214.583 | 280 | 139 |
| dense/ids=60 | 551.205 | 449.538 | 2261 | 1755 |
| dense/ids=200 | 1303.684 | 1116.699 | 6906 | 5545 |
| dense/ids=201 | 1961.854 | 1241.801 | 7183 | 5684 |

The App benchmark prepares complete stored, ordered pages with priority reads
explicitly enabled. It validates order and positive priority/acknowledgement
metadata, including post/channel/user IDs and requested-ack state. There are
no files, reactions or remote links. Post creation is outside the timer;
history preparation, database reads and output checks are inside it.

| Case | Before µs/op | After µs/op | Before allocs/op | After allocs/op |
| --- | ---: | ---: | ---: | ---: |
| empty/posts=1 | 263.324 | 229.731 | 282 | 142 |
| empty/posts=60 | 821.625 | 648.748 | 2372 | 1865 |
| sparse/posts=1 | 327.870 | 311.442 | 314 | 174 |
| sparse/posts=60 | 654.258 | 542.882 | 2457 | 1951 |
| dense/posts=1 | 263.665 | 286.235 | 314 | 174 |
| dense/posts=60 | 988.455 | 872.045 | 3908 | 3402 |

For 60-post pages, median preparation time falls about 21% with empty metadata,
17% with sparse metadata and 12% with dense metadata. Empty/dense 60-post
ranges do not overlap and every pair improves. Sparse ranges overlap and its
first pair is about 2% slower, so its median is a less consistent result.
All cases allocate less. Single-post timings vary; the dense single-post App
control has an 8.6% slower median with overlapping ranges. No universal
single-post or concurrent-throughput speedup is claimed.

These results measure this contribution over its recorded standalone source.
They are not combined-stack throughput measurements, and ratios from separate
PRs must not be multiplied together.

## Validation

The selected SQL store, app and API race suites passed 155 parent/subtest events
with no failures or skips. The feature suite covers acknowledgement-list
hydration, priority creation and acknowledgement APIs. The same new regression
test also passes with both legacy production files restored through a Go
overlay, checking compatibility against the earlier implementation.

Cases cover nil/empty/missing/escaped IDs; 199/200/201/400/401 boundaries;
duplicates within/across chunks; nullable true/false flags; NULL/zero/negative
acknowledgement timestamps; remote fields; and a second-batch failure that must
discard earlier successful rows.

A PostgreSQL fixture probe compares both query forms on 20,000-row tables
matching public migrations 97, 98 and 141. At 1, 60 and 200 IDs, results match
and both forms use index scans. The transaction is rolled back and catalog
checks confirm the temporary tables are removed. This is a fixture plan check,
not a claim about every production planner/statistics configuration.

The public backend builds with only the production tag and passes the release
script's enterprise tag/symbol exclusion criteria. All 39 patches apply cleanly.
[validation.json](validation.json) records commands, exact revisions, scopes
and private-log hashes. Full branded packaging/browser checks and production
load testing are outside this validation.

## Reproduce

Set TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL test service. Use
Go 1.26.10 and the normal public server/public go.work. After just workspace,
run from the repository root:

```sh
GOMAXPROCS=4 python3 docs/benchmarks/priority-ack-array-reads/benchmark.py --workspace work/src --baseline HEAD^ --iterations 1000 --trials 3 --output /tmp/priority-ack-array-reads.json
```

Run the race commands in validation.json from work/src/server. Compare the
source tree hash when reconstructing the workspace, since git-am commit IDs
can differ.
