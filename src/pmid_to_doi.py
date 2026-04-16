"""Convert PubMed IDs (PMIDs) to DOIs using NCBI ID Converter API."""

import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

NCBI_IDCONV_API_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
NCBI_ESUMMARY_API_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
NCBI_TOOL_NAME = "pubmed-batch-downloader"
NCBI_EMAIL = "pubmed-batch-downloader@example.com"


def _normalize_doi(value: str) -> str:
    cleaned = value.strip()
    if cleaned.lower().startswith("doi:"):
        cleaned = cleaned[4:].strip()
    return cleaned


def _doi_from_esummary_record(record: dict) -> Optional[str]:
    article_ids = record.get("articleids", [])
    for article_id in article_ids:
        if str(article_id.get("idtype", "")).lower() != "doi":
            continue
        value = article_id.get("value")
        if isinstance(value, str) and value.strip():
            return _normalize_doi(value)
    return None


def pmid_to_doi(pmid: str, email: Optional[str] = None) -> Optional[str]:
    """
    Convert a single PMID to DOI using NCBI ID Converter API.
    
    Args:
        pmid: The PubMed ID (without 'PMID' prefix, just the number)
        email: Optional email to use for API requests. Uses default if not provided.
    
    Returns:
        The DOI string if found, None otherwise
    
    Example:
        >>> doi = pmid_to_doi("14699080")
        >>> print(doi)
        10.1084/jem.20020509
    """
    email = email or NCBI_EMAIL
    pmid_key = str(pmid)

    try:
        params = {
            "tool": NCBI_TOOL_NAME,
            "email": email,
            "ids": pmid_key,
            "format": "json",
        }
        response = requests.get(NCBI_IDCONV_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "ok":
            logger.warning(f"PMID {pmid_key}: API returned status '{data.get('status')}'")
        else:
            records = data.get("records", [])
            if not records:
                logger.warning(f"PMID {pmid_key}: No records found in API response")
            else:
                for record in records:
                    if str(record.get("pmid")) != pmid_key:
                        continue

                    doi = record.get("doi")
                    if isinstance(doi, str) and doi.strip():
                        normalized = _normalize_doi(doi)
                        logger.debug(f"PMID {pmid_key} -> DOI {normalized} (source=idconv)")
                        return normalized
                    logger.info(f"PMID {pmid_key}: DOI not found in idconv response, trying esummary fallback")
                    break

    except requests.RequestException as e:
        logger.error(f"PMID {pmid_key}: Failed to convert to DOI - {e}")
    except (ValueError, KeyError) as e:
        logger.error(f"PMID {pmid_key}: Failed to parse API response - {e}")

    try:
        params = {
            "db": "pubmed",
            "id": pmid_key,
            "retmode": "json",
            "tool": NCBI_TOOL_NAME,
            "email": email,
        }
        response = requests.get(NCBI_ESUMMARY_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        result = data.get("result", {})
        record = result.get(pmid_key, {})
        if not isinstance(record, dict) or not record:
            logger.warning(f"PMID {pmid_key}: No PubMed summary record found")
            return None

        doi = _doi_from_esummary_record(record)
        if doi:
            logger.debug(f"PMID {pmid_key} -> DOI {doi} (source=esummary)")
            return doi
        logger.warning(f"PMID {pmid_key}: DOI not found in esummary fallback")
    except requests.RequestException as e:
        logger.error(f"PMID {pmid_key}: ESummary fallback request failed - {e}")
    except (ValueError, KeyError) as e:
        logger.error(f"PMID {pmid_key}: ESummary fallback parse failed - {e}")

    return None


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    if len(sys.argv) > 1:
        # Single PMID: python pmid_to_doi.py 14699080
        pmid = sys.argv[1]
        doi = pmid_to_doi(pmid)
        if doi:
            print(f"PMID {pmid} -> DOI {doi}")
        else:
            print(f"Could not convert PMID {pmid}")
            sys.exit(1)
    else:
        # Test with example PMID
        test_pmid = "14699080"
        print(f"Testing with PMID {test_pmid}...")
        doi = pmid_to_doi(test_pmid)
        if doi:
            print(f"✓ Success: {test_pmid} -> {doi}")
        else:
            print(f"✗ Failed to convert {test_pmid}")
