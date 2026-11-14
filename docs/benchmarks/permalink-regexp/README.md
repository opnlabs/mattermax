# Reusing the permalink-path regexp

Post preparation checks whether URLs look like local permalinks. The SiteURL
prefix check returns immediately for external URLs. For matching prefixes,
regexp.MatchString compiles the same constant path pattern on each call.
The patch compiles that pattern once and shares the resulting matcher.

The pattern, whitespace trimming, prefix handling and removal of one leading
slash are unchanged. This preserves existing URL acceptance, including empty
SiteURL and prefix behavior. There is no URL-normalization change. The original
38 Mattermax patch files and contributor credits remain unchanged.

## Measurement

Measurement correction: these runs populate and validate PostList.Order, so default priority and acknowledgement reads execute. They supersede the earlier fixtures, which omitted Order.

The benchmark prepares real stored 60-post pages with explicitly configured
SiteURL and default priority/acknowledgement reads. It covers plain text,
external images, same-site images, a site subpath, same-site non-permalink links
and actual permalink previews. Ordinary link previews are disabled; permalink
previews remain enabled. Setup and cache warming are outside the timer. Timed
loops validate image dimensions and permalink targets, and fail on any image
fetch during timing.

Both variants use the same benchmark and store code. A Go overlay restores
only the baseline post_metadata.go, including the per-call regexp compilation.
[results.json](results.json) records source hashes, environment, raw paired
samples and medians. The baseline is the original 38-patch workspace, so this
contribution is independent of the other performance PRs.

The expected benefit applies when candidate URLs share the configured SiteURL
prefix. Plain text and external-image cases are controls for the existing
prefix rejection path. These local preparation timings exclude HTTP request
handling, image transfer/decoding, attachments and custom emoji; they do not
measure total server throughput.

Three alternating paired trials with one second per benchmark case produced
these medians:

| Case | Before (ms) | After (ms) |
| --- | ---: | ---: |
| plain | 0.755 | 0.790 |
| external_image | 1.119 | 1.164 |
| same_site_image | 3.673 | 1.158 |
| subpath_image | 3.777 | 1.183 |
| same_site_link | 3.441 | 0.928 |
| permalink | 4.086 | 1.654 |

No speedup is claimed for plain text or external-image controls.

## Reproduce

Create the public-only workspace and use disposable PostgreSQL/Redis test
services. Set TEST_DATABASE_POSTGRESQL_DSN and the usual Go cache variables:

```sh
python3 docs/benchmarks/permalink-regexp/benchmark.py \
  --workspace work/src --baseline c9dbbcc480b2 \
  --duration 1s --trials 3 \
  --output docs/benchmarks/permalink-regexp/results.json
```

[validation.json](validation.json) records the selected race checks. They cover
URL boundaries, whitespace, subpaths, image/proxy metadata, direct/group-message
previews, nested previews and metadata filtering for non-members. The same new
boundary cases also pass against the unmodified baseline matcher. The full
branded release build and complete repository test suite were not run. No API
endpoint, schema change or third-party dependency is added.
