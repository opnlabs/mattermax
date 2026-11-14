# Reaction history preparation

History pages prepare reaction metadata once per reaction-bearing post. On a
cold cache this makes a SQL round trip for each post. The reaction batch path
reads each cached entry once, then fetches only misses using array-bound SQL
queries with at most 1,000 distinct post IDs per query. Existing priority and
acknowledgement reads remain separate.

This change is stacked on PR #43, which introduces the shared preparation
helpers. It preserves creation-time reaction ordering, deleted-row filtering,
legacy NULL timestamp handling, remote/channel fields, and nil/empty results.
Save, Delete and emoji deletion retain their existing cache invalidation.
Bulk read failures fall back to the existing per-post reads and warnings.
Single-post responses and nested permalink preparation keep their own reads.
Deleted posts and hidden burn-on-read metadata retain their filtering.

## Measurement

The paired benchmark uses the real app, PostgreSQL and local cache. Pages have
one, ten or sixty stored posts, with three standard emoji reactions per post.
Cold cases purge local store caches outside the timer; warm cases use populated
caches. PostgreSQL buffers are not reset. Both variants validate returned reaction metadata inside the timed loop.
The baseline restores only the parent commit's post_metadata.go with a Go
overlay. Store implementations and the benchmark are identical across variants;
the baseline calls the unchanged single-post method.

[results.json](results.json) records source hashes, environment, raw samples
and medians. This measures post preparation on a local database. It excludes
HTTP, files, custom emoji lookup, remote links and production network latency.
It does not measure total chat capacity or unrelated endpoints.

Three alternating paired trials with one second per benchmark case produced
these medians:

| Posts | Cache | Before (ms) | After (ms) |
| --- | --- | ---: | ---: |
| 1 | cold | 0.168 | 0.173 |
| 1 | warm | 0.004 | 0.004 |
| 10 | cold | 1.695 | 0.290 |
| 10 | warm | 0.042 | 0.041 |
| 60 | cold | 10.755 | 0.838 |
| 60 | warm | 0.250 | 0.240 |

Warm and single-post differences are small; no warm-cache speedup is claimed.

## Reproduce

Use the public-only workspace and disposable PostgreSQL/Redis test setup.
Set TEST_DATABASE_POSTGRESQL_DSN and the usual Go cache variables, then run:

```sh
python3 docs/benchmarks/reaction-history/benchmark.py \
  --workspace work/src --baseline c6ff5f19fd67 \
  --duration 1s --trials 3 \
  --output docs/benchmarks/reaction-history/results.json
```

[validation.json](validation.json) records the selected race checks. No new
third-party dependency, API endpoint or schema migration is introduced. The
full branded release workflow was not run for this contribution.
