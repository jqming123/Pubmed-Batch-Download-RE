"""
Integration guide for Wiley TDM Client into fetch_pdfs.py

This document explains how to integrate the Wiley TDM downloader into the main script.
"""

# STEP 1: Add imports at the top of fetch_pdfs.py
# Insert after existing imports:

from pmid_to_doi import pmid_to_doi
from wiley_fetch import download_wiley_pdf, setup_wiley_api_token, get_wiley_tdm_client


# STEP 2: Add constant and argument parser configuration

DEFAULT_WILEY_TDM_TOKEN_FILE = os.path.join(PROJECT_ROOT, "wiley_tdm_token.txt")

# Add to argument parser:
parser.add_argument(
    "-wileyTokenFile",
    help=(
        "Path to a text file that stores the Wiley TDM API token. "
        "Default: <repo>/wiley_tdm_token.txt"
    ),
    default=DEFAULT_WILEY_TDM_TOKEN_FILE,
)


# STEP 3: Add Wiley detection function

def looks_like_wiley_article_source(url: str, html: str = "") -> bool:
    """Detect if URL is from Wiley Online Library."""
    lowered = f"{url}\n{html}".lower()
    markers = [
        "onlinelibrary.wiley.com",
        "wiley.com",
        "analyticalsciencejournals.onlinelibrary.wiley.com",
        "febs.onlinelibrary.wiley.com",
    ]
    return any(marker in lowered for marker in markers)


# STEP 4: Modify the fetch() function to include Wiley handling

# In the fetch() function, after the Elsevier check, add:

    # Wiley TDM Client download
    if looks_like_wiley_article_source(response.url, response.text):
        print("** Detected Wiley source; trying Wiley TDM Client PDF download")
        
        # Convert PMID to DOI
        doi = pmid_to_doi(pmid)
        if doi:
            print(f"** Converted PMID {pmid} to DOI {doi}")
            
            wiley_saved = download_wiley_pdf(
                doi=doi,
                output_dir=args["out"]
            )
            
            if wiley_saved:
                print(f"** Fetching of reprint {pmid} succeeded via Wiley TDM")
                return True, "", "", f"https://doi.org/{doi}"
            else:
                failure_reason = _merge_reason(failure_reason, "WILEY_DOWNLOAD_FAILED")
                failure_note = "Wiley TDM download failed"
                # Continue to other finders if Wiley fails
        else:
            print(f"** Could not convert PMID {pmid} to DOI, skipping Wiley TDM")


# STEP 5: Initialize Wiley API token before main loop

# Add after the argument parsing but before the main processing loop:

# Load Wiley TDM token if file exists
wiley_token_loaded = setup_wiley_api_token(args["wileyTokenFile"])
if wiley_token_loaded:
    print(f"✓ Wiley TDM API token loaded from {args['wileyTokenFile']}")
else:
    print(f"⚠ Warning: Wiley TDM token not found. Wiley downloads will be unavailable.")
    print(f"  Token file: {args['wileyTokenFile']}")
    print(f"  To enable Wiley downloads:")
    print(f"    1. Request a token at: https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining")
    print(f"    2. Save it to: {args['wileyTokenFile']}")


# STEP 6: Update failure reason classification

# Add to REASON_PRIORITY dictionary:
REASON_PRIORITY = {
    REASON_403_OR_CHALLENGE: 4,
    REASON_NETWORK_ERROR: 3,
    REASON_HTML_REDIRECT_ONLY: 2,
    REASON_NO_PDF_LINK_FOUND: 1,
    "WILEY_DOWNLOAD_FAILED": 2,  # Add this line
}


# COMPLETE EXAMPLE MODIFICATION

def fetch_with_wiley(pmid, finders, name, headers):
    """
    Modified fetch() function with Wiley TDM Client support.
    
    This is a placeholder showing the complete integration.
    Copy the Wiley detection and download logic into the actual fetch() function
    right after the Elsevier section.
    """
    uri = (
        "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
        "?dbfrom=pubmed&id={0}&retmode=ref&cmd=prlinks"
    ).format(pmid)
    success = False
    skip_finders = False
    failure_reason = REASON_NO_PDF_LINK_FOUND
    failure_note = ""
    last_seen_url = uri

    if os.path.exists("{0}/{1}.pdf".format(args["out"], pmid)):
        print("** Reprint #{0} already downloaded and in folder; skipping.".format(pmid))
        return True, "", "", ""

    try:
        response = requests.get(uri, headers=headers, timeout=args["requestTimeoutSec"])
    except requests.RequestException as exc:
        return False, REASON_NETWORK_ERROR, str(exc), uri

    last_seen_url = response.url

    # Check Elsevier first
    if looks_like_elsevier_article_source(response.url, response.text):
        print("** Detected Elsevier/ScienceDirect source; trying Elsevier API PDF download")
        # ... [existing Elsevier code] ...

    # Check Wiley
    if not success and looks_like_wiley_article_source(response.url, response.text):
        print("** Detected Wiley source; trying Wiley TDM Client PDF download")
        doi = pmid_to_doi(pmid)
        
        if doi:
            print(f"** Converted PMID {pmid} to DOI {doi}")
            wiley_saved = download_wiley_pdf(
                doi=doi,
                output_dir=args["out"]
            )
            
            if wiley_saved:
                print(f"** Fetching of reprint {pmid} succeeded via Wiley TDM")
                return True, "", "", f"https://doi.org/{doi}"
            else:
                failure_reason = _merge_reason(failure_reason, REASON_NO_PDF_LINK_FOUND)
                failure_note = "Wiley TDM download unavailable"

    # Continue with other finders and browser fallback...
    # ... [existing code continues] ...
