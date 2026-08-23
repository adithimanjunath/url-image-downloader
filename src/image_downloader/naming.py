"""Derive a safe, deterministic, collision-free filename from a URL.

Two different hosts routinely reuse the same basename convention (this
sample data does exactly that: .../images/271947.jpg on one host and
.../img/271947.jpg on another) so a filename derived from the URL alone
must include something host- and path-specific, or one download silently
overwrites another.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

_HASH_LENGTH = 8
_MAX_STEM_LENGTH = 60
_FALLBACK_STEM = "image"
_FALLBACK_EXTENSION = ".bin"

# Illegal on Windows, plus control characters (a decoded URL segment can
# contain either, e.g. a path component of "%00" or "%3F").
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Reserved on Windows regardless of extension (CON.jpg is still invalid).
_WINDOWS_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _sanitise_stem(raw_stem: str) -> str:
    """Make `raw_stem` safe to use as a filename component on any OS."""
    stem = _UNSAFE_CHARS.sub("_", raw_stem).strip(" .")
    stem = stem[:_MAX_STEM_LENGTH]
    if not stem:
        stem = _FALLBACK_STEM
    if stem.upper() in _WINDOWS_RESERVED_STEMS:
        stem = f"_{stem}"
    return stem


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
    decoded_path = unquote(urlsplit(url).path)
    raw_stem = PurePosixPath(decoded_path).stem
    stem = _sanitise_stem(raw_stem) if raw_stem else _FALLBACK_STEM

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
    extension = _resolve_extension(url, content_type)
    return f"{stem}-{digest}{extension}"


def resolve_output_path(output_dir: Path, filename: str) -> Path:
    """Join `filename` onto `output_dir`, guaranteed not to escape it.

    `derive_filename` cannot itself produce a path separator or a ".."
    component, so this can't currently be triggered — it exists as the
    cheap, final assertion that a write can never land outside the
    intended directory, even if that guarantee above ever changes.
    """
    resolved_dir = output_dir.resolve()
    candidate = (resolved_dir / filename).resolve()
    if candidate.parent != resolved_dir:
        raise ValueError(f"resolved path {candidate} escapes output directory {resolved_dir}")
    return candidate
