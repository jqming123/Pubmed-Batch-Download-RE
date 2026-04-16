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
- 对 Elsevier / ScienceDirect 来源的 PMID，优先使用 Elsevier Full Text Retrieval API 直连下载 PDF
- 对 Wiley / Online Library 来源的 PMID，优先使用 Wiley TDM Client 直连下载 PDF

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

1. -pmf

python src/fetch_pdfs.py -pmf ./example_pmf.tsv

## fetch_pdfs.py 参数说明

-pmids
逗号分隔 PMID 列表（与 -pmf 互斥）

-pmf
输入文件：每行一个 PMID，或“PMID 和 name 之间用制表符分隔”

-out
输出目录（默认：fetched_pdfs）

-errors
失败 PMID 输出文件（默认：unfetched_pmids.tsv）

-failureReport
详细失败报告 TSV 路径
默认：若 -errors 以 .tsv 结尾，则为对应的 .reasons.tsv 文件
否则为 errors.reasons.tsv

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
临时目录（默认：仓库根目录下的 tmp 目录）

-minIntervalSec
PMID 处理/重试之间的最小延时（秒，默认：1.0）

-maxIntervalSec
PMID 处理/重试之间的最大延时（秒，默认：3.0）

### 常见命令示例

**基础用法，指定输出目录：**

```bash
python src/fetch_pdfs.py -pmids 123456,234567,345678 -out ./pdfs
```

**从文件读取 PMID，指定详细失败报告：**

```bash
python src/fetch_pdfs.py -pmf ./pmid_list.tsv -out ./pdfs -errors ./failed.tsv -failureReport ./failed_reasons.tsv
```

**启用浏览器兜底并延长超时时间：**

```bash
python src/fetch_pdfs.py -pmf ./pmid_list.tsv -out ./pdfs -browserTimeoutSec 60 -requestTimeoutSec 45
```

**有界面模式手动过挑战页：**

```bash
python src/fetch_pdfs.py -pmids 123456 -out ./pdfs -browserHeaded -manualChallengeWaitSec 180
```

**网络较慢时增加延迟：**

```bash
python src/fetch_pdfs.py -pmf ./pmid_list.tsv -out ./pdfs -minIntervalSec 2 -maxIntervalSec 5
```

**禁用浏览器兜底，仅用 requests：**

```bash
python src/fetch_pdfs.py -pmf ./pmid_list.tsv -out ./pdfs -noBrowserFallback
```

**重试前一次失败的 PMID：**

```bash
python src/fetch_pdfs.py -pmf ./failed.tsv -out ./pdfs_retry -errors ./failed_again.tsv
```

### Elsevier API key 文件

如果希望 Elsevier 相关论文走 API 直连下载，请在仓库根目录创建 `elsevier_api_key.txt`，并把 API key 放在第一个非空行。

主脚本启动时会自动读取这个文件。仓库中提供了模板文件 `elsevier_api_key.txt.example`，可以直接复制后填写。

**配置示例：**

```bash
# 复制模板文件
cp elsevier_api_key.txt.example elsevier_api_key.txt

# 编辑并填入你的 API key（第一行非空行）
echo "your-actual-elsevier-api-key-here" > elsevier_api_key.txt

# 添加到 .gitignore 防止意外提交
echo "elsevier_api_key.txt" >> .gitignore
```

### Wiley TDM 令牌文件

如果希望 Wiley 相关论文走 API 直连下载，请在仓库根目录创建 `wiley_tdm_token.txt`，并把 Wiley TDM 令牌放在第一个非空、非注释行。

主脚本启动时会自动读取这个文件；如果文件缺失或为空，Wiley 下载会跳过，并回退到原有的 finder / 浏览器流程。

建议流程：

1. 访问 [Wiley 文本与数据挖掘资源](https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining) 申请令牌。
2. 将令牌保存到 `wiley_tdm_token.txt`。
3. 不要把令牌提交到版本控制。

**配置示例：**

```bash
# 创建令牌文件并填入你的 Wiley TDM 令牌
echo "your-actual-wiley-tdm-token-here" > wiley_tdm_token.txt

# 检查是否已添加到 .gitignore
echo "wiley_tdm_token.txt" >> .gitignore

# （可选）验证令牌是否正确加载
python -c "from wiley_api_fetch import setup_wiley_api_token; print('令牌加载成功' if setup_wiley_api_token('wiley_tdm_token.txt') else '令牌加载失败')"
```

## Warmup + 批处理流程

当目标站点需要先人工过挑战页时，建议使用：

```bash
python src/warmup_then_batch.py -pmf /path/to/input.tsv -out /path/to/output_dir
```

流程说明：

1. 第一条 PMID 先用有界面浏览器进行 warmup
2. 后续 PMID 复用同一个 Playwright profile
3. 默认把运行期临时文件放在项目 tmp 目录

**典型工作流示例：**

```bash
# 运行 warmup 和批处理，延长超时时间
python src/warmup_then_batch.py \
  -pmf ./my_pmids.tsv \
  -out ./output_pdfs \
  -warmupBrowserTimeoutSec 120 \
  -batchBrowserTimeoutSec 90

# 批处理阶段使用有界面模式便于调试
python src/warmup_then_batch.py \
  -pmf ./my_pmids.tsv \
  -out ./output_pdfs \
  --batch-headed

# 使用持久化浏览器配置，跨多次运行复用会话
python src/warmup_then_batch.py \
  -pmf ./my_pmids.tsv \
  -out ./output_pdfs \
  -profileDir ./persistent_browser_profile
```

warmup_then_batch.py 参数：

-pmf
输入 PMID 文件（必填）

-out
批处理输出目录（必填）

-errors
批处理失败文件路径（默认：输入文件名去掉后缀后追加 _failed2.tsv）

-tmpDir
临时目录（默认：仓库根目录下的 tmp 目录）

-profileDir
Playwright profile 目录（默认：tmpDir/pw_pubmed_profile）

-warmupOut
warmup 阶段输出目录（默认：tmpDir/pmid_out）

-warmupErrors
warmup 阶段失败文件（默认：tmpDir/pmid_err.tsv）

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

双列格式（PMID 和不带 .pdf 后缀的文件名之间用制表符分隔）：

12345\tArticle_One
23456\tAnother_Paper

下载失败时，-errors 输出文件为 PMF 兼容格式，可直接作为下一次重试输入。

## 输出说明

- PDF 保存到 -out 目录，文件名格式为 name.pdf
- 失败简表 TSV（默认：unfetched_pmids.tsv）
- 详细失败原因 TSV，列为：

pmid\tname\treason\turl\tnote

当前失败类别包括：

- 403_OR_CHALLENGE
- HTML_REDIRECT_ONLY
- NO_PDF_LINK_FOUND
- NETWORK_ERROR
- WILEY_TDM_DOWNLOAD_FAILED
- TDM_CLIENT_INIT_FAILED

Elsevier / Wiley API 的失败目前都会先归入通用网络/API 失败通道，然后脚本继续尝试站点规则和浏览器兜底。

## 已知限制

- 仅 requests 路径无法执行 JavaScript。
- 部分出版商流程仍需要 Playwright 兜底或人工过挑战页。
- 付费内容是否可下载取决于你的网络环境、会话状态和机构访问权限。

## 完整工作流示例

### 场景 1：使用 API 密钥下载

你拥有 Elsevier 和 Wiley 的授权，想要最大化通过 API 直连下载：

```bash
# 设置凭证文件
echo "your-elsevier-key" > elsevier_api_key.txt
echo "your-wiley-token" > wiley_tdm_token.txt

# 下载批次（启用兜底流程）
python src/fetch_pdfs.py \
  -pmf ./pmids.tsv \
  -out ./papers \
  -errors ./failed.tsv \
  -failureReport ./failed_reasons.tsv

# 查看结果
echo "下载成功的论文数："
ls -la ./papers/*.pdf | wc -l

echo "失败 PMID 及原因："
head -20 ./failed_reasons.tsv
```

### 场景 2：处理有登录保护的站点

目标站点需要一次性解决验证码或登录。使用 warmup 工作流：

```bash
# 准备 PMID 文件
cat > pmids.tsv << EOF
12345678
23456789
34567890
EOF

# 先 warmup（你手动过验证）+ 后续批处理（复用会话）
python src/warmup_then_batch.py \
  -pmf ./pmids.tsv \
  -out ./protected_site_pdfs \
  -warmupChallengeWaitSec 300 \
  -batchBrowserTimeoutSec 60

# 检查结果
wc -l protected_site_pdfs_failed2.tsv
```

### 场景 3：网络不稳定时增加延迟和重试

网络容易超时；增加延迟和重试次数：

```bash
python src/fetch_pdfs.py \
  -pmf ./pmids.tsv \
  -out ./pdfs \
  -maxRetries 5 \
  -minIntervalSec 3 \
  -maxIntervalSec 8 \
  -requestTimeoutSec 60 \
  -browserTimeoutSec 90 \
  -errors ./failed.tsv

# 单独重试失败的 PMID
python src/fetch_pdfs.py \
  -pmf ./failed.tsv \
  -out ./pdfs_retry \
  -errors ./failed2.tsv
```

### 场景 4：有界面调试 + 无界面批处理

先用有界面模式测试单个 PMID，再用无界面模式批量下载：

```bash
# 有界面模式测试单个 PMID
python src/fetch_pdfs.py \
  -pmids 12345678 \
  -out ./test \
  -browserHeaded \
  -manualChallengeWaitSec 120

# 测试成功后，无浏览器模式高速批处理
python src/fetch_pdfs.py \
  -pmf ./pmids.tsv \
  -out ./pdfs \
  -noBrowserFallback

# 需要浏览器的站点，用无界面模式 + 较长超时
python src/fetch_pdfs.py \
  -pmf ./pmids.tsv \
  -out ./pdfs \
  -browserTimeoutSec 60 \
  -errors ./failed.tsv
```

### 场景 5：大批量处理，跨多次运行复用会话

下载大量批次，跨多次运行复用浏览器会话（已认证）：

```bash
# 创建持久化浏览器配置目录
mkdir -p ./my_browser_profile

# 第一批
python src/warmup_then_batch.py \
  -pmf ./batch1.tsv \
  -out ./batch1_pdfs \
  -profileDir ./my_browser_profile \
  -warmupChallengeWaitSec 240

# 后续批次复用同一个 profile（会话状态已保存）
python src/warmup_then_batch.py \
  -pmf ./batch2.tsv \
  -out ./batch2_pdfs \
  -profileDir ./my_browser_profile \
  -warmupChallengeWaitSec 60

# 合并所有下载的 PDF
cat batch1_pdfs/*.pdf batch2_pdfs/*.pdf > combined.pdf
```
