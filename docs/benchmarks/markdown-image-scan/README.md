# Markdown image scanning during history preparation

Inline and reference Markdown images require a literal exclamation mark. Text
without that marker returns the existing empty image slice before parsing.
Inputs containing the marker keep the full parser and preview-domain checks.
Autolink, OpenGraph and interactive-block image handling are unchanged.

This is an independent patch over the original 38-patch Mattermax workspace.
It does not depend on the other performance PRs. The original patch files and
contributor credits are preserved.

## Measurement

The benchmark prepares real 60-post history pages with the default priority and
acknowledgement reads. It includes short text, longer prose, formatting, ordinary
exclamation marks and cached inline/reference images. Both variants use the
same benchmark and store code; the baseline restores only post_metadata.go
through a Go overlay. Setup and image-cache warming are outside the timer.
Timed loops validate image counts and dimensions, and image cases fail if a
network fetch occurs during timing.

[results.json](results.json) records environment, source hashes, raw paired
samples and medians. Measurements use a local database and warm metadata
caches. They exclude HTTP request handling, image transfer/decoding, files and
custom emoji. These results measure page preparation, not total server capacity.

Three alternating paired trials with one second per benchmark case produced
these medians:

| Case | Before (ms) | After (ms) |
| --- | ---: | ---: |
| short | 0.126 | 0.079 |
| prose | 4.557 | 2.480 |
| formatting | 7.201 | 3.591 |
| bang_control | 0.127 | 0.126 |
| inline_image | 2.130 | 2.134 |
| reference_image | 2.234 | 2.223 |

Punctuation and image cases exercise the unchanged parser path. No speedup
is claimed for those controls.

## Reproduce

Create the public-only workspace and use disposable PostgreSQL/Redis test
services. Set TEST_DATABASE_POSTGRESQL_DSN and the usual Go cache variables:

```sh
python3 docs/benchmarks/markdown-image-scan/benchmark.py \
  --workspace work/src --baseline c9dbbcc480b2 \
  --duration 1s --trials 3 \
  --output docs/benchmarks/markdown-image-scan/results.json
```

[validation.json](validation.json) records the selected app race checks. They
cover image syntax, entities, escapes, code, references, preview restrictions,
OpenGraph, message attachments, interactive blocks and image proxies. The
same syntax cases also pass against the unmodified baseline parser. The full
branded release build and complete repository test suite were not run.
No API endpoint, schema change or third-party dependency is added.
