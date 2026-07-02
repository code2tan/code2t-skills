---
name: wechat-article-archive
description: "Archive public WeChat articles into Markdown, images, metadata, batch indexes, browser-context extracts, incremental catalogs, and Lark/IMA handoff packages."
version: "0.6.0"
author: "office-raccoon"
tags:
  - wechat
  - article
  - archive
  - markdown
  - batch
  - browser-context
  - lark
  - ima
---

# wechat-article-archive

## 使命

把用户有权访问的微信公众号文章、合集页和浏览器页面上下文，合规归档为可长期保存、可检索、可增量更新、可写入知识库的资料库。

本技能支持七类任务：

1. **A 当前文章增强**：抓取一篇公开可访问文章，输出 Markdown / HTML / JSON / DOCX / PDF / ZIP，并本地化图片。
2. **B 批量归档增强**：读取 `links.txt`，批量抓取、去重、断点续抓、随机限速，生成索引与失败清单。
3. **C 历史文章增强**：在用户提供合法 Cookie、profile URL 或 token 参数时，尝试调用微信历史列表接口发现近期文章，再可选批量归档。
4. **D 合集页增强**：从公开 `appmsgalbum` 合集页导出文章链接清单，并可选归档。
5. **E 浏览器上下文增强**：从用户合法可见的真实浏览器页面上下文中提取文章链接，降低手动复制 Cookie/token 的门槛。
6. **F 资料库发布增强**：生成飞书 / IMA 知识库发布包、`handoff-tasks.json` 和 `HANDOFF.md`，支持授权后的真实写入交接。
7. **G 增量资料库增强**：维护 `catalog.json`，跳过已入库文章，输出 `incremental-report.md/json`。

## 触发条件

当用户提出以下需求时使用本技能：

- 保存、下载、归档微信公众号文章。
- 把公众号文章转 Markdown / HTML / Word / PDF。
- 批量导出一组公众号文章链接。
- 从一篇公众号文章、公众号合集页、公众号历史页或浏览器上下文尝试提取文章链接。
- 将公众号内容整理为飞书文档、IMA 知识库或本地资料库。
- 对已有资料库做增量更新，避免重复归档或重复写入。

## 不适用场景

- 绕过登录、验证码、付费墙、删除文章或权限限制。
- 承诺抓取某公众号全部历史文章。
- 未经授权高频批量抓取。
- 复刻公众号复杂排版到像素级一致。
- 在未获得用户授权和目标空间权限前，声称已完成飞书 / IMA 外部写入。

## 默认执行流程

> 单篇文章默认直接保存到当前工作目录：文章落到 `./账号名/标题-digest/` 下，不创建额外的归档根目录。批量、合集、发布等多文件任务默认在当前目录下创建对应名称的子目录（如 `wechat-batch-archive/`）以容纳索引与清单文件，避免污染工作区；任何任务都可用 `--output <目录>` 覆盖输出位置。

### 1. 当前文章归档

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py current "<url>" --formats md,html,json --zip
```

### 2. 批量文章归档

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py batch \
  --links examples/batch-links.txt \
  --output wechat-batch-archive \
  --formats md,html,json,docx,pdf \
  --resume \
  --article-zip \
  --zip
```

### 3. 增量资料库更新

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py batch \
  --links examples/batch-links.txt \
  --output wechat-batch-archive \
  --incremental \
  --catalog wechat-batch-archive/catalog.json
```

输出：

```text
catalog.json
incremental-report.md
incremental-report.json
manifest.csv
failures.json
index.md
```

### 4. 合集页导出与归档

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py album \
  "https://mp.weixin.qq.com/mp/appmsgalbum?..." \
  --output wechat-album \
  --archive \
  --incremental
```

### 5. 浏览器上下文提取

当用户已经在真实浏览器中打开公众号历史页、合集页或相关文章页时，可将页面 HTML / 浏览器读取结果保存为文件，然后执行：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py browser-context \
  --input browser-page.html \
  --output wechat-browser-context \
  --archive \
  --incremental
```

原则：只处理用户授权提供的页面内容，不读取 Cookie、本地存储或敏感凭证。

### 6. 历史文章发现

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py history \
  --profile-url "<profile_ext_url>" \
  --cookie "<cookie>" \
  --limit 20 \
  --archive \
  --incremental \
  --output wechat-history
```

如果接口返回异常，需要把 `history-response.json` 或 `history-error.txt` 交给用户，并说明可能是 Cookie 过期、token 缺失、微信风控或接口变化。

### 7. 飞书 / IMA 发布 Handoff

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py publish \
  --archive wechat-batch-archive \
  --target both \
  --mode handoff \
  --destination "目标飞书文档或 IMA 知识库" \
  --output wechat-publish-package
```

输出：

```text
index.md
documents.jsonl
assets.jsonl
publish-manifest.json
handoff-tasks.json
HANDOFF.md
```

在线写入飞书或 IMA 需要用户授权；无授权时交付离线导入包和可执行交接清单。

## CLI 参数摘要

### current

- `url`：公众号文章链接。
- `--output`：输出目录。
- `--formats`：逗号分隔，支持 `md,html,json,docx,pdf`。
- `--cookie`：可选合法 Cookie。
- `--retries`：请求重试次数。
- `--dry-run`：不下载图片，仅验证解析。
- `--zip`：打包单篇文章目录。

### batch

- `--links`：links.txt 路径，必填。
- `--output`：批量归档目录。
- `--resume`：读取 manifest 跳过已成功文章。
- `--incremental`：读取/写入 catalog，跳过已入库文章。
- `--catalog`：指定跨批次复用的 `catalog.json`。
- `--delay-min` / `--delay-max`：随机限速。
- `--article-zip`：每篇文章单独 ZIP。
- `--zip`：整个批次 ZIP。

### album / browser-context / workflow / history

- 支持 `--archive` 时继续归档。
- 支持 `--incremental` 和 `--catalog` 进行资料库级去重。
- 历史模式需要用户自己的合法登录态或 profile URL。

### publish

- `--archive`：归档目录。
- `--target`：`lark` / `ima` / `both`。
- `--mode`：`offline` / `handoff` / `online-request`。
- `--destination`：目标飞书文档、Wiki、IMA 知识库名称或 ID。
- `--output`：发布包目录。
- `--zip`：打包发布包。

## 异常处理

- 找不到 `#js_content`：说明页面不可访问、需要登录、结构变化或不是公众号文章。
- 图片下载失败：保留失败记录到 `metadata.json`，正文仍输出。
- DOCX/PDF 依赖不可用：写入 warning 文件，不影响 Markdown/HTML。
- 批量模式失败：记录到 `failures.json` 和 `manifest.csv`。
- 历史模式失败：写入 `history-error.txt` 或 `history-response.json`。
- 发布模式无授权：只生成 handoff 包，不声称已写入外部系统。

## 质量门禁

交付前必须检查：

- 根目录 `SKILL.md` 存在。
- YAML front matter 可解析。
- `scripts/fetch_wechat_article.py` 语法通过。
- `current` / `batch` / `history` / `album` / `workflow` / `browser-context` / `publish` 子命令可展示 help。
- 文档包含浏览器上下文、增量资料库、飞书 / IMA handoff 和合规边界说明。
- 回归报告存在：当前文章、合集页、workflow/browser/publish、incremental-publish。
- ZIP 根层包含 `wechat-article-archive/SKILL.md`，且不包含运行态 artifacts、缓存文件或递归 ZIP。

## 合规边界

本技能只处理用户有权访问的公开或授权内容。历史文章能力依赖用户提供自己的合法登录态，不绕过任何平台限制。浏览器上下文能力只处理用户主动提供的页面内容，不读取 Cookie、本地存储或敏感凭证。飞书 / IMA 发布在未获得用户授权和目标权限前，只生成离线包与 handoff 清单，不声称已完成外部写入。对于接口变化、Cookie 过期、验证码、风控、文章删除、付费内容，不做规避承诺，只做清晰失败报告和降级建议。
