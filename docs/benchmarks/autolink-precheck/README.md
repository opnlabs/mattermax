# Autolink precheck

Ordinary messages still build a Markdown tree while the server searches for a
preview link. The existing parser needs a literal colon or lowercase www
prefix to construct an autolink. Return the existing empty result when neither
marker is present. Potential links keep their existing parser and domain
policy. An explicit size check retains constant-time rejection above the
Markdown input limit.

This is an independent patch over the original 38-patch Mattermax baseline.
It does not require the other performance PRs. All inherited patch files are
byte-identical, preserving their features and original authorship. Runtime
code changes are seven lines in getFirstLink; the shared parser is unchanged.

## Measurements

Three alternating-order paired processes per variant, with one-second
benchmark durations, Go 1.26.10 and GOMAXPROCS=4. A Go overlay restores only
post_metadata.go for the baseline; production code elsewhere and benchmark
fixtures are identical. [results.json](results.json) retains every sample,
range, allocation count, source hash and machine detail.

History preparation uses real stored pages with populated and validated order,
including default priority and acknowledgement database reads. The short case
uses one sentence. Prose repeats a sentence across 50 lines; formatting uses
50 Markdown list items with emphasis and code spans. There are no files or
reactions. Link previews are disabled, and the HTTP/www controls do not fetch
remote content. Timed loops include output validation.

| Case | Before µs/op | After µs/op | Before allocs/op | After allocs/op |
| --- | ---: | ---: | ---: | ---: |
| plain/posts=1 | 264.688 | 244.057 | 298 | 278 |
| plain/posts=60 | 653.273 | 502.845 | 3331 | 2131 |
| prose/posts=1 | 442.042 | 332.604 | 1302 | 780 |
| prose/posts=60 | 7933.775 | 4478.724 | 63573 | 32252 |
| formatting/posts=1 | 474.686 | 380.630 | 2906 | 1582 |
| formatting/posts=60 | 10225.573 | 6044.526 | 159812 | 80372 |
| colon_control/posts=1 | 258.416 | 282.629 | 298 | 298 |
| colon_control/posts=60 | 643.062 | 678.430 | 3331 | 3331 |
| http_control/posts=1 | 353.203 | 346.212 | 1170 | 1170 |
| http_control/posts=60 | 4014.452 | 4032.435 | 55652 | 55652 |
| www_control/posts=1 | 320.986 | 346.325 | 1169 | 1169 |
| www_control/posts=60 | 3980.474 | 3894.685 | 55592 | 55592 |

All three eligible 60-post cases improve in every pair, with non-overlapping
before/after timing ranges. Their median reductions are about 23% for short
prose, 44% for longer prose and 41% for formatting. Smaller pages and
marker-positive controls vary. For example, the 60-post colon control has a
roughly 5.5% slower median with overlapping ranges. No improvement is claimed
for those controls or for concurrent server throughput.

The direct getFirstLink benchmark validates returned links against the
unguarded implementation. It shows the removed Markdown allocations for
eligible messages. Link-positive calls retain the parser, with a small
precheck cost: HTTP/www microbenchmark medians are about 2% slower, with
unchanged allocation counts.

| Case | Before µs/op | After µs/op | Before allocs/op | After allocs/op |
| --- | ---: | ---: | ---: | ---: |
| plain | 0.774 | 0.010 | 20 | 0 |
| prose | 42.742 | 0.340 | 522 | 0 |
| formatting | 61.176 | 0.356 | 1324 | 0 |
| colon_control | 0.796 | 0.800 | 20 | 20 |
| http_control | 1.322 | 1.352 | 22 | 22 |
| www_control | 1.339 | 1.368 | 22 | 22 |

These are standalone measurements over the common baseline. Other submitted
performance patches change history preparation too; these ratios must not be
multiplied together or presented as combined-stack throughput.

## Validation

Selected app/API race checks passed 200 parent/subtest events with no failures
or skips. They cover link syntax, domain restrictions, first-link selection,
size boundaries, post preparation, images/proxy behavior, burn-on-read metadata
and history APIs. The differential fuzz run compared 15,047 inputs up to 4 KiB,
checking both returned links and panic outcomes against the unguarded parser.

Initial fuzzing exposed an existing malformed UTF-8 panic in the shared
parser. A captured input panics identically before and after this change. The
compatibility oracle compares those outcomes explicitly; parser robustness is
outside the result of that comparison. The shared parser has no code changes.

A separate corpus probe found no missed autolinks across 1,365 unique Go string
literals in 11 parser test files, including 258 strings with autolinks. This
covers the literal corpus, not every dynamically generated parser test input.
[corpus.json](corpus.json) records the probe scope.

The public backend builds with the production tag and passes the enterprise
tag/symbol exclusion checks. All 39 patches apply cleanly. No new dependency,
public API, schema or configuration change is introduced.
[validation.json](validation.json) records exact revisions, commands and scopes.
Full branded release packaging and browser flows were not run for this patch.

## Reproduce

Set TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL test database.
Use the normal public server/public go.work with Go 1.26.10. After running
just workspace, run from the repository root:

```sh
GOMAXPROCS=4 python3 docs/benchmarks/autolink-precheck/benchmark.py --workspace work/src --baseline HEAD^ --duration 1s --trials 3 --output /tmp/autolink-precheck.json
```

Run the race and fuzz commands in validation.json from work/src/server.
The source tree hash lets reconstructed workspaces be compared even when
git-am commit IDs differ.
