"""Download a single URL: retry transient failures, stream to disk, and
write atomically so a crash or Ctrl-C never leaves a corrupt image behind.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx

from image_downloader.naming import derive_filename, is_image_content_type, resolve_output_path

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 64 * 1024  # 64 KiB: small enough to bound memory, large enough to be efficient
_BACKOFF_BASE_SECONDS = 1.0
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class Status(StrEnum):
    """The outcome of attempting to download a single URL."""

    OK = "ok"
    SKIPPED = "skipped"  # file already existed on disk (idempotent re-run)
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Config:
    """Fully resolved run configuration, built once by the CLI layer.

    Assumes `output_dir` already exists — creating it is the caller's job,
    done once up front rather than repeated on every download attempt.
    """

    output_dir: Path
    concurrency: int = 8
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    max_bytes: int = 100 * 1024 * 1024  # 100 MiB
    max_retries: int = 3
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """The result of attempting to download one URL."""

    url: str
    status: Status
    path: Path | None = None
    bytes_written: int = 0
    attempts: int = 1
    error: str | None = None


class _RetryableError(Exception):
    """A transient failure worth retrying: a timeout, a dropped connection,
    or an HTTP status that usually means "try again later" (5xx/429/408).
    """


def _stream_to_disk(response: httpx.Response, final_path: Path, max_bytes: int) -> int:
    """Write `response`'s body to `final_path` atomically.

    The body is streamed into a `.part` file in the same directory and
    only renamed onto `final_path` once fully written — `os.replace` is
    atomic on both POSIX and Windows, so a reader can never observe a
    half-written image. If anything goes wrong, including a KeyboardInterrupt,
    the partial `.part` file is removed rather than left behind.
    """
    part_path = final_path.with_name(final_path.name + ".part")
    bytes_written = 0
    try:
        with part_path.open("wb") as fh:
            for chunk in response.iter_bytes(chunk_size=_CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise ValueError(f"body exceeded max-bytes limit of {max_bytes}")
                fh.write(chunk)
        part_path.replace(final_path)
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise
    return bytes_written


def _attempt(client: httpx.Client, url: str, config: Config, attempt: int) -> DownloadResult:
    """One full request-and-write attempt.

    Raises `_RetryableError` for failures worth retrying. Returns a
    `DownloadResult` directly for success, an idempotent skip, or a
    failure that retrying would not fix (a 404, a non-image response,
    an oversized body).
    """
    try:
        with client.stream("GET", url) as response:
            if response.status_code in _RETRYABLE_STATUS_CODES:
                raise _RetryableError(f"HTTP {response.status_code}")
            if response.status_code != 200:
                return DownloadResult(
                    url=url,
                    status=Status.FAILED,
                    attempts=attempt,
                    error=f"HTTP {response.status_code}",
                )

            content_type = response.headers.get("content-type")
            if not is_image_content_type(content_type):
                return DownloadResult(
                    url=url,
                    status=Status.FAILED,
                    attempts=attempt,
                    error=f"not an image (content-type: {content_type!r})",
                )

            filename = derive_filename(url, content_type)
            final_path = resolve_output_path(config.output_dir, filename)
            if final_path.exists() and not config.overwrite:
                return DownloadResult(
                    url=url, status=Status.SKIPPED, attempts=attempt, path=final_path
                )

            bytes_written = _stream_to_disk(response, final_path, config.max_bytes)
            return DownloadResult(
                url=url,
                status=Status.OK,
                attempts=attempt,
                path=final_path,
                bytes_written=bytes_written,
            )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise _RetryableError(str(exc)) from exc


def download_one(
    client: httpx.Client,
    url: str,
    config: Config,
    sleep: Callable[[float], None] = time.sleep,
) -> DownloadResult:
    """Download a single URL, retrying transient failures with backoff.

    Each attempt re-does the whole request from scratch — there is no
    partial resume. That keeps the retry logic simple to reason about,
    at the cost of re-fetching bytes already received on a mid-stream
    failure, which is a reasonable trade at this scale.

    `sleep` is injectable so tests can assert retry behaviour without
    actually waiting for real backoff delays.
    """
    last_error = "exhausted retries"
    for attempt in range(1, config.max_retries + 1):
        try:
            return _attempt(client, url, config, attempt)
        except _RetryableError as exc:
            last_error = str(exc)
            logger.warning(
                "attempt %d/%d failed for %s: %s", attempt, config.max_retries, url, last_error
            )
            if attempt < config.max_retries:
                sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
        except Exception as exc:
            # A single bad URL must never take down the whole run: convert
            # any other failure into a result instead of an unhandled crash.
            return DownloadResult(url=url, status=Status.FAILED, attempts=attempt, error=str(exc))

    return DownloadResult(
        url=url, status=Status.FAILED, attempts=config.max_retries, error=last_error
    )
