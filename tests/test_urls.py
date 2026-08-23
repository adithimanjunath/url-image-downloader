"""Unit tests for image_downloader.urls."""

from __future__ import annotations

from pathlib import Path

import pytest

from image_downloader.urls import parse_url_file


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "urls.txt"
    path.write_text(content, encoding="utf-8")
    return path


def test_parses_simple_valid_urls(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "http://mywebserver.com/images/271947.jpg\nhttps://somewebsrv.com/img/992147.jpg\n",
    )

    result = parse_url_file(path)

    assert result.urls == [
        "http://mywebserver.com/images/271947.jpg",
        "https://somewebsrv.com/img/992147.jpg",
    ]
    assert result.errors == []


def test_skips_blank_lines_and_comments(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "\n# a comment describing the batch below\nhttp://mywebserver.com/images/1.jpg\n   \n",
    )

    result = parse_url_file(path)

    assert result.urls == ["http://mywebserver.com/images/1.jpg"]
    assert result.errors == []


def test_strips_surrounding_whitespace(tmp_path: Path) -> None:
    path = _write(tmp_path, "   http://mywebserver.com/images/1.jpg   \n")

    result = parse_url_file(path)

    assert result.urls == ["http://mywebserver.com/images/1.jpg"]


@pytest.mark.parametrize(
    "line",
    [
        "ftp://mywebserver.com/images/1.jpg",
        "file:///etc/passwd",
        "data:image/png;base64,aGVsbG8=",
        "not-a-url-at-all",
    ],
)
def test_rejects_disallowed_schemes(tmp_path: Path, line: str) -> None:
    path = _write(tmp_path, f"{line}\n")

    result = parse_url_file(path)

    assert result.urls == []
    assert len(result.errors) == 1
    assert result.errors[0].line_number == 1
    assert "scheme" in result.errors[0].reason


def test_rejects_url_with_no_host(tmp_path: Path) -> None:
    path = _write(tmp_path, "http:///images/1.jpg\n")

    result = parse_url_file(path)

    assert result.urls == []
    assert "host" in result.errors[0].reason


def test_deduplicates_preserving_first_occurrence_order(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "http://mywebserver.com/images/1.jpg\n"
        "http://mywebserver.com/images/2.jpg\n"
        "http://mywebserver.com/images/1.jpg\n",
    )

    result = parse_url_file(path)

    assert result.urls == [
        "http://mywebserver.com/images/1.jpg",
        "http://mywebserver.com/images/2.jpg",
    ]


def test_reports_correct_line_numbers_in_a_mixed_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "http://mywebserver.com/images/1.jpg\n"  # line 1: valid
        "ftp://bad.example.com/x.jpg\n"  # line 2: invalid
        "\n"  # line 3: blank
        "http://mywebserver.com/images/2.jpg\n",  # line 4: valid
    )

    result = parse_url_file(path)

    assert result.urls == [
        "http://mywebserver.com/images/1.jpg",
        "http://mywebserver.com/images/2.jpg",
    ]
    assert len(result.errors) == 1
    assert result.errors[0].line_number == 2


def test_tolerates_a_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "urls.txt"
    path.write_bytes(b"\xef\xbb\xbfhttp://mywebserver.com/images/1.jpg\n")

    result = parse_url_file(path)

    assert result.urls == ["http://mywebserver.com/images/1.jpg"]


def test_error_str_is_actionable(tmp_path: Path) -> None:
    path = _write(tmp_path, "ftp://bad.example.com/x.jpg\n")

    result = parse_url_file(path)

    message = str(result.errors[0])
    assert message.startswith("line 1:")
    assert "ftp://bad.example.com/x.jpg" in message
