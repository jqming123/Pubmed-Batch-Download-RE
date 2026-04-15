# Pubmed-Batch-Download (Python)

Batch download article PDFs from PubMed IDs (PMIDs).

This repository currently focuses on the Python implementation under `src/`.
The `ruby_version/` directory is legacy and intentionally not covered in this README.

## Status

- Project name/version in `pyproject.toml`: `pubmed-batch-download` / `3.0.0`
- Python requirement: `>=3.9`
- Maintainer note: this project is community-maintained (PRs welcome)

## Features

- Download by `-pmids` (comma-separated) or `-pmf` (TSV/text input file)
- Skip already-downloaded PDFs in output directory
- Site-specific parsing rules + generic fallback logic
- Optional Playwright browser fallback for JS/challenge-heavy pages
- Failure summary (`-errors`) and detailed reason report (`-failureReport`)
- Configurable retries, timeouts, temporary directory, and request intervals
- Warmup workflow (`src/warmup_then_batch.py`) to solve challenge once and reuse browser profile

## Install

### Option A: `uv` (recommended)

```bash
uv sync
uv run playwright install chromium
```

### Option B: `pip`

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

### Option C: conda (legacy env files)

```bash
conda env create -f pubmed-batch-downloader-py3.yml
conda activate pubmed-batch-downloader-py3
```

If you use Windows, you can also try:

```bash
conda env create -f pubmed-batch-downloader-py3-windows.yml
```

## Main Usage

Run from repository root:

```bash
python src/fetch_pdfs.py [-pmids ... | -pmf ...] [other options]
```

You must provide exactly one of `-pmids` or `-pmf`.

### Input modes

1. `-pmids`

```bash
python src/fetch_pdfs.py -pmids 123,124,125
```

2. `-pmf`

```bash
python src/fetch_pdfs.py -pmf ./example_pmf.tsv
```

## `fetch_pdfs.py` Arguments

```text
-pmids                   Comma-separated PMID list (mutually exclusive with -pmf)
-pmf                     Input file: one PMID per line, or "PMID<TAB>name"
-out                     Output directory (default: fetched_pdfs)
-errors                  Failed PMID TSV output path (default: unfetched_pmids.tsv)
-failureReport           Detailed failure report TSV path
						 default: <errors_without_.tsv>.reasons.tsv (or <errors>.reasons.tsv)
-maxRetries              Max retries for network-style failures (default: 3)

-noBrowserFallback       Disable Playwright fallback (fallback is enabled by default)
-browserHeaded           Run Playwright in headed mode
-browserUserDataDir      Persistent Playwright user-data/profile directory
-manualChallengeWaitSec  In headed mode, wait seconds for manual challenge solving (default: 90)

-requestTimeoutSec       Requests timeout seconds (default: 40)
-browserTimeoutSec       Browser fallback timeout seconds (default: 45)

-tmpDir                  Temporary directory (default: <repo>/tmp)
-minIntervalSec          Min delay between PMIDs/retries (default: 1.0)
-maxIntervalSec          Max delay between PMIDs/retries (default: 3.0)
```

## Warmup + Batch Workflow

Use `src/warmup_then_batch.py` when a site challenge must be solved manually once:

```bash
python src/warmup_then_batch.py -pmf /path/to/input.tsv -out /path/to/output_dir
```

What it does:

1. Runs the first PMID in headed browser mode (warmup)
2. Reuses the same Playwright profile for remaining PMIDs
3. Uses project `tmp` directory by default for runtime artifacts

Wrapper options:

```text
-pmf                      Input PMID file (required)
-out                      Batch output directory (required)
-errors                   Batch errors path (default: <pmf_stem>_failed2.tsv)
-tmpDir                   Temporary directory (default: <repo>/tmp)
-profileDir               Playwright profile directory (default: <tmpDir>/pw_pubmed_profile)
-warmupOut                Warmup output directory (default: <tmpDir>/pmid_out)
-warmupErrors             Warmup error file (default: <tmpDir>/pmid_err.tsv)
-warmupChallengeWaitSec   Warmup manual wait seconds (default: 240)
-warmupBrowserTimeoutSec  Warmup browser timeout seconds (default: 120)
-batchBrowserTimeoutSec   Batch browser timeout seconds (default: 90)
--batch-headed            Run batch stage in headed mode too
```

## PMF File Format

One-column format:

```text
12345
23456
34567
```

Two-column format (`PMID<TAB>filename_without_pdf_suffix`):

```text
12345	Article_One
23456	Another_Paper
```

If a download fails, the `-errors` file is written in a PMF-compatible format so it can be retried directly in a later run.

## Output Files

- PDFs are saved to `-out` directory as `<name>.pdf`
- Failed summary TSV (default: `unfetched_pmids.tsv`)
- Detailed reasons TSV with columns:

```text
pmid	name	reason	url	note
```

Current reason categories include:

- `403_OR_CHALLENGE`
- `HTML_REDIRECT_ONLY`
- `NO_PDF_LINK_FOUND`
- `NETWORK_ERROR`

## Known Limitations

- Requests-only fetching cannot execute JavaScript.
- Some publisher flows still require Playwright fallback or manual challenge solving.
- Access to paywalled content depends on your own network/session/institutional permissions.
