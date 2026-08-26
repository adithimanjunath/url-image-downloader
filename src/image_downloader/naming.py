"""Derive a safe, deterministic, collision-free filename from a URL.

A filename built only from a URL's last path segment breaks the moment
two different hosts reuse the same naming convention (a common pattern:
sequential IDs, CDN mirrors), so the filename here also depends on the
full URL, not just its final segment.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

_HASH_LENGTH = 8
_MAX_STEM_LENGTH = 60
_FALLBACK_STEM = "image"
_FALLBACK_EXTENSION = ".bin"

# A few characters that are legal in a URL path segment but not in a
# filename (e.g. "photo:thumb.jpg" is a valid URL path, not a valid
# Windows filename).
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def _sanitise_stem(raw_stem: str) -> str:
    """Make `raw_stem` safe to use as a filename component."""
    stem = _UNSAFE_CHARS.sub("_", raw_stem).strip(" .")[:_MAX_STEM_LENGTH]
    return stem or _FALLBACK_STEM


def _resolve_extension(url: str, content_type: str | None) -> str:
    """Pick a file extension: trust the server's Content-Type first, since
    URLs routinely lack a suffix or carry a misleading one; fall back to
    the URL's own suffix, and finally to a generic extension rather than
    guessing further.
    """
    if content_type:
        mime = content_type.split(";", 1)[0].strip()
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed

    url_suffix = PurePosixPath(urlsplit(url).path).suffix
    if url_suffix and len(url_suffix) <= 6 and _UNSAFE_CHARS.search(url_suffix) is None:
        return url_suffix.lower()

    return _FALLBACK_EXTENSION


def is_image_content_type(content_type: str | None) -> bool:
    """True if `content_type` declares an image MIME type.

    A very common real-world failure is a server responding 200 with an
    HTML error page instead of the requested image. Trusting the
    declared Content-Type (rather than the URL, or just saving whatever
    came back) is what catches that case before junk lands on disk.
    """
    if not content_type:
        return False
    mime = content_type.split(";", 1)[0].strip().lower()
    return mime.startswith("image/")


def derive_filename(url: str, content_type: str | None = None) -> str:
    """Build a safe, deterministic filename for `url`.

    The stem comes from the URL's own last path segment so the output
    directory stays readable; a short hash of the *full* URL is always
    appended so two URLs that share a basename never collide, and the
    same URL always maps to the same filename on a re-run — which is
    what lets a re-run skip files it already downloaded.
    """
    raw_stem = PurePosixPath(urlsplit(url).path).stem
    stem = _sanitise_stem(raw_stem) if raw_stem else _FALLBACK_STEM

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
    extension = _resolve_extension(url, content_type)
    return f"{stem}-{digest}{extension}"


def resolve_output_path(output_dir: Path, filename: str) -> Path:
    """Join `filename` onto `output_dir`, guaranteed not to escape it.

    `derive_filename` cannot itself produce a path separator, so this
    can't currently be triggered — it exists as the cheap, final
    assertion that a write can never land outside the intended
    directory, even if that guarantee above ever changes.
    """
    resolved_dir = output_dir.resolve()
    candidate = (resolved_dir / filename).resolve()
    if candidate.parent != resolved_dir:
        raise ValueError(f"resolved path {candidate} escapes output directory {resolved_dir}")
    return candidate
