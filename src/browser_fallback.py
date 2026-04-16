"""Browser-based PDF fetch fallback using Playwright."""

from __future__ import annotations

import argparse
from importlib import import_module
import os
import re
import time
from typing import Optional, Tuple
import urllib.parse

import requests


REASON_403_OR_CHALLENGE = "403_OR_CHALLENGE"
REASON_HTML_REDIRECT_ONLY = "HTML_REDIRECT_ONLY"
REASON_NO_PDF_LINK_FOUND = "NO_PDF_LINK_FOUND"
REASON_NETWORK_ERROR = "NETWORK_ERROR"


def _challenge_marker_score(text: str) -> tuple[int, bool]:
    lowered = text.lower()
    strong_markers = [
        "just a moment",
        "are you a robot",
        "verify you are human",
        "checking your browser",
    ]
    weak_markers = [
        "cf-chl",
        "challenge-platform",
        "challenges.cloudflare.com",
        "bot verification",
        "hcaptcha",
        "g-recaptcha",
        "captcha",
        "enable javascript",
    ]

    has_strong = any(marker in lowered for marker in strong_markers)
    score = sum(1 for marker in weak_markers if marker in lowered)
    return score, has_strong


def _is_challenge_url(url: str) -> bool:
    lowered = (url or "").lower()
    return (
        "/cdn-cgi/challenge-platform" in lowered
        or "challenges.cloudflare.com" in lowered
        or "captcha" in lowered
    )


def _looks_like_article_url(url: str) -> bool:
    lowered = (url or "").lower()
    return (
        "sciencedirect.com/science/article/" in lowered
        or "onlinelibrary.wiley.com/doi/" in lowered
        or "pubmed.ncbi.nlm.nih.gov/" in lowered
        or lowered.endswith(".pdf")
    )


def _is_still_on_challenge_page(page, lowered_html: str) -> bool:
    if _is_challenge_url(page.url):
        return True

    try:
        title_lowered = (page.title() or "").strip().lower()
    except Exception:
        title_lowered = ""

    if any(marker in title_lowered for marker in ["just a moment", "are you a robot", "verify you are human", "captcha"]):
        return True

    marker_score, has_strong_marker = _challenge_marker_score(lowered_html)
    if has_strong_marker:
        return True

    if _looks_like_article_url(page.url):
        return False

    return marker_score >= 2


def _is_pdf_content_type(content_type: str) -> bool:
    return "application/pdf" in content_type.lower()


def _looks_like_pdf_url(url: str) -> bool:
    lowered = url.lower()
    return lowered.endswith(".pdf") or "/pdf" in lowered or "pdfft" in lowered


def _extract_pdf_asset_candidates(html: str, base_url: str) -> list[str]:
    patterns = [
        r"https?://pdf\.sciencedirectassets\.com/[^\"'<>\s]+?main\.pdf[^\"'<>\s]*",
        r"https?://ars\.els-cdn\.com/[^\"'<>\s]+\.pdf[^\"'<>\s]*",
        r"https?://[^\"'<>\s]+/main\.pdf\?[^\"'<>\s]*",
        r"https?://[^\"'<>\s]+\.pdf(?:\?[^\"'<>\s]*)?",
    ]

    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(re.findall(pattern, html, flags=re.IGNORECASE))

    seen = set()
    unique_candidates: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip().rstrip("'\")>])},;")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unique_candidates.append(urllib.parse.urljoin(base_url, cleaned))

    def score(candidate: str) -> tuple[int, int]:
        lowered = candidate.lower()
        rank = 0
        if "main.pdf" in lowered:
            rank += 100
        if "pdf.sciencedirectassets.com" in lowered:
            rank += 50
        if "ars.els-cdn.com" in lowered:
            rank += 40
        if "mmc" in lowered or "supplement" in lowered or "appendix" in lowered:
            rank -= 100
        if lowered.endswith(".pdf"):
            rank += 10
        return rank, -len(candidate)

    unique_candidates.sort(key=score, reverse=True)
    return unique_candidates


def _extract_meta_refresh_target(html: str, base_url: str) -> str:
    pattern = re.compile(
        r"<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]*content=[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if not match:
        return ""

    content = match.group(1)
    url_match = re.search(r"url\s*=\s*(.+)", content, flags=re.IGNORECASE)
    if not url_match:
        return ""

    target = url_match.group(1).strip().strip("'\"")
    if not target:
        return ""

    return urllib.parse.urljoin(base_url, target)


def _extract_js_redirect_target(html: str, base_url: str) -> str:
    patterns = [
        r"location\.href\s*=\s*['\"]([^'\"]+)['\"]",
        r"window\.location\s*=\s*['\"]([^'\"]+)['\"]",
        r"location\.replace\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"window\.location\.assign\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if not match:
            continue
        target = match.group(1).strip()
        if target:
            return urllib.parse.urljoin(base_url, target)
    return ""


def _safe_page_content(page, max_attempts: int = 6, wait_ms: int = 500) -> str:
    last_exc = None
    for _ in range(max_attempts):
        try:
            return page.content()
        except Exception as exc:
            message = str(exc).lower()
            if "navigating" in message or "target page, context or browser has been closed" in message:
                last_exc = exc
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=2500)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(wait_ms)
                except Exception:
                    break
                continue
            raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unable to read page content")


def _save_pdf_content(pdf_bytes: bytes, output_pdf_path: str) -> bool:
    """Save PDF bytes to file if valid PDF header."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return False
    try:
        with open(output_pdf_path, "wb") as f:
            f.write(pdf_bytes)
        return True
    except Exception:
        return False


def _save_download(download, output_pdf_path: str) -> bool:
    """Save Playwright download object if it's a PDF."""
    try:
        suggested = (download.suggested_filename or "").lower()
    except Exception:
        return False

    if not suggested.endswith(".pdf"):
        return False

    try:
        download.save_as(output_pdf_path)
        return True
    except Exception:
        return False


def _save_if_pdf_response(response, output_pdf_path: str) -> bool:
    """Save HTTP response if it contains a PDF."""
    if response is None:
        return False

    if not _is_pdf_content_type(response.headers.get("content-type", "")):
        return False

    try:
        body = response.body()
    except Exception:
        return False

    return _save_pdf_content(body, output_pdf_path)


def _build_cookie_header(context, url: str) -> str:
    try:
        cookies = context.cookies([url])
    except Exception:
        return ""

    if not cookies:
        return ""

    return "; ".join("{0}={1}".format(cookie["name"], cookie["value"]) for cookie in cookies)


def _download_pdf_via_requests(pdf_url: str, output_pdf_path: str, context=None, referer: str = "", user_agent: str = "") -> bool:
    headers = {"Accept": "application/pdf,*/*;q=0.8"}
    if user_agent:
        headers["User-Agent"] = user_agent
    if referer:
        headers["Referer"] = referer
    if context is not None:
        cookie_header = _build_cookie_header(context, pdf_url)
        if cookie_header:
            headers["Cookie"] = cookie_header

    response = requests.get(pdf_url, headers=headers, timeout=30, allow_redirects=True)
    if not _is_pdf_content_type(response.headers.get("content-type", "")):
        return False
    if not response.content.startswith(b"%PDF"):
        return False

    with open(output_pdf_path, "wb") as file_handle:
        file_handle.write(response.content)
    return True


def _try_browser_download(page, candidate_url: str, output_pdf_path: str, timeout_ms: int) -> tuple[bool, str, str, str]:
    """Try to download PDF from candidate URL using browser navigation."""
    context = page.context
    download = None
    response = None

    try:
        with context.expect_download(timeout=timeout_ms) as download_info:
            response = page.goto(candidate_url, wait_until="domcontentloaded", timeout=timeout_ms)
        download = download_info.value
    except Exception:
        try:
            response = page.goto(candidate_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            response = None

    final_url = page.url
    if download is not None and _save_download(download, output_pdf_path):
        return True, "", "", final_url
    if _save_if_pdf_response(response, output_pdf_path):
        return True, "", "", final_url
    return False, "", "", final_url


def _try_candidates(page, candidates: list[str], output_pdf_path: str, timeout_ms: int, user_agent: str) -> tuple[bool, str, str, str]:
    """Try to download PDF from a list of candidate URLs."""
    context = page.context
    for candidate in candidates:
        print("** 发现 PDF 资源地址，尝试直接下载: {0}".format(candidate))
        if _download_pdf_via_requests(candidate, output_pdf_path, context=context, referer=page.url, user_agent=user_agent):
            return True, "", "", candidate
        saved, reason, note, final_url = _try_browser_download(page, candidate, output_pdf_path, timeout_ms)
        if saved:
            return True, reason, note, final_url
    return False, "", "", page.url


def _extract_candidate_links(page) -> list[str]:
    """Extract PDF-like links from page HTML."""
    try:
        hrefs = page.eval_on_selector_all("a[href]", "elements => elements.map(e => e.href)")
    except Exception:
        return []
    
    candidate_links = []
    for href in hrefs:
        if not isinstance(href, str):
            continue
        lowered = href.lower()
        if _looks_like_pdf_url(lowered) or "download" in lowered:
            candidate_links.append(href)
    return candidate_links


def _deduplicate_candidates(extracted_candidates: list[str]) -> list[str]:
    """Remove duplicate candidates preserving order."""
    unique_candidates = []
    seen = set()
    for candidate in extracted_candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)
    return unique_candidates


def _create_pdf_capture_handler(captured_pdf: dict):
    """Create a response handler that captures PDF from network responses."""
    def on_response(response):
        content_type = response.headers.get("content-type", "")
        if _is_pdf_content_type(content_type) or _looks_like_pdf_url(response.url):
            try:
                body = response.body()
            except Exception:
                return
            if body.startswith(b"%PDF"):
                captured_pdf["url"] = response.url
                captured_pdf["bytes"] = body
    return on_response


def _handle_challenge_page(page, output_pdf_path: str, timeout_ms: int, headless: bool, 
                          manual_challenge_wait_sec: int, captured_pdf: dict) -> tuple[bool, str, str, str]:
    """Handle challenge pages (CAPTCHA, bot checks, etc.)."""
    print("** 检测到挑战页(403/robot/captcha)，进入人工验证流程")
    if not headless and manual_challenge_wait_sec > 0:
        print("** 等待手动完成验证，最长 {0}s；完成后将自动继续抓取".format(manual_challenge_wait_sec))
        deadline = time.monotonic() + manual_challenge_wait_sec
        next_progress_log_at = time.monotonic() + 10
        while time.monotonic() < deadline:
            if captured_pdf["bytes"] and _save_pdf_content(captured_pdf["bytes"], output_pdf_path):
                return True, "", "", captured_pdf["url"]

            try:
                page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                pass
            page.wait_for_timeout(1200)

            html_now = _safe_page_content(page)
            if not _is_still_on_challenge_page(page, html_now.lower()):
                print("** 已脱离挑战页，开始继续抓取")
                break

            now = time.monotonic()
            if now >= next_progress_log_at:
                remain = max(0, int(deadline - now))
                print("** 挑战等待中: 剩余 {0}s, 当前URL: {1}".format(remain, page.url))
                next_progress_log_at = now + 10
        else:
            print("** 挑战页等待超时，继续按后续逻辑尝试抓取")
        return False, "", "", page.url
    else:
        return False, REASON_403_OR_CHALLENGE, "browser page blocked by challenge or 403", page.url


def _setup_browser_and_context(playwright, headless: bool, user_agent: Optional[str], 
                               user_data_dir: str, selected_channel: str, launch_flags: list):
    """Initialize Playwright browser and context with proper configuration."""
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError:
        PlaywrightError = Exception
    
    browser = None
    context_options = {
        "headless": headless,
        "accept_downloads": True,
        "args": launch_flags,
        "ignore_default_args": ["--enable-automation"],
    }
    if user_agent:
        context_options["user_agent"] = user_agent
    if selected_channel:
        context_options["channel"] = selected_channel

    if user_data_dir:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                **context_options,
            )
            if selected_channel:
                print("** Playwright browser channel: {0}".format(selected_channel))
        except PlaywrightError as exc:
            if selected_channel:
                print("** browser channel '{0}' unavailable, fallback to bundled Chromium: {1}".format(selected_channel, exc))
                context_options.pop("channel", None)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    **context_options,
                )
            else:
                raise
        page = context.pages[0] if context.pages else context.new_page()
    else:
        launch_options = {
            "headless": headless,
            "args": launch_flags,
            "ignore_default_args": ["--enable-automation"],
        }
        if selected_channel:
            launch_options["channel"] = selected_channel

        try:
            browser = playwright.chromium.launch(**launch_options)
            if selected_channel:
                print("** Playwright browser channel: {0}".format(selected_channel))
        except PlaywrightError as exc:
            if selected_channel:
                print("** browser channel '{0}' unavailable, fallback to bundled Chromium: {1}".format(selected_channel, exc))
                launch_options.pop("channel", None)
                browser = playwright.chromium.launch(**launch_options)
            else:
                raise
        browser_context_options: dict = {"accept_downloads": True}
        if user_agent:
            browser_context_options["user_agent"] = user_agent
        context = browser.new_context(**browser_context_options)
        page = context.new_page()

    return browser, context, page


def try_download_pdf_with_playwright(
    start_url: str,
    output_pdf_path: str,
    timeout_ms: int = 45000,
    headless: bool = True,
    user_agent: Optional[str] = None,
    user_data_dir: str = "",
    manual_challenge_wait_sec: int = 0,
    temp_dir: str = "",
    browser_channel: str = "",
) -> Tuple[bool, str, str, str]:
    """Try to fetch a PDF by rendering in a real browser context."""

    if temp_dir:
        os.makedirs(temp_dir, exist_ok=True)
        os.environ["TMPDIR"] = temp_dir
        os.environ["TMP"] = temp_dir
        os.environ["TEMP"] = temp_dir

    try:
        sync_api = import_module("playwright.sync_api")
        PlaywrightError = sync_api.Error
        PlaywrightTimeoutError = sync_api.TimeoutError
        sync_playwright = sync_api.sync_playwright
    except (ImportError, AttributeError):
        return (
            False,
            REASON_NETWORK_ERROR,
            "Playwright not installed. Install with: uv pip install playwright && uv run playwright install chromium (or pip install playwright && playwright install chromium)",
            start_url,
        )

    final_url = start_url

    try:
        with sync_playwright() as playwright:
            browser = None
            launch_flags = [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
            selected_channel = (browser_channel or "").strip()
            
            browser, context, page = _setup_browser_and_context(
                playwright, headless, user_agent, user_data_dir, selected_channel, launch_flags
            )

            captured_pdf = {"url": "", "bytes": b""}
            page.on("response", _create_pdf_capture_handler(captured_pdf))

            def render_once(page_url: str) -> tuple[bool, str, str, str]:
                """Render page and attempt to extract PDF."""
                response = page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
                current_url = page.url
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12000))
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(1200)

                if captured_pdf["bytes"] and _save_pdf_content(captured_pdf["bytes"], output_pdf_path):
                    return True, "", "", captured_pdf["url"]

                if _save_if_pdf_response(response, output_pdf_path):
                    return True, "", "", current_url

                html = _safe_page_content(page)
                extracted_candidates = _extract_pdf_asset_candidates(html, current_url)
                if extracted_candidates:
                    saved, reason, note, final_url = _try_candidates(page, extracted_candidates[:8], output_pdf_path, timeout_ms, user_agent or "")
                    if saved:
                        return True, reason, note, final_url

                lowered_html = html.lower()
                if (response is not None and response.status == 403) or _is_still_on_challenge_page(page, lowered_html):
                    return _handle_challenge_page(page, output_pdf_path, timeout_ms, headless, manual_challenge_wait_sec, captured_pdf)

                return False, "", "", current_url

            try:
                ok, reason, note, final_url = render_once(start_url)
                if ok:
                    context.close()
                    if browser is not None:
                        browser.close()
                    return True, reason, note, final_url

                for _ in range(5):
                    html_now = _safe_page_content(page)
                    target_url = _extract_meta_refresh_target(html_now, page.url)
                    if not target_url:
                        target_url = _extract_js_redirect_target(html_now, page.url)
                    if not target_url:
                        break

                    ok, reason, note, final_url = render_once(target_url)
                    if ok:
                        context.close()
                        if browser is not None:
                            browser.close()
                        return True, reason, note, final_url

                extracted_candidates = _extract_pdf_asset_candidates(_safe_page_content(page), page.url)
                if page.url != start_url:
                    extracted_candidates.extend(_extract_pdf_asset_candidates(_safe_page_content(page), start_url))
                unique_candidates = _deduplicate_candidates(extracted_candidates)

                if unique_candidates:
                    saved, reason, note, final_url = _try_candidates(page, unique_candidates[:8], output_pdf_path, timeout_ms, user_agent or "")
                    if saved:
                        context.close()
                        if browser is not None:
                            browser.close()
                        return True, reason, note, final_url

                candidate_links = _extract_candidate_links(page)
                for candidate in candidate_links[:12]:
                    ok, reason, note, final_url = _try_browser_download(page, candidate, output_pdf_path, timeout_ms)
                    if ok:
                        context.close()
                        if browser is not None:
                            browser.close()
                        return True, reason, note, final_url

                html = _safe_page_content(page).lower()
                context.close()
                if browser is not None:
                    browser.close()

                if "http-equiv=\"refresh\"" in html or "http-equiv=refresh" in html:
                    return False, REASON_HTML_REDIRECT_ONLY, "page only provided html redirect", page.url

                return False, REASON_NO_PDF_LINK_FOUND, "browser fallback found no downloadable pdf", page.url

            except PlaywrightTimeoutError as exc:
                context.close()
                if browser is not None:
                    browser.close()
                return False, REASON_NETWORK_ERROR, "browser timeout: {0}".format(exc), final_url
            except PlaywrightError as exc:
                message = str(exc)
                context.close()
                if browser is not None:
                    browser.close()
                if "target page, context or browser has been closed" in message.lower():
                    return False, REASON_403_OR_CHALLENGE, "browser window/page was closed before challenge flow finished", final_url
                return False, REASON_NETWORK_ERROR, "browser error: {0}".format(message), final_url

    except PlaywrightTimeoutError as exc:
        return False, REASON_NETWORK_ERROR, "browser timeout: {0}".format(exc), final_url
    except PlaywrightError as exc:
        message = str(exc)
        if "target page, context or browser has been closed" in message.lower():
            return False, REASON_403_OR_CHALLENGE, "browser window/page was closed before challenge flow finished", final_url
        return False, REASON_NETWORK_ERROR, "browser error: {0}".format(message), final_url


def run_browser_fallback_download(
    start_url: str,
    output_pdf_path: str,
    browser_timeout_sec: int,
    browser_headed: bool,
    user_agent: str,
    browser_user_data_dir: str,
    manual_challenge_wait_sec: int,
    tmp_dir: str,
) -> Tuple[bool, str, str, str]:
    """Convenience wrapper for try_download_pdf_with_playwright with timeout conversion."""
    return try_download_pdf_with_playwright(
        start_url=start_url,
        output_pdf_path=output_pdf_path,
        timeout_ms=browser_timeout_sec * 1000,
        headless=not browser_headed,
        user_agent=user_agent,
        user_data_dir=browser_user_data_dir,
        manual_challenge_wait_sec=manual_challenge_wait_sec,
        temp_dir=tmp_dir,
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build command-line argument parser."""
    parser = argparse.ArgumentParser(description="Browser fallback PDF downloader")
    parser.add_argument("-startUrl", required=True, help="Starting article URL")
    parser.add_argument("-outputPdfPath", required=True, help="Output PDF path")
    parser.add_argument("-browserTimeoutSec", default=45, type=int, help="Timeout in seconds")
    parser.add_argument("-browserHeaded", action="store_true", help="Run browser in headed mode")
    parser.add_argument("-userAgent", required=True, help="Browser user-agent")
    parser.add_argument("-browserUserDataDir", default="", help="Persistent browser user data dir")
    parser.add_argument(
        "-manualChallengeWaitSec",
        default=90,
        type=int,
        help="Wait window for manual challenge solving in headed mode",
    )
    parser.add_argument("-tmpDir", required=True, help="Temporary directory for runtime files")
    return parser


def main() -> int:
    """Main entry point for command-line execution."""
    parser = _build_parser()
    args = parser.parse_args()

    success, reason, note, final_url = run_browser_fallback_download(
        start_url=args.startUrl,
        output_pdf_path=args.outputPdfPath,
        browser_timeout_sec=args.browserTimeoutSec,
        browser_headed=args.browserHeaded,
        user_agent=args.userAgent,
        browser_user_data_dir=args.browserUserDataDir,
        manual_challenge_wait_sec=args.manualChallengeWaitSec,
        tmp_dir=args.tmpDir,
    )

    if success:
        print("success\t{0}".format(final_url))
        return 0

    print("failed\t{0}\t{1}\t{2}".format(reason, final_url, note))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
