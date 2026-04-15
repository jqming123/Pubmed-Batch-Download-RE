"""Warm up the first PMID with a headed browser, then batch the rest.

This wrapper is meant for the workflow where a user manually clears a challenge
page once, then reuses the same Playwright profile for the remaining PMIDs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_TMP_DIR = REPO_ROOT / "tmp"
FETCH_PDFS = SCRIPT_DIR / "fetch_pdfs.py"


def _resolve_path(value: str, base_dir: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if base_dir is not None:
        return (base_dir / path).resolve()
    return path.resolve()


def _load_pmf(pmf_path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with pmf_path.open("r", encoding="utf-8") as file_handle:
        for raw_line in file_handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            pmid = parts[0]
            name = parts[1] if len(parts) > 1 else pmid
            rows.append((pmid, name))

    return rows


def _write_pmf(pmf_path: Path, rows: list[tuple[str, str]]) -> None:
    with pmf_path.open("w", encoding="utf-8") as file_handle:
        for pmid, name in rows:
            file_handle.write(f"{pmid}\t{name}\n")


def _run_command(command: list[str], env: dict[str, str]) -> None:
    print("Running:")
    print(" ".join(command))
    completed = subprocess.run(command, env=env)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Warm up the first PMID with a headed browser, then batch the remaining PMIDs with the same profile."
    )
    parser.add_argument("-pmf", required=True, help="Input PMID file with one PMID per line or PMID/name pairs.")
    parser.add_argument(
        "-out",
        required=True,
        help="Batch output directory for the remaining PMIDs.",
    )
    parser.add_argument(
        "-errors",
        default="",
        help="Batch error file path. Default: <pmf_stem>_failed2.tsv beside the input file.",
    )
    parser.add_argument(
        "-tmpDir",
        default=str(DEFAULT_TMP_DIR),
        help="Project temporary directory. Default: <repo>/tmp.",
    )
    parser.add_argument(
        "-profileDir",
        default="",
        help="Playwright profile directory. Default: <tmpDir>/pw_pubmed_profile.",
    )
    parser.add_argument(
        "-warmupOut",
        default="",
        help="Warmup output directory. Default: <tmpDir>/pmid_out.",
    )
    parser.add_argument(
        "-warmupErrors",
        default="",
        help="Warmup error file path. Default: <tmpDir>/pmid_err.tsv.",
    )
    parser.add_argument(
        "-warmupChallengeWaitSec",
        type=int,
        default=240,
        help="Seconds to wait in headed mode for manual challenge solving during warmup.",
    )
    parser.add_argument(
        "-warmupBrowserTimeoutSec",
        type=int,
        default=120,
        help="Browser timeout in seconds for the warmup run.",
    )
    parser.add_argument(
        "-batchBrowserTimeoutSec",
        type=int,
        default=90,
        help="Browser timeout in seconds for the batch run.",
    )
    parser.add_argument(
        "--batch-headed",
        action="store_true",
        help="Also run the batch stage in headed mode.",
    )
    args = parser.parse_args()

    pmf_path = _resolve_path(args.pmf)
    if not pmf_path.exists():
        print(f"Input PMF not found: {pmf_path}", file=sys.stderr)
        return 1

    tmp_dir = _resolve_path(args.tmpDir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    profile_dir = _resolve_path(args.profileDir, tmp_dir) if args.profileDir else tmp_dir / "pw_pubmed_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    warmup_out = _resolve_path(args.warmupOut, tmp_dir) if args.warmupOut else tmp_dir / "pmid_out"
    warmup_out.mkdir(parents=True, exist_ok=True)

    warmup_errors = _resolve_path(args.warmupErrors, tmp_dir) if args.warmupErrors else tmp_dir / "pmid_err.tsv"
    warmup_errors.parent.mkdir(parents=True, exist_ok=True)

    batch_errors = _resolve_path(args.errors) if args.errors else (pmf_path.with_name(f"{pmf_path.stem}_failed2.tsv"))
    batch_errors.parent.mkdir(parents=True, exist_ok=True)

    rows = _load_pmf(pmf_path)
    if not rows:
        print(f"No PMID rows found in: {pmf_path}", file=sys.stderr)
        return 1

    warmup_pmid, warmup_name = rows[0]
    remaining_rows = rows[1:]

    env = os.environ.copy()
    env["TMPDIR"] = str(tmp_dir)
    env["TMP"] = str(tmp_dir)
    env["TEMP"] = str(tmp_dir)

    warmup_command = [
        sys.executable,
        str(FETCH_PDFS),
        "-pmids",
        warmup_pmid,
        "-errors",
        str(warmup_errors),
        "-out",
        str(warmup_out),
        "-browserHeaded",
        "-browserUserDataDir",
        str(profile_dir),
        "-manualChallengeWaitSec",
        str(args.warmupChallengeWaitSec),
        "-browserTimeoutSec",
        str(args.warmupBrowserTimeoutSec),
        "-tmpDir",
        str(tmp_dir),
    ]

    print(f"Warmup PMID: {warmup_pmid} ({warmup_name})")
    _run_command(warmup_command, env)

    if not remaining_rows:
        print("No remaining PMIDs after warmup; batch stage skipped.")
        return 0

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".tsv",
        prefix="batch_remaining_",
        dir=str(tmp_dir),
        delete=False,
    ) as handle:
        batch_pmf_path = Path(handle.name)

    try:
        _write_pmf(batch_pmf_path, remaining_rows)

        batch_command = [
            sys.executable,
            str(FETCH_PDFS),
            "-pmf",
            str(batch_pmf_path),
            "-errors",
            str(batch_errors),
            "-out",
            str(_resolve_path(args.out)),
            "-browserUserDataDir",
            str(profile_dir),
            "-browserTimeoutSec",
            str(args.batchBrowserTimeoutSec),
            "-tmpDir",
            str(tmp_dir),
        ]
        if args.batch_headed:
            batch_command.append("-browserHeaded")

        _run_command(batch_command, env)
    finally:
        try:
            batch_pmf_path.unlink()
        except FileNotFoundError:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())