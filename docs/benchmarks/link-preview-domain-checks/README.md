# Parse a preview hostname once per domain check

Preview filtering parses the same URL and converts its hostname to ASCII for
every restricted-domain entry until a match is found. Moving those operations
before the loop avoids repeated work when there are several entries. An empty
restriction list still returns immediately, including for malformed URLs.
Substring matching and domain-list normalization stay unchanged.

This contribution is independent of the other performance PRs. It starts from
the original 38-patch Mattermax baseline. All inherited patches remain
byte-identical, preserving their features and authorship. No public API,
schema, configuration or dependency changes.

## Measurements

Three alternating-order pairs of processes per variant use Go 1.26.10,
GOMAXPROCS=4 and disposable local PostgreSQL/Redis services. A Go overlay restores
only post_metadata.go for baseline. Both variants use identical fixtures,
validation and fixed iteration counts. [results.json](results.json) records
every sample, median, range, source hash and command.

The filtering benchmark uses 100,000 iterations per case. Empty and single-domain
lists are controls; a 20-domain list exercises repeated parsing. Cases include
an allowed ASCII host, first/last matches and an allowed Unicode host. Every
iteration validates the allow/deny decision.

The App benchmark uses 1,000 iterations per case and prepares stored, ordered
pages with priority reads explicitly enabled. Each post has the same allowed
HTTPS link. Every iteration checks page order, message and metadata. Preview
fetching is disabled, so no external HTTP requests occur; filtering still runs.
Fixture creation is outside the timer. This measures App preparation with real
metadata reads, not complete HTTP endpoint latency.

| Case | Before µs/op | After µs/op | Before B/op | After B/op | Before allocs/op | After allocs/op |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Checks/domains=0/allowed | 0.031 | 0.037 | 0 | 0 | 0 | 0 |
| Checks/domains=0/first | 0.031 | 0.028 | 0 | 0 | 0 | 0 |
| Checks/domains=0/last | 0.029 | 0.037 | 0 | 0 | 0 | 0 |
| Checks/domains=0/unicode | 0.039 | 0.029 | 0 | 0 | 0 | 0 |
| Checks/domains=1/allowed | 0.369 | 0.354 | 160 | 160 | 2 | 2 |
| Checks/domains=1/first | 0.401 | 0.390 | 160 | 160 | 2 | 2 |
| Checks/domains=1/last | 0.401 | 0.379 | 160 | 160 | 2 | 2 |
| Checks/domains=1/unicode | 0.662 | 0.673 | 248 | 248 | 6 | 6 |
| Checks/domains=20/allowed | 6.496 | 1.378 | 3584 | 848 | 22 | 3 |
| Checks/domains=20/first | 1.404 | 1.411 | 848 | 848 | 3 | 3 |
| Checks/domains=20/last | 7.022 | 1.410 | 3584 | 848 | 22 | 3 |
| Checks/domains=20/unicode | 11.654 | 1.772 | 5344 | 936 | 102 | 7 |
| History/domains=0/posts=1 | 513.193 | 520.524 | 92068 | 92084 | 1166 | 1166 |
| History/domains=0/posts=60 | 3855.677 | 3877.077 | 4677350 | 4677020 | 55412 | 55412 |
| History/domains=20/posts=1 | 430.568 | 528.549 | 95649 | 92914 | 1188 | 1169 |
| History/domains=20/posts=60 | 4277.466 | 4022.265 | 4892370 | 4728112 | 56732 | 55592 |

With 20 entries, the allowed ASCII check falls from 6.496 to 1.378 µs/op
and from 22 to 3 allocations. The last-match and Unicode cases also improve;
the first-match control performs one parse in both versions and its ranges
overlap. Empty/single-domain controls retain their allocation counts.

For a 60-post page with 20 restrictions, median preparation time falls from
4.277466 to 4.022265 ms, about 6%. Every pair improves and ranges do not overlap
(before: 4.182900–4.386917 ms; after: 3.940321–4.084696 ms). Allocations fall
from 56,732 to 55,592 and median allocated bytes from 4,892,370 to 4,728,112.

The empty-list 60-post control has a 0.6% slower median with overlapping ranges
and unchanged allocation counts. Single-post timings are noisy: the 20-domain
single-post median is 22.8% slower, with broad overlapping ranges and mixed
paired outcomes. No universal single-post or empty-list latency improvement
is claimed. All raw controls remain in the report.

These measurements cover this standalone source, not combined-stack throughput
or production capacity. Ratios from separate PRs must not be multiplied together.

## Validation

The new edge-case tests also pass with the unchanged production implementation
restored through a Go overlay. They characterize empty/separator-only lists,
malformed URLs, invalid IDNA, Unicode/punycode, case conversion, userinfo, ports,
IPv6, relative/opaque URLs, substring matches and duplicate entries.

Current selected app race suites cover those checks, existing Markdown link/image
filtering, post preparation and image parsing. The sixteen benchmark cases also
pass execution/output checks under the race detector. The baseline compatibility
run covers the new cases and existing Markdown filtering. [validation.json](validation.json)
records counts, commands, exact sources and scopes.

All 39 patches apply cleanly. The public backend builds with only the production
tag and passes the release script's enterprise tag/symbol exclusion criteria.
Full branded packaging, browser checks and production load tests were not run
for this contribution.

## Reproduce

Use Go 1.26.10 and the normal public server/public go.work. Set
TEST_DATABASE_POSTGRESQL_DSN and TEST_REDIS_ADDR to disposable local test services.
After just workspace, run from this repository's root:

```sh
GOMAXPROCS=4 python3 docs/benchmarks/link-preview-domain-checks/benchmark.py --workspace work/src --baseline HEAD^ --trials 3 --check-iterations 100000 --history-iterations 1000 --output /tmp/link-preview-domain-checks/results.json
```

Run the race commands in validation.json from work/src/server. Compare the source
tree hash when reconstructing the workspace, since git-am commit IDs can differ.
