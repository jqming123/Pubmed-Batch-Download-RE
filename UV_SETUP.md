# UV Environment Setup Notes

This document summarizes what was configured for this repository and how to use it.

## What Was Completed

1. Created a local virtual environment with uv at `.venv`.
2. Installed runtime dependencies required by `fetch_pdfs.py`:
   - requests
   - beautifulsoup4
   - lxml
3. Added project metadata and dependency declaration in `pyproject.toml`.
4. Added uv script-project setting:
   - `[tool.uv]`
   - `package = false`
5. Ran `uv sync` successfully and generated `uv.lock` for reproducibility.
6. Verified runtime works by running script help:
   - `uv run src/fetch_pdfs.py -h`

## Why `package = false` Is Set

This repository is a script-style project, not a Python package with an importable module directory.
Without `package = false`, `uv sync` may attempt editable build/install of the project itself and fail.

## Current Dependency Source of Truth

- `pyproject.toml`: declared dependencies and uv behavior.
- `uv.lock`: resolved, reproducible dependency lock.

## Daily Usage

Run directly with uv (recommended):

```bash
uv run src/fetch_pdfs.py -pmids 22673749,9685366
```

Use file input mode:

```bash
uv run src/fetch_pdfs.py -pmf example_pmf.tsv
```

Specify output and error files:

```bash
uv run src/fetch_pdfs.py -pmids 22673749,9685366 -out ./tmp/pubmed_debug_out -errors ./tmp/pubmed_debug_errors.tsv -maxRetries 1 -tmpDir ./tmp
```

## Recreate Environment on Another Machine

From the repository root:

```bash
uv sync
```

Then run the script:

```bash
uv run src/fetch_pdfs.py -h
```

## Optional: Activate the Local venv

If you prefer direct Python execution after activation:

```bash
source .venv/bin/activate
python src/fetch_pdfs.py -h
```

## Notes

- README mentions `requests3`, but current Python script imports and uses `requests`.
- Prefer `uv run ...` so commands always use the project-managed environment.