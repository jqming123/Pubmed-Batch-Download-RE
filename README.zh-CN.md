# Pubmed-Batch-Download（Python）

基于 PubMed ID（PMID）批量下载论文 PDF。

本仓库当前以 src/ 下的 Python 实现为主。
ruby_version/ 目录属于历史版本，本说明文档不覆盖 Ruby 代码。

## 项目状态

- pyproject.toml 中的项目名/版本：pubmed-batch-download / 3.0.0
- Python 要求：>=3.9
- 维护状态：以社区贡献为主，欢迎提交 PR

## 功能概览

- 支持 -pmids（逗号分隔）或 -pmf（文件输入）两种批量输入方式
- 自动跳过已下载的 PDF
- 内置站点规则解析 + 通用兜底逻辑
- 可选 Playwright 浏览器兜底（应对 JS 渲染/挑战页）
- 输出失败简表（-errors）和详细失败原因报告（-failureReport）
- 支持重试、超时、临时目录、请求间隔等参数调节
- 提供 warmup_then_batch.py：先人工过一次挑战页，再复用浏览器配置批量下载

## 安装

### 方式 A：uv（推荐）

uv sync
uv run playwright install chromium

### 方式 B：pip

python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium

### 方式 C：conda（兼容旧环境文件）

conda env create -f pubmed-batch-downloader-py3.yml
conda activate pubmed-batch-downloader-py3

Windows 可尝试：

conda env create -f pubmed-batch-downloader-py3-windows.yml

## 主程序使用

在仓库根目录运行：

python src/fetch_pdfs.py [-pmids ... | -pmf ...] [其他参数]

注意：-pmids 与 -pmf 二选一，不能同时使用。

### 输入方式

1. -pmids

python src/fetch_pdfs.py -pmids 123,124,125

2. -pmf

python src/fetch_pdfs.py -pmf ./example_pmf.tsv

## fetch_pdfs.py 参数说明

-pmids
逗号分隔 PMID 列表（与 -pmf 互斥）

-pmf
输入文件：每行一个 PMID，或“PMID<TAB>name”

-out
输出目录（默认：fetched_pdfs）

-errors
失败 PMID 输出文件（默认：unfetched_pmids.tsv）

-failureReport
详细失败报告 TSV 路径
默认：若 -errors 以 .tsv 结尾，则为 <errors_without_.tsv>.reasons.tsv
否则为 <errors>.reasons.tsv

-maxRetries
网络类失败最大重试次数（默认：3）

-noBrowserFallback
禁用 Playwright 浏览器兜底（默认启用兜底）

-browserHeaded
浏览器兜底使用有界面模式

-browserUserDataDir
Playwright 持久化用户目录（复用 Cookie/会话）

-manualChallengeWaitSec
有界面模式下，等待手动过挑战页的秒数（默认：90）

-requestTimeoutSec
requests 路径超时时间（秒，默认：40）

-browserTimeoutSec
浏览器兜底操作超时时间（秒，默认：45）

-tmpDir
临时目录（默认：<repo>/tmp）

-minIntervalSec
PMID 处理/重试之间的最小延时（秒，默认：1.0）

-maxIntervalSec
PMID 处理/重试之间的最大延时（秒，默认：3.0）

## Warmup + 批处理流程

当目标站点需要先人工过挑战页时，建议使用：

python src/warmup_then_batch.py -pmf /path/to/input.tsv -out /path/to/output_dir

流程说明：

1. 第一条 PMID 先用有界面浏览器进行 warmup
2. 后续 PMID 复用同一个 Playwright profile
3. 默认把运行期临时文件放在项目 tmp 目录

warmup_then_batch.py 参数：

-pmf
输入 PMID 文件（必填）

-out
批处理输出目录（必填）

-errors
批处理失败文件路径（默认：<pmf_stem>_failed2.tsv）

-tmpDir
临时目录（默认：<repo>/tmp）

-profileDir
Playwright profile 目录（默认：<tmpDir>/pw_pubmed_profile）

-warmupOut
warmup 阶段输出目录（默认：<tmpDir>/pmid_out）

-warmupErrors
warmup 阶段失败文件（默认：<tmpDir>/pmid_err.tsv）

-warmupChallengeWaitSec
warmup 人工等待秒数（默认：240）

-warmupBrowserTimeoutSec
warmup 浏览器超时（秒，默认：120）

-batchBrowserTimeoutSec
batch 浏览器超时（秒，默认：90）

--batch-headed
batch 阶段也使用有界面模式

## PMF 文件格式

单列格式：

12345
23456
34567

双列格式（PMID<TAB>不带 .pdf 后缀的文件名）：

12345	Article_One
23456	Another_Paper

下载失败时，-errors 输出文件为 PMF 兼容格式，可直接作为下一次重试输入。

## 输出说明

- PDF 保存到 -out 目录，文件名格式为 <name>.pdf
- 失败简表 TSV（默认：unfetched_pmids.tsv）
- 详细失败原因 TSV，列为：

pmid	name	reason	url	note

当前失败类别包括：

- 403_OR_CHALLENGE
- HTML_REDIRECT_ONLY
- NO_PDF_LINK_FOUND
- NETWORK_ERROR

## 已知限制

- 仅 requests 路径无法执行 JavaScript。
- 部分出版商流程仍需要 Playwright 兜底或人工过挑战页。
- 付费内容是否可下载取决于你的网络环境、会话状态和机构访问权限。
