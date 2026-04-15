
"""Fetch PDFs for PubMed articles using site-specific finders."""

import argparse
import os
import random
import re
import sys
import time
import urllib.parse
from typing import Any, Optional, TextIO

import requests
from bs4 import BeautifulSoup

from browser_fetch import try_download_pdf_with_playwright


REASON_403_OR_CHALLENGE = "403_OR_CHALLENGE"
REASON_HTML_REDIRECT_ONLY = "HTML_REDIRECT_ONLY"
REASON_NO_PDF_LINK_FOUND = "NO_PDF_LINK_FOUND"
REASON_NETWORK_ERROR = "NETWORK_ERROR"

REASON_PRIORITY = {
    REASON_403_OR_CHALLENGE: 4,
    REASON_NETWORK_ERROR: 3,
    REASON_HTML_REDIRECT_ONLY: 2,
    REASON_NO_PDF_LINK_FOUND: 1,
}


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TMP_DIR = os.path.join(PROJECT_ROOT, "tmp")


parser = argparse.ArgumentParser()
parser._optionals.title = "Flag Arguments"
# 两种输入方式二选一：直接传 PMID 列表，或从文件批量读取。
parser.add_argument(
    "-pmids",
    help="Comma separated list of pmids to fetch. Must include -pmids or -pmf.",
    default="%#$",
)
parser.add_argument(
    "-pmf",
    help=(
        "File with pmids to fetch inside, one pmid per line. Optionally, the file can be a tsv with a second column of names "
        "to save each pmid's article with (without '.pdf' at the end). Must include -pmids or -pmf"
    ),
    default="%#$",
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
    default=DEFAULT_TMP_DIR,
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
args = vars(parser.parse_args())
args["browserFallback"] = not args["noBrowserFallback"]

if args["minIntervalSec"] < 0 or args["maxIntervalSec"] < 0:
    print("Error: -minIntervalSec and -maxIntervalSec must be non-negative.")
    sys.exit(1)
if args["minIntervalSec"] > args["maxIntervalSec"]:
    print("Warning: -minIntervalSec > -maxIntervalSec, swapping values.")
    args["minIntervalSec"], args["maxIntervalSec"] = args["maxIntervalSec"], args["minIntervalSec"]

os.makedirs(args["tmpDir"], exist_ok=True)
# Force all tempfile-like runtime behavior to use the project tmp directory.
os.environ["TMPDIR"] = args["tmpDir"]
os.environ["TMP"] = args["tmpDir"]
os.environ["TEMP"] = args["tmpDir"]


if len(sys.argv) == 1:
    parser.print_help(sys.stderr)
    sys.exit(1)
if args["pmids"] == "%#$" and args["pmf"] == "%#$":
    print("Error: Either -pmids or -pmf must be used.  Exiting.")
    sys.exit(1)
if args["pmids"] != "%#$" and args["pmf"] != "%#$":
    print("Error: -pmids and -pmf cannot be used together.  Ignoring -pmf argument")
    args["pmf"] = "%#$"


if not os.path.exists(args["out"]):
    print("Output directory of {0} did not exist.  Created the directory.".format(args["out"]))
    os.mkdir(args["out"])


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
    return (
        response.url.lower().endswith(".pdf")
        or "application/pdf" in content_type
        or response.content.startswith(b"%PDF")
    )


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


def savePdfFromUrl(pdfUrl, directory, name, headers):
    response = requests.get(pdfUrl, headers=headers, allow_redirects=True, timeout=args["requestTimeoutSec"])
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


def fetch(pmid, finders, name, headers):
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

    if os.path.exists("{0}/{1}.pdf".format(args["out"], pmid)):
        print("** Reprint #{0} already downloaded and in folder; skipping.".format(pmid))
        return True, "", "", ""

    try:
        response = requests.get(uri, headers=headers, timeout=args["requestTimeoutSec"])
    except requests.RequestException as exc:
        return False, REASON_NETWORK_ERROR, str(exc), uri

    last_seen_url = response.url
    failure_reason = _merge_reason(failure_reason, _classify_response_failure(response))

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
        for finder in finders:
            print("Trying {0}".format(finder))
            pdfUrl = globals()[finder](response, soup, headers)
            if pdfUrl is not None:
                try:
                    saved, reason, note, final_url = savePdfFromUrl(pdfUrl, args["out"], name, headers)
                except requests.RequestException as exc:
                    saved, reason, note, final_url = False, REASON_NETWORK_ERROR, str(exc), pdfUrl

                if saved:
                    success = True
                    print("** fetching of reprint {0} succeeded".format(pmid))
                    break

                failure_reason = _merge_reason(failure_reason, reason)
                failure_note = note
                last_seen_url = final_url or pdfUrl

    if not success and args["browserFallback"]:
        # 浏览器兜底用于处理 JS 渲染、挑战页和复杂跳转。
        print("Trying browser fallback via Playwright")
        browser_success, reason, note, final_url = try_download_pdf_with_playwright(
            start_url=response.url,
            output_pdf_path="{0}/{1}.pdf".format(args["out"], name),
            timeout_ms=args["browserTimeoutSec"] * 1000,
            headless=not args["browserHeaded"],
            user_agent=headers["User-Agent"],
            user_data_dir=args["browserUserDataDir"],
            manual_challenge_wait_sec=args["manualChallengeWaitSec"],
            temp_dir=args["tmpDir"],
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


def _sleep_with_jitter(context: str):
    delay = random.uniform(args["minIntervalSec"], args["maxIntervalSec"])
    if delay <= 0:
        return
    print("** sleeping {0:.2f}s before {1}".format(delay, context))
    time.sleep(delay)


def acsPublications(req, soup, headers):
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


def direct_pdf_link(req, soup, headers):
    if _is_pdf_response(req):
        print("** fetching reprint using the 'direct pdf link' finder...")
        return req.url

    return None


def futureMedicine(req, soup, headers):
    possibleLinks = soup.find_all("a", attrs={"href": re.compile("/doi/pdf")})
    if possibleLinks:
        print("** fetching reprint using the 'future medicine' finder...")
        return getMainUrl(req.url) + possibleLinks[0].get("href")
    return None


def genericCitationLabelled(req, soup, headers):
    possibleLinks = soup.find_all("meta", attrs={"name": "citation_pdf_url"})
    if possibleLinks:
        print("** fetching reprint using the 'generic citation labelled' finder...")
        return possibleLinks[0].get("content")
    return None


def nejm(req, soup, headers):
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


def pubmed_central_v1(req, soup, headers):
    possibleLinks = soup.find_all("a", re.compile("pdf"))
    possibleLinks = [
        x for x in possibleLinks if isinstance(x.get("title"), str) and "epdf" not in x.get("title").lower()
    ]

    if possibleLinks:
        print("** fetching reprint using the 'pubmed central' finder...")
        return getMainUrl(req.url) + possibleLinks[0].get("href")

    return None


def pubmed_central_v2(req, soup, headers):
    possibleLinks = soup.find_all("a", attrs={"href": re.compile("/pmc/articles")})

    if possibleLinks:
        print("** fetching reprint using the 'pubmed central' finder...")
        return "https://www.ncbi.nlm.nih.gov/{}".format(possibleLinks[0].get("href"))

    return None


def science_direct(req, soup, headers):
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
        timeout=args["requestTimeoutSec"],
    )
    soup = BeautifulSoup(response.content, "lxml")

    possibleLinks = soup.find_all("meta", attrs={"name": "citation_pdf_url"})
    if not possibleLinks:
        return None

    citation_pdf_url = _tag_attr(possibleLinks[0], "content")
    if not citation_pdf_url:
        return None

    print("** fetching reprint using the 'science_direct' finder...")
    response = requests.get(citation_pdf_url, headers=headers, timeout=args["requestTimeoutSec"])
    soup = BeautifulSoup(response.content, "lxml")

    pdf_link = soup.find("a", href=True)
    href = _tag_attr(pdf_link, "href")
    if href:
        return urllib.parse.urljoin(response.url, href)

    return None


def uchicagoPress(req, soup, headers):
    possibleLinks = [
        x
        for x in soup.find_all("a")
        if isinstance(x.get("href"), str) and "pdf" in x.get("href") and ".edu/doi/" in x.get("href")
    ]
    if possibleLinks:
        print("** fetching reprint using the 'uchicagoPress' finder...")
        return getMainUrl(req.url) + possibleLinks[0].get("href")

    return None


finders = [
    # 优先低成本命中率高的规则，最后才尝试直链判断。
    "genericCitationLabelled",
    "pubmed_central_v2",
    "acsPublications",
    "uchicagoPress",
    "nejm",
    "futureMedicine",
    "science_direct",
    "direct_pdf_link",
]


headers = requests.utils.default_headers()
headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36"

if args["failureReport"]:
    failure_report_path = args["failureReport"]
else:
    errors_root, errors_ext = os.path.splitext(args["errors"])
    if errors_ext.lower() == ".tsv" and errors_root:
        failure_report_path = "{0}.reasons.tsv".format(errors_root)
    else:
        failure_report_path = "{0}.reasons.tsv".format(args["errors"])

if args["pmids"] != "%#$":
    pmids = args["pmids"].split(",")
    names = pmids
else:
    pmids = [line.strip().split() for line in open(args["pmf"])]
    if len(pmids[0]) == 1:
        pmids = [x[0] for x in pmids]
        names = pmids
    else:
        names = [x[1] for x in pmids]
        pmids = [x[0] for x in pmids]

with open(args["errors"], "w+") as errorPmids:
    with open(failure_report_path, "w+") as failureReport:
        failureReport.write("pmid\tname\treason\turl\tnote\n")

        for pmid, name in zip(pmids, names):
            print("Trying to fetch pmid {0}".format(pmid))
            retriesSoFar = 0
            while retriesSoFar < args["maxRetries"]:
                try:
                    success, reason, note, url = fetch(pmid, finders, name, headers)
                    if success:
                        retriesSoFar = args["maxRetries"]
                        break

                    if reason == REASON_NETWORK_ERROR and retriesSoFar + 1 < args["maxRetries"]:
                        retriesSoFar += 1
                        print("** fetching of reprint {0} failed from network error {1}, retrying".format(pmid, note))
                        _sleep_with_jitter("retry attempt")
                        continue

                    _write_failure_entry(errorPmids, failureReport, pmid, name, reason, url, note)
                    retriesSoFar = args["maxRetries"]
                except requests.ConnectionError as e:
                    if "104" in str(e) or "BadStatusLine" in str(e):
                        retriesSoFar += 1
                        if retriesSoFar < args["maxRetries"]:
                            print("** fetching of reprint {0} failed from error {1}, retrying".format(pmid, e))
                            _sleep_with_jitter("retry attempt")
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
                        retriesSoFar = args["maxRetries"]
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
                    retriesSoFar = args["maxRetries"]
                    _write_failure_entry(
                        errorPmids,
                        failureReport,
                        pmid,
                        name,
                        REASON_NETWORK_ERROR,
                        "",
                        str(e),
                    )

            _sleep_with_jitter("next pmid")


