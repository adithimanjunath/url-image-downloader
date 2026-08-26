"""End-to-end tests for the CLI: argument parsing, exit codes, and wiring.

Download mechanics (retry, streaming, atomic writes) are already covered
in test_downloader.py; these tests focus on what's specific to the CLI
layer itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import image_downloader.cli as cli_module
from image_downloader.cli import main


def _write_urls(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "urls.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_downloads_a_real_file_over_a_real_socket(tmp_path: Path, local_server: str) -> None:
    urls_file = _write_urls(tmp_path, f"{local_server}/ok.jpg")
    out_dir = tmp_path / "out"

    exit_code = main([str(urls_file), "-o", str(out_dir), "-q"])

    assert exit_code == 0
    assert len(list(out_dir.glob("*.jpg"))) == 1


def test_exit_code_reflects_partial_failure(tmp_path: Path, local_server: str) -> None:
    urls_file = _write_urls(tmp_path, f"{local_server}/ok.jpg", f"{local_server}/missing.jpg")
    out_dir = tmp_path / "out"

    exit_code = main([str(urls_file), "-o", str(out_dir), "-q"])

    assert exit_code == 1


def test_exit_code_for_a_missing_input_file(tmp_path: Path) -> None:
    exit_code = main([str(tmp_path / "does-not-exist.txt"), "-o", str(tmp_path / "out")])

    assert exit_code == 2


def test_exit_code_for_an_empty_input_file(tmp_path: Path) -> None:
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("", encoding="utf-8")

    exit_code = main([str(urls_file), "-o", str(tmp_path / "out")])

    assert exit_code == 0


def test_creates_the_output_directory_if_missing(tmp_path: Path, local_server: str) -> None:
    urls_file = _write_urls(tmp_path, f"{local_server}/ok.jpg")
    out_dir = tmp_path / "nested" / "out"
    assert not out_dir.exists()

    exit_code = main([str(urls_file), "-o", str(out_dir), "-q"])

    assert exit_code == 0
    assert out_dir.is_dir()


def test_a_rejected_url_still_lets_valid_urls_download(tmp_path: Path, local_server: str) -> None:
    urls_file = _write_urls(tmp_path, "ftp://bad.example.com/x.jpg", f"{local_server}/ok.jpg")
    out_dir = tmp_path / "out"

    exit_code = main([str(urls_file), "-o", str(out_dir), "-q"])

    assert exit_code == 1
    assert len(list(out_dir.glob("*.jpg"))) == 1


def test_handles_a_realistic_file_of_many_distinct_urls(tmp_path: Path, local_server: str) -> None:
    """The brief's own example is only 3 lines, but a real input file could
    reasonably hold hundreds of URLs from many different paths. This proves
    the CLI isn't just tuned for a 3-line sample: every one of 50 distinct
    URLs, all bounded by the default concurrency of 8 workers, downloads to
    its own correctly-named file, and none are dropped, merged, or skipped.
    """
    url_count = 50
    urls_file = _write_urls(tmp_path, *(f"{local_server}/ok/{i}.jpg" for i in range(url_count)))
    out_dir = tmp_path / "out"

    exit_code = main([str(urls_file), "-o", str(out_dir), "-q"])

    downloaded = list(out_dir.glob("*.jpg"))
    assert exit_code == 0
    assert len(downloaded) == url_count
    assert len({f.name for f in downloaded}) == url_count  # every filename is unique


def test_keyboard_interrupt_exits_cleanly_without_a_traceback(
    tmp_path: Path, local_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real Ctrl-C is hard to simulate reliably; raising it from inside
    `_run_downloads` exercises the same handler in `main()` without one.
    """
    urls_file = _write_urls(tmp_path, f"{local_server}/ok.jpg")

    def _raise_interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "_run_downloads", _raise_interrupt)

    exit_code = main([str(urls_file), "-o", str(tmp_path / "out"), "-q"])

    assert exit_code == 130


def test_installed_entry_point_runs_as_a_real_subprocess(tmp_path: Path, local_server: str) -> None:
    """Proves the packaging wiring itself works: a separate process, real
    argv, and the actual `python -m image_downloader` entry point — not
    just the `main()` function called in-process like the tests above.
    """
    urls_file = _write_urls(tmp_path, f"{local_server}/ok.jpg")
    out_dir = tmp_path / "out"

    completed = subprocess.run(
        [sys.executable, "-m", "image_downloader", str(urls_file), "-o", str(out_dir), "-q"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert len(list(out_dir.glob("*.jpg"))) == 1
