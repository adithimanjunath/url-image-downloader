"""Unit tests for image_downloader.naming."""

from __future__ import annotations

from pathlib import Path

import pytest

from image_downloader.naming import (
    derive_filename,
    is_image_content_type,
    resolve_output_path,
)


def test_two_different_hosts_sharing_a_basename_do_not_collide() -> None:
    """Not lifted from the brief's own 3-line example (those three
    basenames are already distinct) — but two different hosts easily
    could reuse the same numbering scheme, so the filename can't rely on
    the URL's basename alone.
    """
    name_a = derive_filename("http://mywebserver.com/images/1001.jpg")
    name_b = derive_filename("http://otherhost.com/pics/1001.jpg")

    assert name_a != name_b


def test_same_url_always_produces_the_same_filename() -> None:
    """Determinism is what makes a re-run idempotent: unchanged input maps
    to the same output path, so a second run can recognise "already have
    this one" instead of re-downloading it.
    """
    url = "http://mywebserver.com/images/271947.jpg"

    assert derive_filename(url) == derive_filename(url)


def test_keeps_a_readable_stem_from_the_url() -> None:
    name = derive_filename("http://mywebserver.com/images/271947.jpg")

    assert name.startswith("271947-")
    assert name.endswith(".jpg")


def test_content_type_takes_precedence_over_url_suffix() -> None:
    # The URL claims .jpg but the server says PNG — trust the server.
    name = derive_filename("http://example.com/images/271947.jpg", content_type="image/png")

    assert name.endswith(".png")


def test_falls_back_to_url_suffix_without_a_content_type() -> None:
    name = derive_filename("http://example.com/images/271947.jpg")

    assert name.endswith(".jpg")


def test_falls_back_to_generic_extension_with_no_hints_at_all() -> None:
    name = derive_filename("http://example.com/images/271947")

    assert name.endswith(".bin")


@pytest.mark.parametrize(
    "url", ["http://example.com/photo:thumb.jpg", "http://example.com/a*b.jpg"]
)
def test_sanitises_filesystem_unsafe_characters(url: str) -> None:
    # ":" and "*" are legal, unencoded URL path characters but not legal
    # filename characters on every OS.
    name = derive_filename(url)

    assert ":" not in name
    assert "*" not in name


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("image/jpeg", True),
        ("image/png; charset=binary", True),
        ("text/html", False),
        ("application/json", False),
        (None, False),
        ("", False),
    ],
)
def test_is_image_content_type(content_type: str | None, expected: bool) -> None:
    assert is_image_content_type(content_type) is expected


def test_resolve_output_path_joins_inside_the_output_dir(tmp_path: Path) -> None:
    path = resolve_output_path(tmp_path, "photo-a3f9c1d2.jpg")

    assert path.parent == tmp_path.resolve()
    assert path.name == "photo-a3f9c1d2.jpg"


def test_resolve_output_path_rejects_a_filename_that_would_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes output directory"):
        resolve_output_path(tmp_path, "../escaped.jpg")
