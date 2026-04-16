"""Argument parsing and validation for fetch_pdfs script."""

from __future__ import annotations

import argparse
import sys


PMID_INPUT_SENTINEL = "%#$"


def _build_parser(default_tmp_dir: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser._optionals.title = "Flag Arguments"
    parser.add_argument(
        "-pmids",
        help="Comma separated list of pmids to fetch. Must include -pmids or -pmf.",
        default=PMID_INPUT_SENTINEL,
    )
    parser.add_argument(
        "-pmf",
        help=(
            "File with pmids to fetch inside, one pmid per line. Optionally, the file can be a tsv with a second column of names "
            "to save each pmid's article with (without '.pdf' at the end). Must include -pmids or -pmf"
        ),
        default=PMID_INPUT_SENTINEL,
    )
    parser.add_argument("-out", help="Output directory for fetched articles.  Default: fetched_pdfs", default="fetched_pdfs")
    parser.add_argument(
        "-errors",
        help="Output file path for pmids which failed to fetch.  Default: unfetched_pmids.tsv",
        default="unfetched_pmids.tsv",
    )
    parser.add_argument("-maxRetries", help="Change max number of retries per article on an error 104.  Default: 3", default=3, type=int)
    parser.add_argument(
        "-failureReport",
        help=(
            "Detailed TSV output for failed items with categorized reasons. "
            "Default: <errors>.reasons.tsv"
        ),
        default="",
    )
    parser.add_argument(
        "-noBrowserFallback",
        help="Disable Playwright browser fallback (enabled by default).",
        action="store_true",
    )
    parser.add_argument(
        "-browserHeaded",
        help="Run browser fallback in headed mode (for debugging).",
        action="store_true",
    )
    parser.add_argument(
        "-requestTimeoutSec",
        help="HTTP timeout in seconds for requests-based fetch steps. Default: 40",
        default=40,
        type=int,
    )
    parser.add_argument(
        "-browserTimeoutSec",
        help="Timeout in seconds for browser fallback operations. Default: 45",
        default=45,
        type=int,
    )
    parser.add_argument(
        "-browserUserDataDir",
        help=(
            "Persistent browser profile directory for Playwright fallback. "
            "Use this to reuse cookies/session after passing challenge pages. Default: empty (ephemeral)."
        ),
        default="",
    )
    parser.add_argument(
        "-manualChallengeWaitSec",
        help=(
            "When using -browserHeaded, wait this many seconds on challenge pages so you can solve them manually. "
            "Default: 90"
        ),
        default=90,
        type=int,
    )
    parser.add_argument(
        "-tmpDir",
        help=(
            "Temporary working directory used by this project and browser fallback runtime. "
            "Default: <repo>/tmp"
        ),
        default=default_tmp_dir,
    )
    parser.add_argument(
        "-minIntervalSec",
        help="Minimum delay (seconds) between PMID processing/retry attempts. Default: 1.0",
        default=1.0,
        type=float,
    )
    parser.add_argument(
        "-maxIntervalSec",
        help="Maximum delay (seconds) between PMID processing/retry attempts. Default: 3.0",
        default=3.0,
        type=float,
    )
    return parser


def parse_and_validate_args(default_tmp_dir: str, argv: list[str] | None = None) -> dict:
    parser = _build_parser(default_tmp_dir)
    arg_list = sys.argv[1:] if argv is None else argv

    if not arg_list:
        parser.print_help(sys.stderr)
        raise SystemExit(1)

    args = vars(parser.parse_args(arg_list))
    args["browserFallback"] = not args["noBrowserFallback"]

    if args["minIntervalSec"] < 0 or args["maxIntervalSec"] < 0:
        print("Error: -minIntervalSec and -maxIntervalSec must be non-negative.")
        raise SystemExit(1)
    if args["minIntervalSec"] > args["maxIntervalSec"]:
        print("Warning: -minIntervalSec > -maxIntervalSec, swapping values.")
        args["minIntervalSec"], args["maxIntervalSec"] = args["maxIntervalSec"], args["minIntervalSec"]

    if args["pmids"] == PMID_INPUT_SENTINEL and args["pmf"] == PMID_INPUT_SENTINEL:
        print("Error: Either -pmids or -pmf must be used.  Exiting.")
        raise SystemExit(1)
    if args["pmids"] != PMID_INPUT_SENTINEL and args["pmf"] != PMID_INPUT_SENTINEL:
        print("Error: -pmids and -pmf cannot be used together.  Ignoring -pmf argument")
        args["pmf"] = PMID_INPUT_SENTINEL

    return args