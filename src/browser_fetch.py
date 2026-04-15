"""Browser-based PDF fetch fallback using Playwright."""

from __future__ import annotations

from importlib import import_module
import os
import re
import time
from typing import Tuple
import urllib.parse


REASON_403_OR_CHALLENGE = "403_OR_CHALLENGE"
REASON_HTML_REDIRECT_ONLY = "HTML_REDIRECT_ONLY"
REASON_NO_PDF_LINK_FOUND = "NO_PDF_LINK_FOUND"
REASON_NETWORK_ERROR = "NETWORK_ERROR"


def _contains_challenge_marker(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "just a moment",
        "enable javascript",
        "captcha",
        "cloudflare",
        "cf-chl",
        "bot verification",
    ]
    return any(marker in lowered for marker in markers)


def _is_pdf_content_type(content_type: str) -> bool:
    return "application/pdf" in content_type.lower()


def _looks_like_pdf_url(url: str) -> bool:
    lowered = url.lower()
    return lowered.endswith(".pdf") or "/pdf" in lowered or "pdfft" in lowered


def _extract_meta_refresh_target(html: str, base_url: str) -> str:
    # 提取 <meta http-equiv="refresh"> 的跳转目标，处理“壳页面”场景。
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


def _extract_pii_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    if "/retrieve/pii/" in path:
        return path.split("/retrieve/pii/")[-1].strip()
    if "/science/article/pii/" in path:
        return path.split("/science/article/pii/")[-1].split("/")[0].strip()
    return ""


def _publisher_specific_candidates(url: str) -> list[str]:
    candidates: list[str] = []
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()

    # Elsevier 常见重定向链：linkinghub -> sciencedirect。
    pii = _extract_pii_from_url(url)
    if pii and ("elsevier" in host or "linkinghub.elsevier.com" in host or "sciencedirect.com" in host):
        candidates.extend(
            [
                "https://www.sciencedirect.com/science/article/pii/{0}".format(pii),
                "https://www.sciencedirect.com/science/article/pii/{0}/pdf".format(pii),
                "https://www.sciencedirect.com/science/article/pii/{0}/pdfft?isDTMRedir=true&download=true".format(pii),
            ]
        )

    # Wiley 常见 PDF 路径可由 /doi/ 页面推导。
    if "onlinelibrary.wiley.com" in host and "/doi/" in parsed.path:
        normalized = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        if "/doi/full/" in normalized:
            base = normalized.replace("/doi/full/", "/doi/")
        else:
            base = normalized
        candidates.extend(
            [
                base.replace("/doi/", "/doi/pdf/"),
                base.replace("/doi/", "/doi/pdfdirect/"),
            ]
        )

    seen = set()
    unique_candidates = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)
    return unique_candidates


def try_download_pdf_with_playwright(
    start_url: str,
    output_pdf_path: str,
    timeout_ms: int = 45000,
    headless: bool = True,
    user_agent: str = "Mozilla/5.0",
    user_data_dir: str = "",
    manual_challenge_wait_sec: int = 0,
    temp_dir: str = "",
) -> Tuple[bool, str, str, str]:
    """Try to fetch a PDF by rendering in a real browser context.

    Returns (success, reason, note, final_url).
    """

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
            if user_data_dir:
                # 持久化 profile：复用 cookies/session，适合人工先过挑战后批量跑。
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    accept_downloads=True,
                    user_agent=user_agent,
                )
                page = context.pages[0] if context.pages else context.new_page()
            else:
                browser = playwright.chromium.launch(headless=headless)
                context = browser.new_context(accept_downloads=True, user_agent=user_agent)
                page = context.new_page()

            captured_pdf = {"url": "", "bytes": b""}

            def on_response(response):
                # 监听所有响应，只要看到有效 PDF 字节就立刻缓存。
                content_type = response.headers.get("content-type", "")
                if _is_pdf_content_type(content_type) or _looks_like_pdf_url(response.url):
                    try:
                        body = response.body()
                    except Exception:
                        return
                    if body.startswith(b"%PDF"):
                        captured_pdf["url"] = response.url
                        captured_pdf["bytes"] = body

            page.on("response", on_response)

            response = page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)
            final_url = page.url
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12000))
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1200)

            if captured_pdf["bytes"]:
                with open(output_pdf_path, "wb") as file_handle:
                    file_handle.write(captured_pdf["bytes"])
                context.close()
                if browser is not None:
                    browser.close()
                return True, "", "", captured_pdf["url"]

            if response is not None and _is_pdf_content_type(response.headers.get("content-type", "")):
                body = response.body()
                if body.startswith(b"%PDF"):
                    with open(output_pdf_path, "wb") as file_handle:
                        file_handle.write(body)
                    context.close()
                    if browser is not None:
                        browser.close()
                    return True, "", "", page.url

            html = page.content()
            lowered_html = html.lower()
            if (response is not None and response.status == 403) or _contains_challenge_marker(lowered_html):
                if not headless and manual_challenge_wait_sec > 0:
                    # 有界面模式下给人工操作窗口（验证码/挑战页），超时后继续判断。
                    deadline = time.monotonic() + manual_challenge_wait_sec
                    while time.monotonic() < deadline:
                        if captured_pdf["bytes"]:
                            with open(output_pdf_path, "wb") as file_handle:
                                file_handle.write(captured_pdf["bytes"])
                            context.close()
                            if browser is not None:
                                browser.close()
                            return True, "", "", captured_pdf["url"]

                        try:
                            page.wait_for_load_state("networkidle", timeout=2000)
                        except PlaywrightTimeoutError:
                            pass
                        page.wait_for_timeout(1200)

                        lowered_html = page.content().lower()
                        if not _contains_challenge_marker(lowered_html):
                            break
                else:
                    context.close()
                    if browser is not None:
                        browser.close()
                    return (
                        False,
                        REASON_403_OR_CHALLENGE,
                        "browser page blocked by challenge or 403",
                        page.url,
                    )

            redirect_hops = 0
            while redirect_hops < 5:
                # 部分站点先返回 refresh 页面，这里显式跟随几跳。
                html_now = page.content()
                target_url = _extract_meta_refresh_target(html_now, page.url)
                if not target_url:
                    # 兼容 JS 重定向壳页（location.href / location.replace）。
                    target_url = _extract_js_redirect_target(html_now, page.url)
                if not target_url:
                    break

                response = page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                final_url = page.url
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(1000)

                if captured_pdf["bytes"]:
                    with open(output_pdf_path, "wb") as file_handle:
                        file_handle.write(captured_pdf["bytes"])
                    context.close()
                    if browser is not None:
                        browser.close()
                    return True, "", "", captured_pdf["url"]

                if response is not None and _is_pdf_content_type(response.headers.get("content-type", "")):
                    body = response.body()
                    if body.startswith(b"%PDF"):
                        with open(output_pdf_path, "wb") as file_handle:
                            file_handle.write(body)
                        context.close()
                        if browser is not None:
                            browser.close()
                        return True, "", "", page.url

                redirect_hops += 1

            publisher_candidates = _publisher_specific_candidates(page.url)
            if page.url != start_url:
                publisher_candidates.extend(_publisher_specific_candidates(start_url))

            for candidate in publisher_candidates[:8]:
                try:
                    response = page.goto(candidate, wait_until="domcontentloaded", timeout=timeout_ms)
                except PlaywrightError:
                    continue

                final_url = page.url
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(800)

                if captured_pdf["bytes"]:
                    with open(output_pdf_path, "wb") as file_handle:
                        file_handle.write(captured_pdf["bytes"])
                    context.close()
                    if browser is not None:
                        browser.close()
                    return True, "", "", captured_pdf["url"]

                if response is not None and _is_pdf_content_type(response.headers.get("content-type", "")):
                    body = response.body()
                    if body.startswith(b"%PDF"):
                        with open(output_pdf_path, "wb") as file_handle:
                            file_handle.write(body)
                        context.close()
                        if browser is not None:
                            browser.close()
                        return True, "", "", page.url

            hrefs = page.eval_on_selector_all("a[href]", "elements => elements.map(e => e.href)")
            # 最后一轮：从页面链接里抽取可能的 PDF/下载地址尝试访问。
            candidate_links = []
            for href in hrefs:
                if not isinstance(href, str):
                    continue
                lowered = href.lower()
                if _looks_like_pdf_url(lowered) or "download" in lowered:
                    candidate_links.append(href)

            seen = set()
            unique_candidates = []
            for candidate in candidate_links:
                if candidate in seen:
                    continue
                seen.add(candidate)
                unique_candidates.append(candidate)

            for candidate in unique_candidates[:12]:
                response = page.goto(candidate, wait_until="domcontentloaded", timeout=timeout_ms)
                final_url = page.url
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(800)

                if captured_pdf["bytes"]:
                    with open(output_pdf_path, "wb") as file_handle:
                        file_handle.write(captured_pdf["bytes"])
                    context.close()
                    if browser is not None:
                        browser.close()
                    return True, "", "", captured_pdf["url"]

                if response is not None and _is_pdf_content_type(response.headers.get("content-type", "")):
                    body = response.body()
                    if body.startswith(b"%PDF"):
                        with open(output_pdf_path, "wb") as file_handle:
                            file_handle.write(body)
                        context.close()
                        if browser is not None:
                            browser.close()
                        return True, "", "", page.url

            html = page.content().lower()
            context.close()
            if browser is not None:
                browser.close()

            if "http-equiv=\"refresh\"" in html or "http-equiv=refresh" in html:
                return False, REASON_HTML_REDIRECT_ONLY, "page only provided html redirect", final_url

            return False, REASON_NO_PDF_LINK_FOUND, "browser fallback found no downloadable pdf", final_url

    except PlaywrightTimeoutError as exc:
        return False, REASON_NETWORK_ERROR, "browser timeout: {0}".format(exc), final_url
    except PlaywrightError as exc:
        return False, REASON_NETWORK_ERROR, "browser error: {0}".format(exc), final_url
