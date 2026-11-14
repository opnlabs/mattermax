# Attachment metadata across history pages

History preparation reads file metadata separately for each attachment-bearing
post. This patch gathers distinct file IDs and calls the existing cached
GetByIds method in batches of at most 1,000 IDs. The cache decodes each entry
once and fetches only misses. A fully cold page of 60 posts with two files each
uses one attachment query instead of 60. Priority and acknowledgement reads
remain separate.

Ordering, access-limit filtering and preview processing still run per post.
Prepared results already follow stored attachment order, so they avoid another
sort. Repeated IDs are deduplicated, and file values shared across posts are
copied before mutation, including preview bytes and remote-ID pointers. Bulk
errors fall back to per-post reads. Pending previews and metadata resets keep
their original second attempts. Single-post, master-read and deleted-file
paths retain their existing lookups.

The patch is stacked on PR #45 and includes its dependency, PR #43. Existing
feature patches and contributor credits remain unchanged.

## Measurement

The paired benchmark prepares real ordered pages with default priority and
acknowledgement reads. Each attachment-bearing post has two stored text files,
in reversed creation order; output checks validate file IDs, ownership and
attachment order. Cases cover one, ten and sixty posts, plus a sixty-post
no-file control. Cold cases purge only file caches outside the timer; warm
cases use populated caches. PostgreSQL buffers are not reset.

A Go overlay restores the parent post.go and post_metadata.go for the baseline.
The new helper and all tests compile in both variants, but the baseline app
path does not use that helper. Setup is outside the timer. Measurements exclude
HTTP, file bytes, image decoding/generation and remote links.

[results.json](results.json) records environment, source hashes, raw paired
samples and medians. These are local preparation timings, not measurements of
overall server throughput.

Three alternating paired trials with one second per case produced these
medians:

| Posts | Files/post | Cache | Before (ms) | After (ms) |
| --- | --- | --- | ---: | ---: |
| 1 | 2 | cold | 0.856 | 0.724 |
| 1 | 2 | warm | 0.278 | 0.278 |
| 10 | 2 | cold | 2.684 | 0.787 |
| 10 | 2 | warm | 0.398 | 0.390 |
| 60 | 2 | cold | 15.705 | 1.882 |
| 60 | 2 | warm | 1.111 | 1.131 |
| 60 | 0 | cold | 0.569 | 0.581 |
| 60 | 0 | warm | 0.535 | 0.573 |

No speedup is claimed for warm-cache, single-post or no-file controls.

## Reproduce

Use the public-only workspace and disposable PostgreSQL/Redis test services.
Set TEST_DATABASE_POSTGRESQL_DSN and the usual Go cache variables:

```sh
python3 docs/benchmarks/attachment-history/benchmark.py \
  --workspace work/src --baseline 1b0e20638d72 \
  --duration 1s --trials 3 \
  --output docs/benchmarks/attachment-history/results.json
```

[validation.json](validation.json) records selected race checks for batching,
missing/repeated IDs, mutable metadata, content limits, pending previews,
hidden/deleted posts, master/deleted-file flags and file-policy APIs. Full
branded release packaging and the complete repository suite were not run.
No API endpoint, schema change or third-party dependency is added.
