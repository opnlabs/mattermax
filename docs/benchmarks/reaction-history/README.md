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

Measurement correction: these runs populate and validate PostList.Order, so default priority and acknowledgement reads execute. They supersede the earlier fixtures, which omitted Order.

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
| 1 | cold | 0.484 | 0.657 |
| 1 | warm | 0.268 | 0.256 |
| 10 | cold | 1.943 | 0.582 |
| 10 | warm | 0.342 | 0.323 |
| 60 | cold | 10.538 | 1.233 |
| 60 | warm | 0.856 | 0.819 |

No warm-cache speedup is claimed. The single-post cold case was slower in
this matrix; see single-post-control.json for longer isolated control runs.

Longer isolated single-post cold controls (three paired trials, three seconds
per case) measured median 0.500 ms before and 0.447 ms after. The sample
ranges overlap. These controls do not establish a single-post speedup.

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
