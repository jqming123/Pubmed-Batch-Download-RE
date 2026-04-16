# Wiley TDM Client 与 PMID-to-DOI 集成完整指南

## 📦 已创建的新文件

本次集成为项目添加了以下新文件：

### 核心脚本（位于 `src/` 目录）

| 文件名 | 功能 | 说明 |
|------|------|------|
| **pmid_to_doi.py** | PMID 转 DOI 转换 | 使用 NCBI ID Converter API 将 PubMed ID 转换成 DOI |
| **wiley_fetch.py** | Wiley TDM 下载 | 使用 Wiley TDM Client 根据 DOI 下载 PDF |

### 配置文件

| 文件名 | 功能 | 说明 |
|------|------|------|
| **wiley_tdm_token.txt** | API 令牌 | 存放 Wiley TDM API 令牌（需手动配置）|

### 测试与文档

| 文件名 | 功能 | 说明 |
|------|------|------|
| **test_wiley_integration.py** | 集成测试 | 测试所有新功能的脚本 |
| **WILEY_SETUP_CN.md** | 中文集成指南 | 详细的 7 步集成说明 |
| **WILEY_INTEGRATION_GUIDE.md** | 英文集成指南 | 英文版集成文档 |
| **WILEY_INTEGRATION_README.md** | 本文件 | 完整说明文档 |

---

## 🚀 快速开始

### 第一步：验证安装

```bash
# 检查 wiley-tdm 包是否已安装
uv list | findstr wiley-tdm

# 应该看到类似：wiley-tdm==1.0.0
```

### 第二步：运行集成测试

```bash
# 在项目根目录运行
uv run python test_wiley_integration.py
```

**预期输出：**
- ✓ PMID 到 DOI 转换正常工作
- ✓ Wiley 源检测正常工作  
- ⚠ 令牌文件需要配置（正常，待填充）

### 第三步：配置 Wiley TDM 令牌

1. **访问申请页面**：
   https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining

2. **使用机构账户登录**并申请 TDM 令牌

3. **编辑 `wiley_tdm_token.txt`**：
   ```
   # 将以下内容替换为实际令牌
   YOUR_TDM_API_TOKEN_HERE
   ```
   替换为：
   ```
   your-actual-wiley-tdm-token-string-here
   ```

4. **保存文件**（不要提交到版本控制）

### 第四步：测试 PMID 转换

```bash
# 单个 PMID 测试
uv run python src/pmid_to_doi.py 14699080

# 应该输出：
# PMID 14699080 -> DOI 10.1084/jem.20020509
```

---

## 📚 核心模块说明

### 1. pmid_to_doi.py

**功能**：将 PubMed ID 转换成 DOI

```python
from pmid_to_doi import pmid_to_doi, pmids_to_dois

# 单个转换
doi = pmid_to_doi("14699080")
print(doi)  # 输出：10.1084/jem.20020509

# 批量转换（最多 200 个 ID）
results = pmids_to_dois(["14699080", "8240242", "23193287"])
for pmid, doi in results.items():
    print(f"{pmid} -> {doi if doi else 'Not found'}")
```

**依赖**：requests

---

### 2. wiley_fetch.py

**功能**：使用 Wiley TDM Client 下载 PDF

```python
from wiley_fetch import download_wiley_pdf, setup_wiley_api_token

# 设置 API 令牌
setup_wiley_api_token("wiley_tdm_token.txt")

# 下载单个 PDF
success = download_wiley_pdf("10.1111/jtsb.12390", output_dir="pdfs/")

# 批量下载
from wiley_fetch import download_wiley_pdfs
results = download_wiley_pdfs(
    ["10.1111/jtsb.12390", "10.1111/jlse.12141"],
    output_dir="pdfs/"
)
```

**依赖**：wiley-tdm, requests

---

## 🔧 集成到主脚本

### 需要修改的文件：`src/fetch_pdfs.py`

**修改步骤**（详见 `WILEY_SETUP_CN.md`）：

1. ✅ **导入新模块**（第 2 行）
2. ✅ **添加常量**（第 35 行）  
3. ✅ **添加参数**（第 127 行）
4. ✅ **添加检测函数**（第 300+ 行）
5. ✅ **修改 fetch() 函数**（第 380-410 行）
6. ✅ **初始化令牌**（第 160-170 行）
7. ✅ **更新失败原因优先级**（第 29 行）

**快速版修改**：

```python
# 顶部导入
from pmid_to_doi import pmid_to_doi
from wiley_fetch import download_wiley_pdf, setup_wiley_api_token

# 在 fetch() 中的 Elsevier 检测之后添加
if not success and looks_like_wiley_article_source(response.url, response.text):
    print("** Detected Wiley source; trying Wiley TDM")
    doi = pmid_to_doi(pmid)
    if doi:
        wiley_saved = download_wiley_pdf(doi, args["out"])
        if wiley_saved:
            return True, "", "", f"https://doi.org/{doi}"
```

---

## 🧪 使用示例

### 示例 1：测试单个 Wiley 期刊 PMID

```bash
# 转换 PMID 到 DOI
uv run python src/pmid_to_doi.py 14699080

# 预期输出：
# PMID 14699080 -> DOI 10.1084/jem.20020509
```

### 示例 2：批量处理发行版中的 Wiley 文献

创建文件 `wiley_pmids.txt`：
```
12694562
24117942
21362118
```

运行：
```bash
uv run python src/warmup_then_batch.py \
  -pmf wiley_pmids.txt \
  -out output/wiley_pdfs \
  -errors output/wiley_failed.tsv
```

### 示例 3：通过环境变量使用令牌

**Windows PowerShell：**
```powershell
$env:TDM_API_TOKEN='your-token-here'
uv run python src/wiley_fetch.py
```

**Linux/macOS：**
```bash
export TDM_API_TOKEN='your-token-here'
python src/wiley_fetch.py
```

---

## 📊 工作流程图

```
┌─────────────┐
│  PMID List  │
└──────┬──────┘
       │
       ▼
┌──────────────────┐
│  PMID → DOI API  │ ◄── pmid_to_doi.py
└──────┬───────────┘
       │
       ├─ DOI Found ──┐
       │              │
       │              ▼
       │         ┌────────────────┐
       │         │ Wiley TDM API  │ ◄── wiley_fetch.py
       │         └────────┬───────┘
       │                  │
       │                  ├─ Download OK ──┐
       │                  │                 │
       │                  │                 ▼
       │                  │            [PDF Saved]
       │                  │
       │                  └─ Failed ───┐
       │                               │
       └─ No DOI ─────────────┬────────┘
                              │
                              ▼
                        [Browser Fallback]
                              │
                              ▼
                         [Final Result]
```

---

## ✅ 检查清单

集成完整性检查：

- [ ] **pmid_to_doi.py** 已创建（`src/` 目录）
- [ ] **wiley_fetch.py** 已创建（`src/` 目录）
- [ ] **wiley_tdm_token.txt** 已创建且配置实际令牌
- [ ] **test_wiley_integration.py** 运行成功
- [ ] **fetch_pdfs.py** 已按 7 步修改
- [ ] 令牌文件已添加到 `.gitignore`（重要！）
- [ ] 测试运行成功

---

## 🐛 故障排除

### 问题：ModuleNotFoundError: No module named 'wiley_tdm'

**解决**：确保用 `uv run` 执行，或激活虚拟环境：
```bash
uv run python test_wiley_integration.py
```

### 问题：PMID 无法转换为 DOI

**原因**：
- 较老的 PMID 可能无法转换
- 某些 PMID 无法在 NCBI 系统中找到

**解决**：这是正常行为，脚本会自动降级到其他下载方法

### 问题：Wiley 下载失败

**检查**：
1. 令牌是否正确配置？
2. 机构是否有 Wiley 期刊订阅？
3. 网络连接是否正常？

**调试**：
```bash
uv run python test_wiley_integration.py
```

### 问题：令牌文件被意外提交

**紧急处理**：
```bash
# 从 git 历史中删除敏感文件
git rm --cached wiley_tdm_token.txt
echo "wiley_tdm_token.txt" >> .gitignore
git add .gitignore
git commit -m "Remove wiley token from git tracking"
git push
```

---

## 📈 性能考虑

### PMID 到 DOI 转换的速率限制

- NCBI API：无严格限制，但建议间隔 1-3 秒
- 批处理：默认已实现，最多 200 个 ID/请求

### Wiley TDM 下载的速率限制

- 根据 Wiley 服务条款，下载频率可能受限
- 推荐参数：
  ```bash
  -minIntervalSec 2.0 -maxIntervalSec 5.0
  ```

---

## 📖 相关资源

| 资源 | 链接 |
|------|------|
| **Wiley TDM Client** | https://github.com/WileyLabs/tdm-client |
| **NCBI ID Converter API** | https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api/ |
| **Wiley 文本挖掘** | https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining |
| **项目主页** | [本项目] |

---

## 📝 许可证

本集成遵循项目原许可证。Wiley TDM Client 使用 MIT 许可证。

---

## ✨ 进阶技巧

### 为特定出版商启用记录日志

```python
import logging

# 启用调试日志
logging.basicConfig(level=logging.DEBUG)

# 只记录 pmid_to_doi 模块
logging.getLogger("pmid_to_doi").setLevel(logging.DEBUG)
```

### 缓存 PMID-DOI 映射（改进性能）

```python
from pmid_to_doi import pmid_to_doi
import json

# 构建缓存
doi_cache = {}
for pmid in pmids:
    doi = pmid_to_doi(pmid)
    if doi:
        doi_cache[pmid] = doi

# 保存缓存
with open("pmid_doi_cache.json", "w") as f:
    json.dump(doi_cache, f)
```

### 自定义用户代理（如需要）

```python
# 在 wiley_fetch.py 中修改
from wiley_tdm import TDMClient

# 如果 TDMClient 支持用户代理参数
client = TDMClient(user_agent="MyBot/1.0")
```

---

**最后更新**：2026-04-15  
**维护者**：Pubmed Batch Download Team
