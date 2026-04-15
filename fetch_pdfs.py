
"""Fetch PDFs for PubMed articles using site-specific finders."""

import argparse
import os
import re
import sys
import urllib.parse
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup


parser = argparse.ArgumentParser()
parser._optionals.title = "Flag Arguments"
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
args = vars(parser.parse_args())


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


def savePdfFromUrl(pdfUrl, directory, name, headers):
    response = requests.get(pdfUrl, headers=headers, allow_redirects=True)
    with open("{0}/{1}.pdf".format(directory, name), "wb") as file_handle:
        file_handle.write(response.content)


def _tag_attr(tag: Any, attr: str) -> Optional[str]:
    getter = getattr(tag, "get", None)
    if getter is None:
        return None

    value = getter(attr)
    return value if isinstance(value, str) and value else None


def fetch(pmid, finders, name, headers, errorPmids):
    uri = (
        "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
        "?dbfrom=pubmed&id={0}&retmode=ref&cmd=prlinks"
    ).format(pmid)
    success = False
    skip_finders = False

    if os.path.exists("{0}/{1}.pdf".format(args["out"], pmid)):
        print("** Reprint #{0} already downloaded and in folder; skipping.".format(pmid))
        return

    response = requests.get(uri, headers=headers)
    if "ovid" in response.url:
        print(
            " ** Reprint {0} cannot be fetched as ovid is not supported by the requests package.".format(pmid)
        )
        errorPmids.write("{}\t{}\n".format(pmid, name))
        skip_finders = True
        success = True

    soup = BeautifulSoup(response.content, "lxml")

    if not skip_finders:
        for finder in finders:
            print("Trying {0}".format(finder))
            pdfUrl = globals()[finder](response, soup, headers)
            if pdfUrl is not None:
                savePdfFromUrl(pdfUrl, args["out"], name, headers)
                success = True
                print("** fetching of reprint {0} succeeded".format(pmid))
                break

    if not success:
        print("** Reprint {0} could not be fetched with the current finders.".format(pmid))
        errorPmids.write("{}\t{}\n".format(pmid, name))


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
    content_type = req.headers.get("content-type", "").lower()
    if req.url.lower().endswith(".pdf") or "application/pdf" in content_type or req.content.startswith(b"%PDF"):
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

    response = requests.get(urllib.parse.unquote(new_uri), allow_redirects=True, headers=headers)
    soup = BeautifulSoup(response.content, "lxml")

    possibleLinks = soup.find_all("meta", attrs={"name": "citation_pdf_url"})
    if not possibleLinks:
        return None

    citation_pdf_url = _tag_attr(possibleLinks[0], "content")
    if not citation_pdf_url:
        return None

    print("** fetching reprint using the 'science_direct' finder...")
    response = requests.get(citation_pdf_url, headers=headers)
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
    for pmid, name in zip(pmids, names):
        print("Trying to fetch pmid {0}".format(pmid))
        retriesSoFar = 0
        while retriesSoFar < args["maxRetries"]:
            try:
                fetch(pmid, finders, name, headers, errorPmids)
                retriesSoFar = args["maxRetries"]
            except requests.ConnectionError as e:
                if "104" in str(e) or "BadStatusLine" in str(e):
                    retriesSoFar += 1
                    if retriesSoFar < args["maxRetries"]:
                        print("** fetching of reprint {0} failed from error {1}, retrying".format(pmid, e))
                    else:
                        print("** fetching of reprint {0} failed from error {1}".format(pmid, e))
                        errorPmids.write("{}\t{}\n".format(pmid, name))
                else:
                    print("** fetching of reprint {0} failed from error {1}".format(pmid, e))
                    retriesSoFar = args["maxRetries"]
                    errorPmids.write("{}\t{}\n".format(pmid, name))
            except Exception as e:
                print("** fetching of reprint {0} failed from error {1}".format(pmid, e))
                retriesSoFar = args["maxRetries"]
                errorPmids.write("{}\t{}\n".format(pmid, name))


