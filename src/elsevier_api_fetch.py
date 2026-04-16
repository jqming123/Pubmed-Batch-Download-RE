"""Elsevier full-text PDF download helper for PubMed IDs."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import requests


ELSEVIER_API_URL = "https://api.elsevier.com/content/article/pubmed_id/{pubmed_id}"


def _read_api_key(api_key_file: str) -> str:
    path = Path(api_key_file).expanduser()
    if not path.is_absolute():
        path = path.resolve()

    if not path.exists():
        return ""

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line and not line.startswith("#"):
                return line

    return ""


def looks_like_elsevier_article_source(url: str, html: str = "") -> bool:
    lowered = f"{url}\n{html}".lower()
    markers = [
        "sciencedirect.com",
        "elsevier.com",
        "linkinghub.elsevier.com",
        "pdf.sciencedirectassets.com",
        "ars.els-cdn.com",
        "science direct",
    ]
    return any(marker in lowered for marker in markers)


def _is_pdf_response(response: requests.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return "application/pdf" in content_type or response.content.startswith(b"%PDF")


def download_elsevier_pdf_by_pubmed_id(
    pmid: str,
    output_pdf_path: str,
    api_key_file: str,
    timeout_sec: int = 40,
    user_agent: str = "",
) -> Tuple[bool, str, str, str]:
    """Download an Elsevier-hosted article PDF using the Elsevier API."""

    api_key = _read_api_key(api_key_file)
    if not api_key:
        return False, "NETWORK_ERROR", f"Elsevier API key file missing or empty: {api_key_file}", ""

    headers = {
        "Accept": "application/pdf",
        "X-ELS-APIKey": api_key,
    }
    if user_agent:
        headers["User-Agent"] = user_agent

    response = requests.get(
        ELSEVIER_API_URL.format(pubmed_id=pmid),
        headers=headers,
        params={"httpAccept": "application/pdf"},
        timeout=timeout_sec,
        allow_redirects=True,
    )

    if not _is_pdf_response(response):
        note = "Elsevier API returned {0} ({1})".format(response.status_code, response.url)
        return False, "NETWORK_ERROR", note, response.url

    output_path = Path(output_pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        handle.write(response.content)

    return True, "", "", response.url


def main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Download Elsevier full-text PDFs for PubMed IDs.")
    parser.add_argument("-pmid", default="", help="Single PubMed ID.")
    parser.add_argument("-pmids", default="", help="Comma-separated PubMed IDs.")
    parser.add_argument("-out", default="elsevier_pdfs", help="Output directory for PDF files.")
    parser.add_argument(
        "-apiKeyFile",
        default=str(Path(__file__).resolve().parent.parent / "elsevier_api_key.txt"),
        help="Path to the Elsevier API key file.",
    )
    parser.add_argument("-timeoutSec", type=int, default=40, help="Request timeout in seconds.")
    args = parser.parse_args()

    pmids = []
    if args.pmid:
        pmids.append(args.pmid.strip())
    if args.pmids:
        pmids.extend([item.strip() for item in args.pmids.split(",") if item.strip()])

    if not pmids:
        parser.print_help(sys.stderr)
        return 1

    output_dir = Path(args.out).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    any_failure = False
    for pmid in pmids:
        output_pdf_path = output_dir / f"{pmid}.pdf"
        saved, reason, note, final_url = download_elsevier_pdf_by_pubmed_id(
            pmid=pmid,
            output_pdf_path=str(output_pdf_path),
            api_key_file=args.apiKeyFile,
            timeout_sec=args.timeoutSec,
        )
        if saved:
            print(f"saved {pmid} -> {output_pdf_path} ({final_url})")
            continue

        any_failure = True
        print(f"failed {pmid}: {reason}; {note}; {final_url}", file=sys.stderr)

    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())