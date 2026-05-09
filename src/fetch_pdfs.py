
"""Fetch PDFs for PubMed articles using site-specific finders."""

import os
import random
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, MutableMapping, Optional, TextIO

import requests
from bs4 import BeautifulSoup

from browser_fallback import run_browser_fallback_download
from check_pdf import is_pdf_by_magic_number, get_pdf_page_count
from fetch_cli_args import PMID_INPUT_SENTINEL, parse_and_validate_args
from core_download_by_pmid import download_pdf_for_pmid
from elsevier_api_fetch import download_elsevier_pdf_by_pubmed_id, looks_like_elsevier_article_source
from wiley_api_fetch import download_wiley_pdf_by_pmid, looks_like_wiley_article_source, setup_wiley_api_token


REASON_403_OR_CHALLENGE = "403_OR_CHALLENGE"
REASON_HTML_REDIRECT_ONLY = "HTML_REDIRECT_ONLY"
REASON_NO_PDF_LINK_FOUND = "NO_PDF_LINK_FOUND"
REASON_NETWORK_ERROR = "NETWORK_ERROR"
REASON_WILEY_TDM_DOWNLOAD_FAILED = "WILEY_TDM_DOWNLOAD_FAILED"
REASON_TDM_CLIENT_INIT_FAILED = "TDM_CLIENT_INIT_FAILED"
REASON_CORRUPTED_PDF = "CORRUPTED_PDF"
REASON_LOW_PAGE_COUNT = "LOW_PAGE_COUNT"

REASON_PRIORITY = {
    REASON_403_OR_CHALLENGE: 4,
    REASON_NETWORK_ERROR: 3,
    REASON_WILEY_TDM_DOWNLOAD_FAILED: 3,
    REASON_TDM_CLIENT_INIT_FAILED: 3,
    REASON_CORRUPTED_PDF: 3,
    REASON_HTML_REDIRECT_ONLY: 2,
    REASON_NO_PDF_LINK_FOUND: 1,
    REASON_LOW_PAGE_COUNT: 0,
}


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TMP_DIR = os.path.join(PROJECT_ROOT, "tmp")
DEFAULT_ELSEVIER_API_KEY_FILE = os.path.join(PROJECT_ROOT, "elsevier_api_key.txt")
DEFAULT_WILEY_TDM_TOKEN_FILE = os.path.join(PROJECT_ROOT, "wiley_tdm_token.txt")
DEFAULT_CORE_API_KEY_FILE = os.path.join(PROJECT_ROOT, "core_api_key.txt")


@dataclass(frozen=True)
class FetchConfig:
    pmids: str
    pmf: str
    out: str
    errors: str
    maxRetries: int
    failureReport: str
    browserFallback: bool
    browserHeaded: bool
    requestTimeoutSec: int
    browserTimeoutSec: int
    browserUserDataDir: str
    manualChallengeWaitSec: int
    tmpDir: str
    minIntervalSec: float
    maxIntervalSec: float


def _build_config(args: dict) -> FetchConfig:
    return FetchConfig(
        pmids=args["pmids"],
        pmf=args["pmf"],
        out=args["out"],
        errors=args["errors"],
        maxRetries=args["maxRetries"],
        failureReport=args["failureReport"],
        browserFallback=args["browserFallback"],
        browserHeaded=args["browserHeaded"],
        requestTimeoutSec=args["requestTimeoutSec"],
        browserTimeoutSec=args["browserTimeoutSec"],
        browserUserDataDir=args["browserUserDataDir"],
        manualChallengeWaitSec=args["manualChallengeWaitSec"],
        tmpDir=args["tmpDir"],
        minIntervalSec=args["minIntervalSec"],
        maxIntervalSec=args["maxIntervalSec"],
    )


def getMainUrl(url):
    return "/".join(url.split("/")[:3])


def _contains_challenge_marker(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "just a moment",
        "enable javascript",
        "captcha",
        "cf-chl",
        "cloudflare",
        "bot verification",
    ]
    return any(marker in lowered for marker in markers)


def _is_pdf_response(response: requests.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return response.url.lower().endswith(".pdf") or "application/pdf" in content_type


def _classify_response_failure(response: requests.Response) -> str:
    # 统一把失败原因分类，便于后续 failure report 排查。
    snippet = response.text[:8000].lower() if "text" in response.headers.get("content-type", "").lower() else ""
    if response.status_code == 403 or _contains_challenge_marker(snippet):
        return REASON_403_OR_CHALLENGE
    if "http-equiv=\"refresh\"" in snippet or "http-equiv=refresh" in snippet:
        return REASON_HTML_REDIRECT_ONLY
    return REASON_NO_PDF_LINK_FOUND


def _merge_reason(current: str, candidate: str) -> str:
    # 同一次 PMID 尝试里保留“更关键”的失败原因。
    if REASON_PRIORITY.get(candidate, 0) > REASON_PRIORITY.get(current, 0):
        return candidate
    return current


def savePdfFromUrl(pdfUrl, directory, name, headers, config: FetchConfig):
    response = requests.get(pdfUrl, headers=headers, allow_redirects=True, timeout=config.requestTimeoutSec)
    if not _is_pdf_response(response):
        reason = _classify_response_failure(response)
        note = "non-pdf response ({0}) from {1}".format(response.status_code, response.url)
        return False, reason, note, response.url

    with open("{0}/{1}.pdf".format(directory, name), "wb") as file_handle:
        file_handle.write(response.content)
    return True, "", "", response.url


def _tag_attr(tag: Any, attr: str) -> Optional[str]:
    getter = getattr(tag, "get", None)
    if getter is None:
        return None

    value = getter(attr)
    return value if isinstance(value, str) and value else None


def _try_publisher_api_download(pmid: str, name: str, response: requests.Response, headers, config: FetchConfig):
    output_pdf_path = "{0}/{1}.pdf".format(config.out, name)
    failure_reason = REASON_NO_PDF_LINK_FOUND
    failure_note = ""
    last_seen_url = response.url

    if looks_like_elsevier_article_source(response.url, response.text):
        print("Trying Elsevier API download")
        try:
            saved, reason, note, final_url = download_elsevier_pdf_by_pubmed_id(
                pmid=pmid,
                output_pdf_path=output_pdf_path,
                api_key_file=DEFAULT_ELSEVIER_API_KEY_FILE,
                timeout_sec=config.requestTimeoutSec,
                user_agent=headers["User-Agent"],
            )
        except requests.RequestException as exc:
            saved, reason, note, final_url = False, REASON_NETWORK_ERROR, str(exc), response.url

        if saved:
            print("** fetching of reprint {0} succeeded via Elsevier API".format(pmid))
            return True, "", "", final_url

        failure_reason = _merge_reason(failure_reason, reason)
        failure_note = note
        last_seen_url = final_url or last_seen_url

    if looks_like_wiley_article_source(response.url, response.text):
        print("Trying Wiley API download")
        try:
            saved, reason, note, final_url = download_wiley_pdf_by_pmid(
                pmid=pmid,
                output_pdf_path=output_pdf_path,
                timeout_sec=config.requestTimeoutSec,
                user_agent=headers["User-Agent"],
            )
        except requests.RequestException as exc:
            saved, reason, note, final_url = False, REASON_NETWORK_ERROR, str(exc), response.url

        if saved:
            print("** fetching of reprint {0} succeeded via Wiley API".format(pmid))
            return True, "", "", final_url

        if reason == "WILEY_TDM_DOWNLOAD_FAILED":
            reason = REASON_WILEY_TDM_DOWNLOAD_FAILED
        elif reason == "TDM_CLIENT_INIT_FAILED":
            reason = REASON_TDM_CLIENT_INIT_FAILED

        failure_reason = _merge_reason(failure_reason, reason)
        failure_note = note
        last_seen_url = final_url or last_seen_url

    return False, failure_reason, failure_note, last_seen_url


def _try_core_api_download(pmid: str, name: str, config: FetchConfig):
    output_pdf_path = "{0}/{1}.pdf".format(config.out, name)
    if not os.path.exists(DEFAULT_CORE_API_KEY_FILE):
        return False, REASON_NO_PDF_LINK_FOUND, "core api key file not found: {0}".format(DEFAULT_CORE_API_KEY_FILE), ""

    print("Trying CORE API download")
    try:
        saved, reason, note, final_url = download_pdf_for_pmid(
            pmid=pmid,
            output_pdf_path=output_pdf_path,
            api_key_file=DEFAULT_CORE_API_KEY_FILE,
            timeout_sec=config.requestTimeoutSec,
            max_retries=config.maxRetries,
            retry_base_sec=1.5,
            delay_min_sec=config.minIntervalSec,
            delay_max_sec=config.maxIntervalSec,
        )
    except Exception as exc:  # noqa: BLE001
        return False, REASON_NETWORK_ERROR, str(exc), ""

    if saved:
        print("** fetching of reprint {0} succeeded via CORE API".format(pmid))
        return True, "", "", final_url

    return False, reason, note, final_url


def fetch(pmid, finders, name, headers, config: FetchConfig):
    # 先通过 PubMed 的 prlinks 拿到出版商落地页，再逐个 finder 解析 PDF 线索。
    uri = (
        "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
        "?dbfrom=pubmed&id={0}&retmode=ref&cmd=prlinks"
    ).format(pmid)
    success = False
    skip_finders = False
    failure_reason = REASON_NO_PDF_LINK_FOUND
    failure_note = ""
    last_seen_url = uri

    if os.path.exists("{0}/{1}.pdf".format(config.out, pmid)):
        print("** Reprint #{0} already downloaded and in folder; skipping.".format(pmid))
        return True, "", "", ""

    try:
        response = requests.get(uri, headers=headers, timeout=config.requestTimeoutSec)
    except requests.RequestException as exc:
        return False, REASON_NETWORK_ERROR, str(exc), uri

    last_seen_url = response.url
    failure_reason = _merge_reason(failure_reason, _classify_response_failure(response))

    api_success, api_reason, api_note, api_url = _try_publisher_api_download(pmid, name, response, headers, config)
    if api_success:
        return True, "", "", api_url
    failure_reason = _merge_reason(failure_reason, api_reason)
    failure_note = api_note
    last_seen_url = api_url or last_seen_url

    if "ovid" in response.url:
        print(
            " ** Reprint {0} cannot be fetched as ovid is not supported by the requests package.".format(pmid)
        )
        skip_finders = True
        failure_reason = REASON_NO_PDF_LINK_FOUND
        failure_note = "ovid not supported"

    soup = BeautifulSoup(response.content, "lxml")

    if not skip_finders:
        # requests 路径：按站点规则快速尝试，不成功再走浏览器兜底。
        for finder_name, finder in finders.items():
            print("Trying {0}".format(finder_name))
            pdfUrl = finder(response, soup, headers, config)
            if pdfUrl is not None:
                try:
                    saved, reason, note, final_url = savePdfFromUrl(pdfUrl, config.out, name, headers, config)
                except requests.RequestException as exc:
                    saved, reason, note, final_url = False, REASON_NETWORK_ERROR, str(exc), pdfUrl

                if saved:
                    success = True
                    print("** fetching of reprint {0} succeeded".format(pmid))
                    break

                failure_reason = _merge_reason(failure_reason, reason)
                failure_note = note
                last_seen_url = final_url or pdfUrl

    if not success:
        core_success, core_reason, core_note, core_url = _try_core_api_download(pmid, name, config)
        if core_success:
            success = True
            failure_reason = ""
            failure_note = ""
            last_seen_url = core_url or last_seen_url
        else:
            failure_reason = _merge_reason(failure_reason, core_reason)
            failure_note = core_note
            last_seen_url = core_url or last_seen_url

    if not success and config.browserFallback:
        # 浏览器兜底用于处理 JS 渲染、挑战页和复杂跳转。
        print("Trying browser fallback via Playwright")
        browser_success, reason, note, final_url = run_browser_fallback_download(
            start_url=response.url,
            output_pdf_path="{0}/{1}.pdf".format(config.out, name),
            browser_timeout_sec=config.browserTimeoutSec,
            browser_headed=config.browserHeaded,
            user_agent=headers["User-Agent"],
            browser_user_data_dir=config.browserUserDataDir,
            manual_challenge_wait_sec=config.manualChallengeWaitSec,
            tmp_dir=config.tmpDir,
        )
        if browser_success:
            print("** fetching of reprint {0} succeeded with browser fallback".format(pmid))
            success = True
        else:
            failure_reason = _merge_reason(failure_reason, reason)
            failure_note = note
            last_seen_url = final_url or last_seen_url

    if not success:
        print(
            "** Reprint {0} could not be fetched. reason={1}; url={2}".format(
                pmid,
                failure_reason,
                last_seen_url,
            )
        )

    return success, failure_reason, failure_note, last_seen_url


def _write_failure_entry(
    error_pmids: TextIO,
    failure_report: TextIO,
    pmid: str,
    name: str,
    reason: str,
    url: str,
    note: str,
):
    # errors 文件保留简表；failure report 保留可审计明细。
    error_pmids.write("{}\t{}\n".format(pmid, name))
    failure_report.write("{}\t{}\t{}\t{}\t{}\n".format(pmid, name, reason, url, note.replace("\t", " ")))


def _sleep_with_jitter(context: str, config: FetchConfig):
    delay = random.uniform(config.minIntervalSec, config.maxIntervalSec)
    if delay <= 0:
        return
    print("** sleeping {0:.2f}s before {1}".format(delay, context))
    time.sleep(delay)


def _resolve_failure_report_path(errors_path: str, failure_report: str) -> str:
    if failure_report:
        return failure_report

    errors_root, errors_ext = os.path.splitext(errors_path)
    if errors_ext.lower() == ".tsv" and errors_root:
        return "{0}.reasons.tsv".format(errors_root)
    return "{0}.reasons.tsv".format(errors_path)


def _post_download_validate_pdf(name: str, config: FetchConfig):
    pdf_filename = "{0}.pdf".format(name)
    pdf_path = os.path.join(config.out, pdf_filename)

    if not os.path.exists(pdf_path):
        return False, REASON_CORRUPTED_PDF, "download marked successful but file missing"

    try:
        with open(pdf_path, "rb") as pdf_file:
            file_header = pdf_file.read(8)
    except OSError as exc:
        return False, REASON_CORRUPTED_PDF, "failed to read pdf: {0}".format(exc)

    if not is_pdf_by_magic_number(file_header):
        try:
            os.remove(pdf_path)
        except OSError as exc:
            return False, REASON_CORRUPTED_PDF, "invalid pdf magic; failed to remove file: {0}".format(exc)
        return False, REASON_CORRUPTED_PDF, "invalid pdf magic number; file removed"

    page_count = get_pdf_page_count(pdf_path)
    if page_count is None:
        try:
            os.remove(pdf_path)
        except OSError as exc:
            return False, REASON_CORRUPTED_PDF, "unreadable pdf; failed to remove file: {0}".format(exc)
        return False, REASON_CORRUPTED_PDF, "unreadable pdf; file removed"

    if page_count < 4:
        need_check_dir = os.path.join(config.out, "need_check")
        os.makedirs(need_check_dir, exist_ok=True)
        moved_path = os.path.join(need_check_dir, pdf_filename)
        os.replace(pdf_path, moved_path)
        return True, REASON_LOW_PAGE_COUNT, "low page count: {0} pages; moved to {1}".format(page_count, moved_path)

    return True, "", ""


def acsPublications(req, soup, headers, config: FetchConfig):
    possibleLinks = [
        x
        for x in soup.find_all("a")
        if isinstance(x.get("title"), str)
        and ("high-res pdf" in x.get("title").lower() or "low-res pdf" in x.get("title").lower())
    ]

    if possibleLinks:
        print("** fetching reprint using the 'acsPublications' finder...")
        return getMainUrl(req.url) + possibleLinks[0].get("href")

    return None


def direct_pdf_link(req, soup, headers, config: FetchConfig):
    if _is_pdf_response(req):
        print("** fetching reprint using the 'direct pdf link' finder...")
        return req.url

    return None


def futureMedicine(req, soup, headers, config: FetchConfig):
    possibleLinks = soup.find_all("a", attrs={"href": re.compile("/doi/pdf")})
    if possibleLinks:
        print("** fetching reprint using the 'future medicine' finder...")
        return getMainUrl(req.url) + possibleLinks[0].get("href")
    return None


def genericCitationLabelled(req, soup, headers, config: FetchConfig):
    possibleLinks = soup.find_all("meta", attrs={"name": "citation_pdf_url"})
    if possibleLinks:
        print("** fetching reprint using the 'generic citation labelled' finder...")
        return possibleLinks[0].get("content")
    return None


def nejm(req, soup, headers, config: FetchConfig):
    possibleLinks = [
        x
        for x in soup.find_all("a")
        if isinstance(x.get("data-download-type"), str)
        and x.get("data-download-type").lower() == "article pdf"
    ]

    if possibleLinks:
        print("** fetching reprint using the 'NEJM' finder...")
        return getMainUrl(req.url) + possibleLinks[0].get("href")

    return None


def pubmed_central_v2(req, soup, headers, config: FetchConfig):
    possibleLinks = soup.find_all("a", attrs={"href": re.compile("/pmc/articles")})

    if possibleLinks:
        print("** fetching reprint using the 'pubmed central' finder...")
        return "https://www.ncbi.nlm.nih.gov/{}".format(possibleLinks[0].get("href"))

    return None


def science_direct(req, soup, headers, config: FetchConfig):
    input_tags = soup.find_all("input")
    if not input_tags:
        return None

    new_uri = _tag_attr(input_tags[0], "value")
    if not new_uri:
        return None

    response = requests.get(
        urllib.parse.unquote(new_uri),
        allow_redirects=True,
        headers=headers,
        timeout=config.requestTimeoutSec,
    )
    soup = BeautifulSoup(response.content, "lxml")

    possibleLinks = soup.find_all("meta", attrs={"name": "citation_pdf_url"})
    if not possibleLinks:
        return None

    citation_pdf_url = _tag_attr(possibleLinks[0], "content")
    if not citation_pdf_url:
        return None

    print("** fetching reprint using the 'science_direct' finder...")
    response = requests.get(citation_pdf_url, headers=headers, timeout=config.requestTimeoutSec)
    soup = BeautifulSoup(response.content, "lxml")

    pdf_link = soup.find("a", href=True)
    href = _tag_attr(pdf_link, "href")
    if href:
        return urllib.parse.urljoin(response.url, href)

    return None


def uchicagoPress(req, soup, headers, config: FetchConfig):
    possibleLinks = [
        x
        for x in soup.find_all("a")
        if isinstance(x.get("href"), str) and "pdf" in x.get("href") and ".edu/doi/" in x.get("href")
    ]
    if possibleLinks:
        print("** fetching reprint using the 'uchicagoPress' finder...")
        return getMainUrl(req.url) + possibleLinks[0].get("href")

    return None


FINDER_REGISTRY = {
    # 优先低成本命中率高的规则，最后才尝试直链判断。
    "genericCitationLabelled": genericCitationLabelled,
    "pubmed_central_v2": pubmed_central_v2,
    "acsPublications": acsPublications,
    "uchicagoPress": uchicagoPress,
    "nejm": nejm,
    "futureMedicine": futureMedicine,
    "science_direct": science_direct,
    "direct_pdf_link": direct_pdf_link,
}


def _build_default_headers() -> MutableMapping[str, str]:
    headers = requests.utils.default_headers()
    headers["User-Agent"] = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36"
    )
    return headers


def main() -> None:
    args = parse_and_validate_args(DEFAULT_TMP_DIR)
    config = _build_config(args)

    os.makedirs(config.tmpDir, exist_ok=True)
    # Force all tempfile-like runtime behavior to use the project tmp directory.
    os.environ["TMPDIR"] = config.tmpDir
    os.environ["TMP"] = config.tmpDir
    os.environ["TEMP"] = config.tmpDir
    setup_wiley_api_token(DEFAULT_WILEY_TDM_TOKEN_FILE)

    if not os.path.exists(config.out):
        print("Output directory of {0} did not exist.  Created the directory.".format(config.out))
        os.mkdir(config.out)

    headers = _build_default_headers()
    failure_report_path = _resolve_failure_report_path(config.errors, config.failureReport)

    if config.pmids != PMID_INPUT_SENTINEL:
        pmids = config.pmids.split(",")
        names = pmids
    else:
        pmids = [line.strip().split() for line in open(config.pmf)]
        if len(pmids[0]) == 1:
            pmids = [x[0] for x in pmids]
            names = pmids
        else:
            names = [x[1] for x in pmids]
            pmids = [x[0] for x in pmids]

    with open(config.errors, "w+") as errorPmids:
        with open(failure_report_path, "w+") as failureReport:
            failureReport.write("pmid\tname\treason\turl\tnote\n")

            for pmid, name in zip(pmids, names):
                print("Trying to fetch pmid {0}".format(pmid))
                retriesSoFar = 0
                while retriesSoFar < config.maxRetries:
                    try:
                        success, reason, note, url = fetch(pmid, FINDER_REGISTRY, name, headers, config)
                        if success:
                            # 下载结束后统一做 PDF 完整性和页数检查。
                            post_success, post_reason, post_note = _post_download_validate_pdf(name, config)
                            if not post_success:
                                print(
                                    "** Reprint {0} downloaded but removed after validation: {1}".format(
                                        pmid,
                                        post_note,
                                    )
                                )
                                _write_failure_entry(errorPmids, failureReport, pmid, name, post_reason, url, post_note)
                            elif post_reason == REASON_LOW_PAGE_COUNT:
                                print(
                                    "** Reprint {0} downloaded but flagged for review (low page count): {1}".format(
                                        pmid,
                                        post_note,
                                    )
                                )
                                _write_failure_entry(errorPmids, failureReport, pmid, name, post_reason, url, post_note)
                            retriesSoFar = config.maxRetries
                            break

                        if reason == REASON_NETWORK_ERROR and retriesSoFar + 1 < config.maxRetries:
                            retriesSoFar += 1
                            print("** fetching of reprint {0} failed from network error {1}, retrying".format(pmid, note))
                            _sleep_with_jitter("retry attempt", config)
                            continue

                        _write_failure_entry(errorPmids, failureReport, pmid, name, reason, url, note)
                        retriesSoFar = config.maxRetries
                    except requests.ConnectionError as e:
                        if "104" in str(e) or "BadStatusLine" in str(e):
                            retriesSoFar += 1
                            if retriesSoFar < config.maxRetries:
                                print("** fetching of reprint {0} failed from error {1}, retrying".format(pmid, e))
                                _sleep_with_jitter("retry attempt", config)
                            else:
                                print("** fetching of reprint {0} failed from error {1}".format(pmid, e))
                                _write_failure_entry(
                                    errorPmids,
                                    failureReport,
                                    pmid,
                                    name,
                                    REASON_NETWORK_ERROR,
                                    "",
                                    str(e),
                                )
                        else:
                            print("** fetching of reprint {0} failed from error {1}".format(pmid, e))
                            retriesSoFar = config.maxRetries
                            _write_failure_entry(
                                errorPmids,
                                failureReport,
                                pmid,
                                name,
                                REASON_NETWORK_ERROR,
                                "",
                                str(e),
                            )
                    except Exception as e:
                        print("** fetching of reprint {0} failed from error {1}".format(pmid, e))
                        retriesSoFar = config.maxRetries
                        _write_failure_entry(
                            errorPmids,
                            failureReport,
                            pmid,
                            name,
                            REASON_NETWORK_ERROR,
                            "",
                            str(e),
                        )

                _sleep_with_jitter("next pmid", config)


if __name__ == "__main__":
    main()


