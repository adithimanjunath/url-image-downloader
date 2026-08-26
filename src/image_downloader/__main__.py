"""Enables `python -m image_downloader ...` as an alternative to the
installed `image-downloader` console script.
"""

from __future__ import annotations

import sys

from image_downloader.cli import main

if __name__ == "__main__":
    sys.exit(main())
