"""Unit tests for image_downloader.downloader.

Uses httpx.MockTransport rather than a real local server: it needs no
sockets or background threads, and lets a handler raise a timeout or
connection error on demand, which is what makes the retry tests precise.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from image_downloader.downloader import Config, Status, download_one


def _no_sleep(_seconds: float) -> None:
    """A drop-in for time.sleep that makes retry tests run instantly."""


def _recording_sleep() -> tuple[list[float], Callable[[float], None]]:
    delays: list[float] = []

    def sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, sleep


class _FlakyHandler:
    """A MockTransport handler that fails `fail_times` times before succeeding."""

    def __init__(
        self,
        *,
        fail_times: int,
        success: httpx.Response | None = None,
        failure: httpx.Response | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.fail_times = fail_times
        self.success = success
        self.failure = failure
        self.raise_exc = raise_exc
        self.call_count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            if self.raise_exc is not None:
                raise self.raise_exc
            assert self.failure is not None
            return self.failure
        assert self.success is not None
        return self.success


def _client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


_JPEG_RESPONSE = httpx.Response(
    200, content=b"fake-jpeg-bytes", headers={"content-type": "image/jpeg"}
)


def test_downloads_successfully_and_writes_the_file(tmp_path: Path) -> None:
    client = _client_for(lambda _request: _JPEG_RESPONSE)
    config = Config(output_dir=tmp_path)

    result = download_one(client, "http://example.com/photo.jpg", config, sleep=_no_sleep)

    assert result.status is Status.OK
    assert result.attempts == 1
    assert result.path is not None
    assert result.path.read_bytes() == b"fake-jpeg-bytes"
    assert result.bytes_written == len(b"fake-jpeg-bytes")


def test_skips_an_existing_file_without_overwrite(tmp_path: Path) -> None:
    client = _client_for(lambda _request: _JPEG_RESPONSE)
    config = Config(output_dir=tmp_path, overwrite=False)

    first = download_one(client, "http://example.com/photo.jpg", config, sleep=_no_sleep)
    assert first.path is not None
    first.path.write_bytes(b"pre-existing-content")

    second = download_one(client, "http://example.com/photo.jpg", config, sleep=_no_sleep)

    assert second.status is Status.SKIPPED
    assert second.path is not None
    assert second.path.read_bytes() == b"pre-existing-content"


def test_overwrite_flag_forces_a_fresh_download(tmp_path: Path) -> None:
    client = _client_for(lambda _request: _JPEG_RESPONSE)
    config = Config(output_dir=tmp_path, overwrite=True)

    first = download_one(client, "http://example.com/photo.jpg", config, sleep=_no_sleep)
    assert first.path is not None
    first.path.write_bytes(b"stale-content")

    second = download_one(client, "http://example.com/photo.jpg", config, sleep=_no_sleep)

    assert second.status is Status.OK
    assert second.path is not None
    assert second.path.read_bytes() == b"fake-jpeg-bytes"


def test_retries_on_server_error_then_succeeds(tmp_path: Path) -> None:
    handler = _FlakyHandler(fail_times=1, success=_JPEG_RESPONSE, failure=httpx.Response(503))
    client = _client_for(handler)
    config = Config(output_dir=tmp_path, max_retries=3)
    delays, sleep = _recording_sleep()

    result = download_one(client, "http://example.com/photo.jpg", config, sleep=sleep)

    assert result.status is Status.OK
    assert result.attempts == 2
    assert delays == [1.0]  # one backoff, before the second (successful) attempt


def test_retries_on_connection_timeout_then_succeeds(tmp_path: Path) -> None:
    handler = _FlakyHandler(
        fail_times=1, success=_JPEG_RESPONSE, raise_exc=httpx.ConnectTimeout("simulated timeout")
    )
    client = _client_for(handler)
    config = Config(output_dir=tmp_path, max_retries=3)

    result = download_one(client, "http://example.com/photo.jpg", config, sleep=_no_sleep)

    assert result.status is Status.OK
    assert result.attempts == 2


def test_does_not_retry_a_404(tmp_path: Path) -> None:
    handler = _FlakyHandler(fail_times=99, failure=httpx.Response(404))
    client = _client_for(handler)
    config = Config(output_dir=tmp_path, max_retries=3)
    delays, sleep = _recording_sleep()

    result = download_one(client, "http://example.com/missing.jpg", config, sleep=sleep)

    assert result.status is Status.FAILED
    assert result.attempts == 1
    assert "404" in (result.error or "")
    assert delays == []  # a permanent failure must not trigger a retry


def test_gives_up_after_max_retries(tmp_path: Path) -> None:
    handler = _FlakyHandler(fail_times=99, failure=httpx.Response(503))
    client = _client_for(handler)
    config = Config(output_dir=tmp_path, max_retries=3)

    result = download_one(client, "http://example.com/photo.jpg", config, sleep=_no_sleep)

    assert result.status is Status.FAILED
    assert result.attempts == 3
    assert "503" in (result.error or "")


def test_rejects_a_non_image_response(tmp_path: Path) -> None:
    html_response = httpx.Response(
        200, content=b"<html>error</html>", headers={"content-type": "text/html"}
    )
    client = _client_for(lambda _request: html_response)
    config = Config(output_dir=tmp_path)

    result = download_one(client, "http://example.com/photo.jpg", config, sleep=_no_sleep)

    assert result.status is Status.FAILED
    assert "not an image" in (result.error or "")
    assert list(tmp_path.iterdir()) == []


def test_aborts_and_cleans_up_when_body_exceeds_max_bytes(tmp_path: Path) -> None:
    big_response = httpx.Response(200, content=b"x" * 1000, headers={"content-type": "image/jpeg"})
    client = _client_for(lambda _request: big_response)
    config = Config(output_dir=tmp_path, max_bytes=100)

    result = download_one(client, "http://example.com/huge.jpg", config, sleep=_no_sleep)

    assert result.status is Status.FAILED
    assert "max-bytes" in (result.error or "")
    # no partial .part file, and no final file, left behind
    assert list(tmp_path.iterdir()) == []


def test_result_reflects_multiple_urls_without_cross_contamination(tmp_path: Path) -> None:
    """A regression guard for a plausible bug: state leaking between calls
    (e.g. reusing a mutable default argument) would make this fail.
    """
    client = _client_for(lambda _request: _JPEG_RESPONSE)
    config = Config(output_dir=tmp_path)

    result_a = download_one(client, "http://a.example.com/img/1.jpg", config, sleep=_no_sleep)
    result_b = download_one(client, "http://b.example.com/images/1.jpg", config, sleep=_no_sleep)

    assert result_a.path != result_b.path
    assert result_a.status is Status.OK
    assert result_b.status is Status.OK
