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
- Download order: PubMed prlinks -> Elsevier/Wiley API -> site-specific finders -> CORE API -> optional Playwright browser fallback
- Site-specific parsing rules + generic fallback logic
- Optional Playwright browser fallback for JS/challenge-heavy pages
- Failure summary (`-errors`) and detailed reason report (`-failureReport`)
- Configurable retries, timeouts, temporary directory, and request intervals
- Warmup workflow (`src/warmup_then_batch.py`) to solve challenge once and reuse browser profile
- Elsevier PubMed ID fast path via the Elsevier Full Text Retrieval API when an Elsevier/ScienceDirect source is detected
- Wiley PubMed ID fast path via Wiley TDM Client when a Wiley/Online Library source is detected

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

1. `-pmf`

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

-browserFallback         Enable Playwright fallback
-browserHeaded           Run Playwright in headed mode
-browserUserDataDir      Persistent Playwright user-data/profile directory
-manualChallengeWaitSec  In headed mode, wait seconds for manual challenge solving (default: 90)

-requestTimeoutSec       Requests timeout seconds (default: 40)
-browserTimeoutSec       Browser fallback timeout seconds (default: 45)

-tmpDir                  Temporary directory (default: <repo>/tmp)
-minIntervalSec          Min delay between PMIDs/retries (default: 1.0)
-maxIntervalSec          Max delay between PMIDs/retries (default: 3.0)
```

### Common Command Examples

**Basic usage with output directory:**

```bash
python src/fetch_pdfs.py -pmids 123456,234567,345678 -out ./pdfs
```

**Download from file with custom error reporting:**

```bash
python src/fetch_pdfs.py -pmf ./pmid_list.tsv -out ./pdfs -errors ./failed.tsv -failureReport ./failed_reasons.tsv
```

**Enable browser fallback with longer timeout for challenging sites:**

```bash
python src/fetch_pdfs.py -pmf ./pmid_list.tsv -out ./pdfs -browserFallback -browserTimeoutSec 60 -requestTimeoutSec 45
```

**Headed browser mode for manual challenge solving:**

```bash
python src/fetch_pdfs.py -pmids 123456 -out ./pdfs -browserHeaded -manualChallengeWaitSec 180
```

**Increase delays for slow networks:**

```bash
python src/fetch_pdfs.py -pmf ./pmid_list.tsv -out ./pdfs -minIntervalSec 2 -maxIntervalSec 5
```

**Enable browser fallback explicitly:**

```bash
python src/fetch_pdfs.py -pmf ./pmid_list.tsv -out ./pdfs -browserFallback
```

**Retry failed PMIDs from previous run:**

```bash
python src/fetch_pdfs.py -pmf ./failed.tsv -out ./pdfs_retry -errors ./failed_again.tsv
```

### Elsevier API key file

If you want Elsevier-hosted papers to be downloaded through the API, create a plain text file named `elsevier_api_key.txt` in the repository root and put your API key on the first non-empty line.

The main script reads this file automatically at startup. An example template is provided as `elsevier_api_key.txt.example`.

**Setup example:**

```bash
# Copy the template
cp elsevier_api_key.txt.example elsevier_api_key.txt

# Edit and add your API key (first non-empty line)
echo "your-actual-elsevier-api-key-here" > elsevier_api_key.txt

# Add to .gitignore to prevent accidental commits
echo "elsevier_api_key.txt" >> .gitignore
```

### CORE API key file

If you want the pipeline to try CORE API before browser fallback, create a plain text file named `core_api_key.txt` in the repository root and put your CORE API key on the first non-empty line.

The main script reads this file automatically when the CORE step is reached.

**Setup example:**

```bash
# Create CORE API key file
echo "your-actual-core-api-key-here" > core_api_key.txt

# Add to .gitignore to prevent accidental commits
echo "core_api_key.txt" >> .gitignore
```

### Wiley TDM API Token File

If you want to download papers from Wiley Online Library journals, create a plain text file named `wiley_tdm_token.txt` in the repository root and put your Wiley Text & Data Mining (TDM) API token on the first non-empty, non-comment line.

The main script reads this file automatically at startup. If the file is missing or empty, Wiley downloads are skipped and the script falls back to the existing finder/browser flow.

Suggested token flow:

1. Request a token at [Wiley text and data mining resources](https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining).
2. Save the token to `wiley_tdm_token.txt`.
3. Keep the token out of version control.

**Setup example:**

```bash
# Create token file with your Wiley TDM token
echo "your-actual-wiley-tdm-token-here" > wiley_tdm_token.txt

# Verify it's in .gitignore
echo "wiley_tdm_token.txt" >> .gitignore

# Test if token loads correctly (optional)
python -c "from wiley_api_fetch import setup_wiley_api_token; print('Token loaded' if setup_wiley_api_token('wiley_tdm_token.txt') else 'Token failed')"
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

**Typical workflow example:**

```bash
# Run warmup and batch with longer timeouts
python src/warmup_then_batch.py \
  -pmf ./my_pmids.tsv \
  -out ./output_pdfs \
  -warmupBrowserTimeoutSec 120 \
  -batchBrowserTimeoutSec 90

# Run batch in headed mode for debugging
python src/warmup_then_batch.py \
  -pmf ./my_pmids.tsv \
  -out ./output_pdfs \
  --batch-headed

# Use custom profile directory to reuse session across runs
python src/warmup_then_batch.py \
  -pmf ./my_pmids.tsv \
  -out ./output_pdfs \
  -profileDir ./persistent_browser_profile
```

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
12345\tArticle_One
23456\tAnother_Paper
```

If a download fails, the `-errors` file is written in a PMF-compatible format so it can be retried directly in a later run.

## Output Files

- PDFs are saved to `-out` directory as `<name>.pdf`
- Failed summary TSV (default: `unfetched_pmids.tsv`)
- Detailed reasons TSV with columns:

```text
pmid\tname\treason\turl\tnote
```

Current reason categories include:

- `403_OR_CHALLENGE`
- `HTML_REDIRECT_ONLY`
- `NO_PDF_LINK_FOUND`
- `NETWORK_ERROR`
- `WILEY_TDM_DOWNLOAD_FAILED`
- `TDM_CLIENT_INIT_FAILED`

Elsevier/Wiley API failures are reported through the same failure channels as other network/API errors, then the script falls back to the site-specific finders, CORE API, and browser fallback.

## Known Limitations

- Requests-only fetching cannot execute JavaScript.
- Some publisher flows still require Playwright fallback or manual challenge solving.
- Access to paywalled content depends on your own network/session/institutional permissions.

## Complete Workflow Examples

### Scenario 1: Download with API Keys

You have Elsevier and Wiley credentials and want to maximize API direct downloads:

```bash
# Setup credential files
echo "your-elsevier-key" > elsevier_api_key.txt
echo "your-wiley-token" > wiley_tdm_token.txt

# Download batch with fallback enabled
python src/fetch_pdfs.py \
  -pmf ./pmids.tsv \
  -out ./papers \
  -errors ./failed.tsv \
  -failureReport ./failed_reasons.tsv

# Check results
echo "Downloaded papers:"
ls -la ./papers/*.pdf | wc -l

echo "Failed PMIDs:"
head -20 ./failed_reasons.tsv
```

### Scenario 2: Handle Protected Sites with Warmup

A site requires solving a CAPTCHA or login once. Use warmup workflow:

```bash
# Prepare PMID file
cat > pmids.tsv << EOF
12345678
23456789
34567890
EOF

# Run warmup (you manually solve challenge) + batch (reuses session)
python src/warmup_then_batch.py \
  -pmf ./pmids.tsv \
  -out ./protected_site_pdfs \
  -warmupChallengeWaitSec 300 \
  -batchBrowserTimeoutSec 60

# Verify results
wc -l protected_site_pdfs_failed2.tsv
```

### Scenario 3: Slow Network with Retry

Network is unstable; use longer delays and increase retry attempts:

```bash
python src/fetch_pdfs.py \
  -pmf ./pmids.tsv \
  -out ./pdfs \
  -maxRetries 5 \
  -minIntervalSec 3 \
  -maxIntervalSec 8 \
  -requestTimeoutSec 60 \
  -browserTimeoutSec 90 \
  -errors ./failed.tsv

# Retry only the failed ones
python src/fetch_pdfs.py \
  -pmf ./failed.tsv \
  -out ./pdfs_retry \
  -errors ./failed2.tsv
```

### Scenario 4: Headless Mode with Debugging

Test a small batch visually in headed mode first, then run batch headless:

```bash
# Test with one PMID in headed mode
python src/fetch_pdfs.py \
  -pmids 12345678 \
  -out ./test \
  -browserHeaded \
  -manualChallengeWaitSec 120

# If successful, run full batch headless
python src/fetch_pdfs.py \
  -pmf ./pmids.tsv \
  -out ./pdfs \
  -browserFallback

# For sites that need browser, use headless with longer timeout
python src/fetch_pdfs.py \
  -pmf ./pmids.tsv \
  -out ./pdfs \
  -browserTimeoutSec 60 \
  -errors ./failed.tsv
```

### Scenario 5: Bulk Processing with Persistent Profile

Download large batches across multiple runs, reusing browser sessions:

```bash
# Create persistent profile directory
mkdir -p ./my_browser_profile

# First batch
python src/warmup_then_batch.py \
  -pmf ./batch1.tsv \
  -out ./batch1_pdfs \
  -profileDir ./my_browser_profile \
  -warmupChallengeWaitSec 240

# Later batches reuse the same profile (session already authenticated)
python src/warmup_then_batch.py \
  -pmf ./batch2.tsv \
  -out ./batch2_pdfs \
  -profileDir ./my_browser_profile \
  -warmupChallengeWaitSec 60

# Combine all downloaded PDFs
cat batch1_pdfs/*.pdf batch2_pdfs/*.pdf > combined.pdf
```
