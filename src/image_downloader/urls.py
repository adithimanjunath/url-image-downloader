"""Parse and validate the plaintext file of image URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class UrlParseError:
    """One rejected line, with enough context for a human to fix it."""

    line_number: int
    raw: str
    reason: str

    def __str__(self) -> str:
        return f"line {self.line_number}: {self.reason}: {self.raw!r}"


@dataclass(slots=True)
class ParsedUrls:
    """What to download, and what was rejected, from one input file."""

    urls: list[str] = field(default_factory=list)
    errors: list[UrlParseError] = field(default_factory=list)


def _validate(raw: str) -> str | None:
    """Return a rejection reason for `raw`, or None if it is downloadable.

    Only http/https are allowed. Accepting file:// would let a URL list
    read arbitrary local files instead of downloading anything; neither
    that nor a data: URI is "downloading an image from a URL".
    """
    parts = urlsplit(raw)
    if parts.scheme not in _ALLOWED_SCHEMES:
        return f"unsupported scheme {parts.scheme!r} (only http/https are allowed)"
    if not parts.netloc:
        return "missing host"
    return None


def parse_url_file(path: Path) -> ParsedUrls:
    """Read `path` and return the deduplicated, validated URLs plus any errors.

    - Lines are stripped; blank lines and lines starting with '#' are skipped,
      so a URL list can carry its own comments.
    - A UTF-8 BOM (common when a file is saved by Windows tools) is tolerated.
    - Duplicate URLs are dropped, keeping the first occurrence's position, so
      a URL repeated in the input is only downloaded once.
    """
    result = ParsedUrls()
    seen: set[str] = set()

    with path.open(encoding="utf-8-sig") as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            reason = _validate(line)
            if reason is not None:
                result.errors.append(UrlParseError(line_number, line, reason))
                continue

            if line in seen:
                continue
            seen.add(line)
            result.urls.append(line)

    return result
