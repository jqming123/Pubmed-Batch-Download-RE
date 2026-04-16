# Wiley TDM Client 集成清单

本文档提供了将 Wiley TDM Client 集成到 fetch_pdfs.py 的具体步骤。

## 📋 集成步骤

### 第 1 步：在 fetch_pdfs.py 顶部添加导入

在文件开头的导入部分（第 15 行之后），添加：

```python
from pmid_to_doi import pmid_to_doi
from wiley_fetch import download_wiley_pdf, setup_wiley_api_token
```

具体位置：在这行之后
```python
from browser_fetch import try_download_pdf_with_playwright
```

---

### 第 2 步：添加常量定义

在 `PROJECT_ROOT` 和 `DEFAULT_ELSEVIER_API_KEY_FILE` 定义之后（第 33-34 行），添加：

```python
DEFAULT_WILEY_TDM_TOKEN_FILE = os.path.join(PROJECT_ROOT, "wiley_tdm_token.txt")
```

---

### 第 3 步：在参数解析器中添加 Wiley 配置

在 `-elsevierApiKeyFile` 参数之后（第 127 行之后），添加：

```python
parser.add_argument(
    "-wileyTokenFile",
    help=(
        "Path to a text file that stores the Wiley TDM API token. "
        "Default: <repo>/wiley_tdm_token.txt"
    ),
    default=DEFAULT_WILEY_TDM_TOKEN_FILE,
)
```

---

### 第 4 步：在 REASON_PRIORITY 中添加 Wiley 失败标记

修改 `REASON_PRIORITY` 字典（第 29-34 行）：

```python
REASON_PRIORITY = {
    REASON_403_OR_CHALLENGE: 4,
    REASON_NETWORK_ERROR: 3,
    REASON_HTML_REDIRECT_ONLY: 2,
    REASON_NO_PDF_LINK_FOUND: 1,
    "WILEY_DOWNLOAD_FAILED": 2,  # 添加这行
}
```

---

### 第 5 步：添加 Wiley 检测函数

在 `looks_like_elsevier_article_source()` 函数附近（大约第 300+ 行），添加新函数：

```python
def looks_like_wiley_article_source(url: str, html: str = "") -> bool:
    """检测 URL 是否来自 Wiley Online Library。"""
    lowered = f"{url}\n{html}".lower()
    markers = [
        "onlinelibrary.wiley.com",
        "wiley.com",
        "analyticalsciencejournals.onlinelibrary.wiley.com",
        "febs.onlinelibrary.wiley.com",
    ]
    return any(marker in lowered for marker in markers)
```

---

### 第 6 步：在 fetch() 函数中添加 Wiley 处理

在 `fetch()` 函数中，**Elsevier 检测之后**（大约第 380-410 行），**Ovid 检测之前**，添加：

```python
    # Wiley TDM Client 下载
    if not success and looks_like_wiley_article_source(response.url, response.text):
        print("** 检测到 Wiley 源；尝试使用 Wiley TDM Client 下载 PDF")
        
        # 转换 PMID 为 DOI
        doi = pmid_to_doi(pmid)
        if doi:
            print(f"** 已转换 PMID {pmid} 为 DOI {doi}")
            
            wiley_saved = download_wiley_pdf(
                doi=doi,
                output_dir=args["out"]
            )
            
            if wiley_saved:
                print(f"** Wiley TDM 成功下载文献 {pmid}")
                return True, "", "", f"https://doi.org/{doi}"
            else:
                failure_reason = _merge_reason(failure_reason, "WILEY_DOWNLOAD_FAILED")
                failure_note = "Wiley TDM 下载失败"
                # 继续尝试其他 finders
        else:
            print(f"** 无法将 PMID {pmid} 转换为 DOI，跳过 Wiley TDM")
```

---

### 第 7 步：初始化 Wiley API 令牌

在主处理循环**之前**（大约第 160-170 行，`if not os.path.exists(args["out"]):` 之后），添加：

```python
# 加载 Wiley TDM 令牌
wiley_token_loaded = setup_wiley_api_token(args["wileyTokenFile"])
if wiley_token_loaded:
    print(f"✓ Wiley TDM API 令牌已从 {args['wileyTokenFile']} 加载")
else:
    print(f"⚠ 警告：未找到 Wiley TDM 令牌。Wiley 下载将不可用。")
    print(f"  令牌文件：{args['wileyTokenFile']}")
    print(f"  要启用 Wiley 下载：")
    print(f"    1. 从以下地址申请令牌：https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining")
    print(f"    2. 将其保存到：{args['wileyTokenFile']}")
```

---

## 🔑 配置 Wiley TDM 令牌

1. **申请令牌**：访问 https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining

2. **保存令牌**：向导已为你创建 `wiley_tdm_token.txt` 文件
   - 打开文件编辑
   - 将 `YOUR_TDM_API_TOKEN_HERE` 替换为实际的令牌字符串

3. **验证**：运行测试脚本确认令牌有效
   ```bash
   python test_wiley_integration.py
   ```

---

## 🧪 测试集成

在修改 `fetch_pdfs.py` 后，运行集成测试：

```bash
# 测试 PMID 到 DOI 的转换
python test_wiley_integration.py

# 也可以单独测试 PMID 转换
cd src
python pmid_to_doi.py 29080362
```

---

## 📊 测试用例

使用你已有的失败文献数据：

```bash
# 使用当前项目配置运行一个小批次，包含 Wiley 期刊
python src/warmup_then_batch.py \
  -pmf input_PMID_table/noPMCID_test.tsv \
  -out output/pdf_with_wiley \
  -errors output/log_info/noPMCID_test_wiley_failed.tsv
```

---

## 🐛 故障排除

### 问题：Wiley TDM 下载失败

1. 检查令牌是否有效：
   ```bash
   python test_wiley_integration.py
   ```

2. 验证使用权限：
   - PMID 对应的期刊是否来自 Wiley？
   - 你的机构是否有该期刊的订阅？

3. 检查网络连接：
   ```bash
   cd src && python -c "from pmid_to_doi import pmid_to_doi; print(pmid_to_doi('14699080'))"
   ```

### 问题：PMID 转换失败

- 某些 PMID 可能无法转换到 DOI（特别是较旧的或未在 PMC 中索引的）
- 脚本会自动降级到浏览器后备方案

### 问题：NCBI API 超时

- 批量转换时请稍微增加 `-minIntervalSec` 和 `-maxIntervalSec`
- 示例：`-minIntervalSec 2 -maxIntervalSec 5`

---

## 📝 环境变量（可选）

你也可以通过环境变量设置令牌（不编辑文件）：

```bash
# Linux/macOS
export TDM_API_TOKEN='your-actual-token-here'

# Windows PowerShell
$env:TDM_API_TOKEN='your-actual-token-here'

# Windows cmd
set TDM_API_TOKEN=your-actual-token-here
```

---

## 📚 相关资源

- **Wiley TDM Client**：https://github.com/WileyLabs/tdm-client
- **NCBI ID Converter API**：https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api/
- **Wiley 文本挖掘资源**：https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining

---

## ✅ 快速检查表

- [ ] 安装了 `wiley-tdm` 包：`uv add wiley-tdm`
- [ ] 创建了 `pmid_to_doi.py`
- [ ] 创建了 `wiley_fetch.py`
- [ ] 配置了 `wiley_tdm_token.txt`
- [ ] 运行了测试脚本：`python test_wiley_integration.py`
- [ ] 修改了 `src/fetch_pdfs.py`（按上述 7 个步骤）
- [ ] 测试了小批量下载
