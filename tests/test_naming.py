"""Unit tests for image_downloader.naming."""

from __future__ import annotations

from pathlib import Path

import pytest

from image_downloader.naming import (
    derive_filename,
    is_image_content_type,
    resolve_output_path,
)


def test_two_hosts_sharing_a_basename_do_not_collide() -> None:
    """The actual trap in the brief's own sample data: both URLs end in
    the same basename, on different hosts and different path prefixes.
    A naive `os.path.basename()` would map both to "271947.jpg" and the
    second download would silently overwrite the first.
    """
    name_a = derive_filename("http://mywebserver.com/images/271947.jpg")
    name_b = derive_filename("http://somewebsrv.com/img/271947.jpg")

    assert name_a != name_b


def test_same_url_always_produces_the_same_filename() -> None:
    """Determinism is what makes a re-run idempotent: unchanged input maps
    to the same output path, so a second run can recognise "already have
    this one" instead of re-downloading or renaming it.
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


def test_url_with_no_path_falls_back_to_a_generic_stem() -> None:
    name = derive_filename("http://example.com")

    assert name.startswith("image-")


@pytest.mark.parametrize(
    "url",
    [
        # Percent-decoding a path segment could otherwise inject a
        # traversal sequence or a control character into the filename.
        "http://example.com/%2e%2e%2fsecret.jpg",
        "http://example.com/%00.jpg",
        "http://example.com/weird%3Aname.jpg",
    ],
)
def test_sanitises_decoded_path_traversal_and_control_characters(url: str) -> None:
    name = derive_filename(url)

    assert "/" not in name
    assert "\\" not in name
    assert "\x00" not in name
    assert ".." not in name.split("-")[0]  # the stem portion specifically


def test_reserved_windows_stems_are_escaped() -> None:
    name = derive_filename("http://example.com/CON.jpg")

    assert not name.upper().startswith("CON-")


def test_decodes_percent_encoded_spaces_for_readability() -> None:
    name = derive_filename("http://example.com/my%20photo.jpg")

    assert name.startswith("my photo-") or name.startswith("my_photo-")


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
