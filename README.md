# image-downloader

[![CI](https://github.com/adithimanjunath/url-image-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/adithimanjunath/url-image-downloader/actions/workflows/ci.yml)

Downloads all the images listed in a plaintext file — one URL per line — to
local disk, concurrently and safely enough to run unattended.

```bash
uv sync
uv run image-downloader sample_urls.txt -o downloads
```

`sample_urls.txt` includes two deliberately broken URLs, so the first run
shows the error handling, not just the happy path.

## Usage

```
image-downloader [-h] [-o OUTPUT] [-c CONCURRENCY]
                  [--connect-timeout SECONDS] [--read-timeout SECONDS]
                  [--max-bytes N] [--max-retries N] [--overwrite] [-v | -q]
                  input_file
```

| Flag | Default | |
|---|---|---|
| `input_file` | — | Plaintext file of URLs, one per line. `#` comments, blank lines skipped. |
| `-o, --output` | `downloads` | Output directory, created if missing. |
| `-c, --concurrency` | `8` | Max concurrent downloads. |
| `--connect-timeout` / `--read-timeout` | `5.0` / `30.0` | Seconds. |
| `--max-bytes` | 100 MiB | Abort a response larger than this. |
| `--max-retries` | `3` | Attempts per URL before giving up. |
| `--overwrite` | off | Re-download files that already exist. |
| `-v` / `-q` | — | Debug logging / warnings-and-errors only. |

**Exit codes:** `0` all ok · `1` a URL failed or was rejected · `2` input
file not found · `130` interrupted. Re-running against the same output
directory is safe — existing files are skipped, not re-fetched.

## Design decisions

- **Threads, not asyncio** — downloads are I/O-bound, and threads keep the
  code simple to read.
- **Filename = stem + hash of the full URL** — so two hosts never overwrite
  each other, and re-runs skip files already downloaded.
- **Extension from Content-Type, falling back to the URL** — also catches a
  server returning an error page instead of an image.
- **Streamed to disk with a size cap** — never loads a whole response into
  memory.
- **Atomic writes via a `.part` file** — a crash or Ctrl-C never leaves a
  broken image behind.
- **Retries with backoff** — only for timeouts/connection errors/5xx; never
  for a 404.
- **`http`/`https` only** — an input file shouldn't be able to read local
  files.
- **`logging`, not `print`** — output can be filtered with `-v`/`-q` instead
  of always printing everything.

## Testing & CI

```bash
uv run pytest --cov     # 47 tests, 99% coverage
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src tests
```

Same four commands run in GitHub Actions on every push
(`.github/workflows/ci.yml`). Unit tests use `httpx.MockTransport` (no real
sockets); the CLI tests spin up a real `http.server` on `127.0.0.1` instead,
to prove the whole pipeline over an actual socket. No test touches the real
internet. Covers a basename collision across hosts, retry-then-succeed vs.
no-retry-on-404, an HTML page served as 200, the size cap, idempotent
re-runs, a 50-URL file, and Ctrl-C.

## Out of scope

Deliberately not built: a Flask/REST wrapper (this is a CLI; one would just
wrap `download_one()` directly), a BDD/Gherkin suite (a second test
framework for scenarios plain `pytest` already covers), magic-byte content
sniffing, `Retry-After` parsing, partial/resumable downloads, a run
manifest, per-host rate limiting, JSON logs, a multi-OS CI matrix, and SQL
persistence. Each is reasonable on a long-lived service; none are needed
here.

**One limitation stated rather than hidden:** `download_one()` relies on its
caller to deduplicate URLs first (which `urls.py` does) — two concurrent
calls for the *same* URL would race on the same temp file. Not reachable
through this CLI today, but worth knowing if the function is ever reused
elsewhere.
