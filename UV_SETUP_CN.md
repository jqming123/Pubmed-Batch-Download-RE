# 使用 uv 配置环境说明（中文版）

本文档整理了本仓库已完成的 uv 环境配置，以及后续的使用方法。

## 已完成内容

1. 在仓库内创建本地虚拟环境 `.venv`。
2. 安装 `fetch_pdfs.py` 运行所需依赖：
   - requests
   - beautifulsoup4
   - lxml
3. 新增 `pyproject.toml`，统一声明项目依赖。
4. 增加 uv 脚本项目配置：
   - `[tool.uv]`
   - `package = false`
5. 执行 `uv sync` 成功，生成 `uv.lock`，用于可复现安装。
6. 已验证命令可运行：
   - `uv run src/fetch_pdfs.py -h`

## 为什么需要 `package = false`

本仓库是脚本型项目，而不是可打包发布的 Python 包。
如果不设置 `package = false`，`uv sync` 可能会尝试把当前项目按可编辑包安装，从而导致构建失败。

## 当前依赖的权威来源

- `pyproject.toml`：声明依赖与 uv 行为。
- `uv.lock`：锁定后的可复现依赖版本。

## 日常使用方式

推荐直接通过 uv 运行：

```bash
uv run src/fetch_pdfs.py -pmids 22673749,9685366
```

使用文件输入模式：

```bash
uv run src/fetch_pdfs.py -pmf example_pmf.tsv
```

指定输出目录和错误文件：

```bash
uv run src/fetch_pdfs.py -pmids 22673749,9685366 -out ./tmp/pubmed_debug_out -errors ./tmp/pubmed_debug_errors.tsv -maxRetries 1 -tmpDir ./tmp
```

## 在新机器上复现环境

进入仓库根目录后执行：

```bash
uv sync
```

然后验证：

```bash
uv run src/fetch_pdfs.py -h
```

## 可选：手动激活本地虚拟环境

如果你更习惯先激活环境再运行：

```bash
source .venv/bin/activate
python src/fetch_pdfs.py -h
```

## 备注

- README 中提到 `requests3`，但当前 Python 脚本实际导入并使用的是 `requests`。
- 建议优先使用 `uv run ...`，可确保始终使用项目内受控环境。