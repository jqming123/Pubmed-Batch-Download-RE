"""CORE API v3 单 PMID / 批量 PMID 全文下载脚本。

功能概述:
1) 输入单个 PubMed ID (`-pmid`) 或一组 PubMed ID 的文件 (`-pmidFile`)。
2) 调用 CORE API v3 的 Works 搜索接口按 pubmedId 检索记录。
3) 提取命中的 CORE Work ID。
4) 调用下载接口获取该 Work 的 PDF，并保存到指定目录。

鉴权要求:
- 本脚本强制从文件读取 API Key，不支持命令行明文传入 Key。
- 必须通过 `-apiKeyFile` 指定密钥文件路径。
- 密钥文件应将 CORE API Key 放在“第一行非空行”。

核心参数:
- `-pmid`: 单个数字型 PubMed ID（可选，与 `-pmidFile` 二选一或优先使用 `-pmid`）。
- `-pmidFile`: 可选，包含 PubMed IDs 的文本文件（详见下方格式）。
- `-out`: PDF 输出目录。
- `-apiKeyFile`: CORE API Key 文件路径（必填）。
- `-filename`: 可选，自定义输出文件名（会放在对应 work 目录内）。
- `-timeoutSec`: HTTP 超时秒数。

`-pmidFile` 文件格式要求:
- 文本文件，UTF-8 编码推荐。
- 每行一个 PMID，允许空行和以 `#` 开头的注释行会被忽略。
- 行可以包含额外字段（例如注释或标签），脚本会使用每行的第一个 token 作为 PMID；该 token 必须全部由数字组成。
- 示例内容:
  # sample pmid list
  2844484
  1234567  # 带注释
  7654321

输出规则（变化）:
- 若不传 `-filename`，默认输出为: `<out_dir>/core_<workid>/<pmid>.pdf`。

退出码:
- 0: 全部下载成功。
- 1: 发生一个或多个下载失败（脚本在批量模式下会继续处理剩余 PMID 并在最后返回 1）。

示例:
单个 PMID:
    python src/core_download_by_pmid.py -pmid 40376717 -out ./output_test -apiKeyFile ./core_api_key.txt

批量（文件）:
    python src/core_download_by_pmid.py -pmidFile ./input_test/example_PMID_havePMCID.txt -out ./output_test -apiKeyFile ./core_api_key.txt
"""

from __future__ import annotations

import argparse
import random
import re
import time
from pathlib import Path
from typing import Any, Optional, List

import requests

CORE_API_BASE = "https://api.core.ac.uk/v3"
DEFAULT_TIMEOUT_SEC = 60
DEFAULT_MAX_RETRIES = 4
DEFAULT_RETRY_BASE_SEC = 1.5
DEFAULT_DELAY_MIN_SEC = 0.5
DEFAULT_DELAY_MAX_SEC = 1.5
REASON_NO_PDF_LINK_FOUND = "NO_PDF_LINK_FOUND"
REASON_NETWORK_ERROR = "NETWORK_ERROR"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download full-text PDF from CORE API v3 using one PubMed ID."
    )
    parser.add_argument("-pmid", required=False, help="Single PubMed ID")
    parser.add_argument(
        "-pmidFile",
        required=False,
        help="Path to a text file containing PubMed IDs (one per line).",
    )
    parser.add_argument("-out", required=True, help="Output directory for downloaded PDF")
    parser.add_argument(
        "-apiKeyFile",
        required=True,
        help="Text file path that stores CORE API key on the first non-empty line.",
    )
    parser.add_argument(
        "-timeoutSec",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT_SEC})",
    )
    parser.add_argument(
        "-filename",
        default="",
        help="Optional output filename (with or without .pdf). Default: <pmid>_core_<workid>.pdf",
    )
    parser.add_argument(
        "-maxRetries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Max retry attempts for HTTP 429/500 (default: {DEFAULT_MAX_RETRIES})",
    )
    parser.add_argument(
        "-retryBaseSec",
        type=float,
        default=DEFAULT_RETRY_BASE_SEC,
        help=f"Base retry backoff in seconds (default: {DEFAULT_RETRY_BASE_SEC})",
    )
    parser.add_argument(
        "-delayMinSec",
        type=float,
        default=DEFAULT_DELAY_MIN_SEC,
        help=f"Minimum random delay before each request (default: {DEFAULT_DELAY_MIN_SEC})",
    )
    parser.add_argument(
        "-delayMaxSec",
        type=float,
        default=DEFAULT_DELAY_MAX_SEC,
        help=f"Maximum random delay before each request (default: {DEFAULT_DELAY_MAX_SEC})",
    )
    return parser


def _read_key_from_file(path: str) -> str:
    key_path = Path(path)
    if not key_path.exists() or not key_path.is_file():
        raise FileNotFoundError(f"API key file not found: {path}")

    with key_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            key = line.strip()
            if key:
                return key

    raise ValueError(f"API key file is empty: {path}")


def _read_pmids_from_file(path: str) -> List[str]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"PMID file not found: {path}")

    pmids: List[str] = []
    with p.open("r", encoding="utf-8") as handle:
        for line in handle:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # Accept lines that contain a numeric PMID anywhere, but prefer full-digit lines
            token = s.split()[0]
            if re.fullmatch(r"\d+", token):
                pmids.append(token)
    if not pmids:
        raise ValueError(f"No valid PMIDs found in file: {path}")
    return pmids


def _resolve_api_key(args: argparse.Namespace) -> str:
    if args.apiKeyFile.strip():
        return _read_key_from_file(args.apiKeyFile.strip())
    raise ValueError("No API key file provided. Use -apiKeyFile.")


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "pubmed-batch-download/core-api-v3-script",
        "Accept": "application/json",
    }


def _download_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "pubmed-batch-download/core-api-v3-script",
        "Accept": "application/pdf",
    }


def _safe_name(text: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return sanitized.strip("._") or "download"


def _extract_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    return []


def _jitter_sleep(delay_min_sec: float, delay_max_sec: float) -> None:
    if delay_min_sec <= 0 and delay_max_sec <= 0:
        return

    low = min(delay_min_sec, delay_max_sec)
    high = max(delay_min_sec, delay_max_sec)
    delay = random.uniform(max(low, 0.0), max(high, 0.0))
    if delay > 0:
        time.sleep(delay)


def _retry_sleep(
    attempt: int,
    base_sec: float,
    retry_after_header: Optional[str],
) -> None:
    retry_after = None
    if retry_after_header:
        try:
            retry_after = float(retry_after_header)
        except ValueError:
            retry_after = None

    if retry_after is not None and retry_after > 0:
        sleep_sec = retry_after
    else:
        # Exponential backoff with jitter.
        sleep_sec = max(base_sec, 0.0) * (2 ** max(attempt - 1, 0)) + random.uniform(0, 0.5)

    if sleep_sec > 0:
        time.sleep(sleep_sec)


def _find_work_by_pmid(
    session: requests.Session,
    pmid: str,
    timeout_sec: int,
    max_retries: int,
    retry_base_sec: float,
    delay_min_sec: float,
    delay_max_sec: float,
) -> dict[str, Any]:
    url = f"{CORE_API_BASE}/search/works"
    params = {"q": f"pubmedId:{pmid}", "limit": 5, "offset": 0}

    response: Optional[requests.Response] = None
    for attempt in range(1, max_retries + 2):
        _jitter_sleep(delay_min_sec, delay_max_sec)
        try:
            response = session.get(url, params=params, timeout=timeout_sec)
            response.raise_for_status()
            break
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {429, 500} and attempt <= max_retries:
                retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
                _retry_sleep(attempt, retry_base_sec, retry_after)
                continue
            raise
        except (requests.Timeout, requests.ConnectionError):
            if attempt <= max_retries:
                _retry_sleep(attempt, retry_base_sec, None)
                continue
            raise

    if response is None:
        raise RuntimeError("Search request did not return any response.")

    payload = response.json()
    results = _extract_results(payload)
    if not results:
        raise LookupError(f"No CORE work found for PubMed ID: {pmid}")

    # Prefer an exact pubmedId match when available.
    for item in results:
        value = item.get("pubmedId")
        if value is not None and str(value) == str(pmid):
            return item

    return results[0]


def _build_output_path(out_dir: Path, pmid: str, work_id: str, filename: str) -> Path:
    # Default layout: <out_dir>/core_<workid>/<pmid>.pdf
    work_dir = out_dir / _safe_name(f"core_{work_id}")
    if filename:
        name = filename if filename.lower().endswith(".pdf") else f"{filename}.pdf"
        return work_dir / _safe_name(name)

    return work_dir / _safe_name(f"{pmid}.pdf")


def _looks_like_pdf(content: bytes, content_type: str) -> bool:
    return content.startswith(b"%PDF") or "application/pdf" in content_type.lower()


def _download_work_pdf(
    session: requests.Session,
    api_key: str,
    work_id: str,
    output_path: Path,
    timeout_sec: int,
    max_retries: int,
    retry_base_sec: float,
    delay_min_sec: float,
    delay_max_sec: float,
) -> None:
    url = f"{CORE_API_BASE}/works/{work_id}/download"

    for attempt in range(1, max_retries + 2):
        _jitter_sleep(delay_min_sec, delay_max_sec)
        try:
            with session.get(url, headers=_download_headers(api_key), stream=True, timeout=timeout_sec) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")

                output_path.parent.mkdir(parents=True, exist_ok=True)

                first_chunk: Optional[bytes] = None
                with output_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 64):
                        if not chunk:
                            continue
                        if first_chunk is None:
                            first_chunk = chunk
                        handle.write(chunk)

                if first_chunk is None:
                    output_path.unlink(missing_ok=True)
                    raise RuntimeError("Download returned empty content.")

                if not _looks_like_pdf(first_chunk, content_type):
                    output_path.unlink(missing_ok=True)
                    raise RuntimeError(
                        "Downloaded content is not recognized as PDF. "
                        f"content-type={content_type or 'unknown'}"
                    )
            return
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {429, 500} and attempt <= max_retries:
                retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
                _retry_sleep(attempt, retry_base_sec, retry_after)
                continue
            raise
        except (requests.Timeout, requests.ConnectionError):
            if attempt <= max_retries:
                _retry_sleep(attempt, retry_base_sec, None)
                continue
            raise


def download_pdf_for_pmid(
    pmid: str,
    output_pdf_path: str,
    api_key_file: str,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_base_sec: float = DEFAULT_RETRY_BASE_SEC,
    delay_min_sec: float = DEFAULT_DELAY_MIN_SEC,
    delay_max_sec: float = DEFAULT_DELAY_MAX_SEC,
) -> tuple[bool, str, str, str]:
    try:
        api_key = _read_key_from_file(api_key_file)
    except Exception as exc:  # noqa: BLE001
        return False, REASON_NO_PDF_LINK_FOUND, str(exc), ""

    session = requests.Session()
    session.headers.update(_headers(api_key))

    try:
        work = _find_work_by_pmid(
            session,
            pmid,
            timeout_sec,
            max_retries,
            retry_base_sec,
            delay_min_sec,
            delay_max_sec,
        )
    except LookupError as exc:
        return False, REASON_NO_PDF_LINK_FOUND, str(exc), ""
    except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
        return False, REASON_NETWORK_ERROR, str(exc), ""
    except Exception as exc:  # noqa: BLE001
        return False, REASON_NETWORK_ERROR, str(exc), ""

    work_id = str(work.get("id", "")).strip()
    if not work_id:
        return False, REASON_NO_PDF_LINK_FOUND, f"No CORE work id found for PubMed ID: {pmid}", ""

    output_path = Path(output_pdf_path)
    download_url = f"{CORE_API_BASE}/works/{work_id}/download"

    try:
        _download_work_pdf(
            session,
            api_key,
            work_id,
            output_path,
            timeout_sec,
            max_retries,
            retry_base_sec,
            delay_min_sec,
            delay_max_sec,
        )
    except requests.HTTPError as exc:
        return False, REASON_NETWORK_ERROR, str(exc), download_url
    except (requests.Timeout, requests.ConnectionError, RuntimeError) as exc:
        return False, REASON_NETWORK_ERROR, str(exc), download_url
    except Exception as exc:  # noqa: BLE001
        return False, REASON_NETWORK_ERROR, str(exc), download_url

    return True, "", "", download_url


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        api_key = _resolve_api_key(args)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}")
        return 1

    if args.timeoutSec <= 0:
        print("[ERROR] -timeoutSec must be a positive integer.")
        return 1

    if args.maxRetries < 0:
        print("[ERROR] -maxRetries must be >= 0.")
        return 1

    if args.retryBaseSec < 0:
        print("[ERROR] -retryBaseSec must be >= 0.")
        return 1

    if args.delayMinSec < 0 or args.delayMaxSec < 0:
        print("[ERROR] -delayMinSec and -delayMaxSec must be >= 0.")
        return 1

    if not args.pmid and not args.pmidFile:
        print("[ERROR] Either -pmid or -pmidFile must be provided.")
        return 1

    out_dir = Path(args.out).expanduser().resolve()

    # Build list of pmids to process
    pmids: List[str] = []
    if args.pmid:
        p = str(args.pmid).strip()
        if not p or not re.fullmatch(r"\d+", p):
            print("[ERROR] -pmid must be a numeric PubMed ID.")
            return 1
        pmids = [p]
    else:
        try:
            pmids = _read_pmids_from_file(args.pmidFile)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {exc}")
            return 1

    session = requests.Session()
    session.headers.update(_headers(api_key))

    successes = 0
    search_failures = 0
    download_failures = 0
    for pmid in pmids:
        try:
            work = _find_work_by_pmid(
                session,
                pmid,
                args.timeoutSec,
                args.maxRetries,
                args.retryBaseSec,
                args.delayMinSec,
                args.delayMaxSec,
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            text = ""
            if exc.response is not None:
                try:
                    text = exc.response.text[:300]
                except Exception:  # noqa: BLE001
                    text = ""
            print(f"[SEARCH ERROR] PMID {pmid}: HTTP {status}: {text}")
            search_failures += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[SEARCH ERROR] PMID {pmid}: {exc}")
            search_failures += 1
            continue

        work_id = str(work.get("id", "")).strip()
        if not work_id:
            print(f"[SEARCH ERROR] PMID {pmid}: CORE result has no work id.")
            search_failures += 1
            continue

        output_path = _build_output_path(out_dir, pmid, work_id, args.filename)
        try:
            _download_work_pdf(
                session,
                api_key,
                work_id,
                output_path,
                args.timeoutSec,
                args.maxRetries,
                args.retryBaseSec,
                args.delayMinSec,
                args.delayMaxSec,
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            text = ""
            if exc.response is not None:
                try:
                    text = exc.response.text[:300]
                except Exception:  # noqa: BLE001
                    text = ""
            print(f"[DOWNLOAD ERROR] PMID {pmid}: HTTP {status}: {text}")
            if status == 404:
                print(
                    "[HINT] CORE 找到了该 PMID 对应的 Work，但该 Work 可能没有可下载的 PDF，"
                    "或者该记录的下载权限/源站状态不允许通过 /download 获取全文。"
                )
            elif status == 403:
                print(
                    "[HINT] 下载被 CORE 拒绝，通常意味着该全文受限、需要更高权限，"
                    "或者该记录当前没有可通过 API 获取的 PDF。"
                )
            download_failures += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[DOWNLOAD ERROR] PMID {pmid}: {exc}")
            download_failures += 1
            continue

        title = str(work.get("title", "")).strip()
        print(f"[OK] PMID: {pmid}")
        print(f"[OK] CORE Work ID: {work_id}")
        if title:
            print(f"[OK] Title: {title}")
        print(f"[OK] PDF saved to: {output_path}")
        successes += 1

    total_failures = search_failures + download_failures
    print(
        "[SUMMARY] "
        f"success={successes}, "
        f"search_failed={search_failures}, "
        f"download_failed={download_failures}, "
        f"total_failed={total_failures}"
    )

    if total_failures:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
