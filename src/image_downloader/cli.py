"""Command-line entry point: argument parsing, logging, the thread pool,
and turning a batch of results into a process exit code.
"""

from __future__ import annotations

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from image_downloader.downloader import Config, DownloadResult, Status, download_one
from image_downloader.urls import parse_url_file

logger = logging.getLogger("image_downloader")

_USER_AGENT = "image-downloader/1.0 (+https://github.com/adithimanjunath/url-image-downloader)"

_EXIT_OK = 0
_EXIT_PARTIAL_FAILURE = 1
_EXIT_USAGE_ERROR = 2
_EXIT_INTERRUPTED = 130


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-downloader",
        description="Download images listed in a plaintext file, one URL per line.",
    )
    parser.add_argument(
        "input_file", type=Path, help="Path to a plaintext file of image URLs, one per line."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("downloads"),
        help="Directory to save images into (default: %(default)s).",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=8,
        help="Number of concurrent downloads (default: %(default)s).",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=5.0,
        help="Connection timeout in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=30.0,
        help="Read timeout in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=100 * 1024 * 1024,
        help="Maximum bytes accepted per image (default: 100 MiB).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum attempts per URL before giving up (default: %(default)s).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download and overwrite files that already exist.",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="Only log warnings and errors."
    )
    return parser


def _configure_logging(*, verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _run_downloads(urls: list[str], config: Config) -> list[DownloadResult]:
    timeout = httpx.Timeout(config.connect_timeout, read=config.read_timeout)
    headers = {"User-Agent": _USER_AGENT}
    results: list[DownloadResult] = []

    with (
        httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client,
        ThreadPoolExecutor(max_workers=config.concurrency) as pool,
    ):
        futures = [pool.submit(download_one, client, url, config) for url in urls]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            logger.debug("%s: %s", result.status.value, result.url)

    return results


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    _configure_logging(verbose=args.verbose, quiet=args.quiet)

    if not args.input_file.is_file():
        logger.error("input file not found: %s", args.input_file)
        return _EXIT_USAGE_ERROR

    parsed = parse_url_file(args.input_file)
    for parse_error in parsed.errors:
        logger.warning("%s", parse_error)

    if not parsed.urls:
        logger.info("no valid URLs to download")
        return _EXIT_OK if not parsed.errors else _EXIT_PARTIAL_FAILURE

    args.output.mkdir(parents=True, exist_ok=True)
    config = Config(
        output_dir=args.output,
        concurrency=args.concurrency,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        max_bytes=args.max_bytes,
        max_retries=args.max_retries,
        overwrite=args.overwrite,
    )

    try:
        results = _run_downloads(parsed.urls, config)
    except KeyboardInterrupt:
        logger.warning("interrupted; in-flight downloads were allowed to finish cleanly")
        return _EXIT_INTERRUPTED

    succeeded = sum(1 for r in results if r.status is Status.OK)
    skipped = sum(1 for r in results if r.status is Status.SKIPPED)
    failed = [r for r in results if r.status is Status.FAILED]

    logger.info(
        "done: %d downloaded, %d skipped, %d failed (of %d URLs)",
        succeeded,
        skipped,
        len(failed),
        len(results),
    )
    for result in failed:
        logger.error("failed: %s (%s)", result.url, result.error)

    if failed or parsed.errors:
        return _EXIT_PARTIAL_FAILURE
    return _EXIT_OK
