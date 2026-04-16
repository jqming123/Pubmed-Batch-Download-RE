"""Wiley TDM API client for PubMed article PDF downloads."""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

from pmid_to_doi import pmid_to_doi
from wiley_tdm import TDMClient
from wiley_tdm.download_result import DownloadStatus

logger = logging.getLogger(__name__)


def get_wiley_tdm_client(api_token: Optional[str] = None) -> Optional[TDMClient]:
    """
    Initialize and return a Wiley TDM Client.
    
    Args:
        api_token: Wiley TDM API token. If None, reads from environment variable TDM_API_TOKEN.
    
    Returns:
        TDMClient instance if successful, None if token not found
    """
    # Try to get token from argument
    if api_token:
        try:
            return TDMClient(api_token=api_token)
        except Exception as e:
            logger.debug(f"Failed to initialize TDM Client with provided token: {e}")
            return None
    
    # Try environment variable
    if "TDM_API_TOKEN" in os.environ:
        try:
            return TDMClient()
        except Exception as e:
            logger.debug(f"Failed to initialize TDM Client from environment: {e}")
            return None
    
    logger.debug("TDM_API_TOKEN not found")
    return None


def _is_valid_pdf_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb") as handle:
        return handle.read(4) == b"%PDF"


def download_wiley_pdf_by_pmid(
    pmid: str,
    output_pdf_path: str,
    api_token: Optional[str] = None,
    timeout_sec: int = 40,
    user_agent: str = ""
) -> Tuple[bool, str, str, str]:
    """
    Download a PDF from Wiley using PMID (similar to Elsevier's download function).
    
    Args:
        pmid: PubMed ID
        output_pdf_path: Full path where to save the PDF (including filename and .pdf extension)
        api_token: Wiley TDM API token (uses environment variable if not provided)
        timeout_sec: Timeout for the request
        user_agent: User-Agent header value
    
    Returns:
        Tuple of (success: bool, reason: str, note: str, url: str)
        - success: True if downloaded successfully
        - reason: Empty string on success, error reason on failure
        - note: Additional details about the failure
        - url: URL used for the download attempt or error message
    """
    # Step 1: Convert PMID to DOI
    doi = pmid_to_doi(pmid)
    if not doi:
        return False, "NO_DOI_FOUND", f"Could not convert PMID {pmid} to DOI", ""
    
    # Step 2: Set up API token
    if api_token:
        os.environ["TDM_API_TOKEN"] = api_token
    
    # Step 3: Get TDM client
    client = get_wiley_tdm_client()
    if client is None:
        return False, "TDM_CLIENT_INIT_FAILED", "Could not initialize Wiley TDM Client", f"https://doi.org/{doi}"
    
    # Step 4: Download PDF
    try:
        logger.info(f"Downloading Wiley PDF for PMID {pmid} (DOI {doi})...")
        
        # Ensure output directory exists
        output_dir = os.path.dirname(output_pdf_path)
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        result = client.download_pdf(doi)
        status = result.status
        source_path = result.path

        if status in {DownloadStatus.SUCCESS, DownloadStatus.EXISTING_FILE} and source_path is not None:
            source_pdf = Path(source_path)
            if _is_valid_pdf_file(source_pdf):
                target_pdf = Path(output_pdf_path)
                if source_pdf.resolve() != target_pdf.resolve():
                    target_pdf.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(source_pdf, target_pdf)
                logger.info(f"Successfully downloaded PMID {pmid} via Wiley TDM")
                return True, "", "", f"https://doi.org/{doi}"

            note = f"Wiley reported {status.name} but no valid PDF was produced"
            logger.debug(f"PMID {pmid}: {note}")
            return False, "WILEY_TDM_DOWNLOAD_FAILED", note, f"https://doi.org/{doi}"

        note = result.comment or f"Wiley TDM status={status.name}"
        logger.debug(f"PMID {pmid}: Wiley TDM download failed - {note}")
        return False, "WILEY_TDM_DOWNLOAD_FAILED", note, f"https://doi.org/{doi}"
        
    except Exception as e:
        error_msg = str(e)
        logger.debug(f"PMID {pmid}: Wiley TDM download failed - {error_msg}")
        return False, "WILEY_TDM_DOWNLOAD_FAILED", error_msg, f"https://doi.org/{doi}"


def looks_like_wiley_article_source(url: str, html: str = "") -> bool:
    """
    Detect if URL is from Wiley Online Library.
    
    Args:
        url: URL to check
        html: HTML content to check
    
    Returns:
        True if URL appears to be from Wiley, False otherwise
    """
    lowered = f"{url}\n{html}".lower()
    markers = [
        "onlinelibrary.wiley.com",
        "wiley.com",
        "analyticalsciencejournals.onlinelibrary.wiley.com",
        "febs.onlinelibrary.wiley.com",
    ]
    return any(marker in lowered for marker in markers)


def setup_wiley_api_token(token_file: str) -> bool:
    """
    Load TDM API token from file and set environment variable.
    
    Args:
        token_file: Path to file containing the TDM API token
    
    Returns:
        True if token loaded successfully, False otherwise
    """
    if not os.path.exists(token_file):
        logger.debug(f"Token file not found: {token_file}")
        return False
    
    try:
        with open(token_file, "r", encoding="utf-8") as f:
            # Skip comments and empty lines
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    os.environ["TDM_API_TOKEN"] = line
                    logger.info("✓ Wiley TDM API token loaded from file")
                    return True
        
        logger.error("Token file is empty or contains only comments")
        return False
        
    except Exception as e:
        logger.error(f"Failed to read token file: {e}")
        return False


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    if len(sys.argv) > 1:
        # Test with provided PMID
        pmid = sys.argv[1]
        print(f"Testing PMID {pmid}...")
        doi = pmid_to_doi(pmid)
        if doi:
            print(f"✓ {pmid} -> {doi}")
        else:
            print(f"✗ Could not convert {pmid}")
    else:
        # Test with example
        print("Testing with example PMID...")
        doi = pmid_to_doi("14699080")
        if doi:
            print(f"✓ Example: 14699080 -> {doi}")
        else:
            print(f"✗ Failed example")
