# wechat-article-archive

微信公众号文章归档 Skill。支持单篇增强、显式链接批量归档、公开合集页链接导出、一键合集归档、浏览器上下文提取，以及面向飞书/IMA 的资料库发布包。

## 能力

### A. 当前文章增强

- 抓取公开可访问的公众号文章。
- 输出 Markdown、HTML、JSON 元数据。
- 图片本地化，支持重试和失败记录。
- 可选输出 DOCX、PDF。
- 可选将单篇文章目录打包为 ZIP。
- 对视频、音频、小程序、iframe 等复杂嵌入内容做占位降级。

### B. 批量归档

- 从 `links.txt` 读取文章链接。
- 自动去重。
- 支持 `--resume` 断点续抓。
- 支持 `--incremental` 增量归档，基于 `catalog.json` 跳过已入库文章。
- 支持 `--catalog` 指定跨批次复用的资料库目录索引。
- 支持随机限速。
- 生成 `manifest.csv`、`failures.json`、`index.md`、`catalog.json`、`incremental-report.md/json`。
- 支持单篇 ZIP 和整批 ZIP。

### C. 历史文章抓取

- 支持用户提供合法 Cookie、`profile_ext` URL 或 `__biz` + token 参数。
- 调用微信历史列表接口获取近期文章链接。
- 可只导出 `history-links.txt`，也可加 `--archive` 继续归档。
- 不绕过登录、验证码、付费、删除、风控或平台权限限制。

### D. 公开合集页导出与一键归档

- 支持 `mp/appmsgalbum` 公众号合集页。
- 从公开 HTML/JS 中提取文章链接，生成 `album-links.txt` 和 `album-items.json`。
- `album --archive` 可继续归档合集文章。
- `workflow` 可执行 `album -> batch -> index -> zip` 一键流程。
- 若合集页只暴露部分条目，则如实记录，不虚构完整列表。

### E. 浏览器上下文提取

- 当用户已在真实浏览器打开公众号文章、合集或历史页时，Agent 可先用浏览器读取当前页面，保存 URL/HTML/正文到 JSON。
- `browser-context` 从该 JSON 中提取公众号文章链接，不读取 Cookie、本地存储或敏感凭证。
- 可选 `--archive` 继续归档。

### F. 飞书 / IMA 发布包

- `publish` 从归档目录生成 `index.md`、`documents.jsonl`、`assets.jsonl`、`publish-manifest.json`、`handoff-tasks.json`、`HANDOFF.md`。
- 支持 `--mode offline|handoff|online-request` 和 `--destination` 描述目标飞书文档 / IMA 知识库。
- 在线写入飞书或 IMA 需要用户授权；无授权时交付离线导入包和可执行交接清单。

## 快速开始

单篇：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py current "https://mp.weixin.qq.com/s/xxxx" --formats md,html,json,docx,pdf --zip
```

兼容旧入口：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx"
```

批量：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py batch --links examples/batch-links.txt --output wechat-batch --resume --zip
```

合集页：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py album "https://mp.weixin.qq.com/mp/appmsgalbum?..." --output wechat-album --limit 20
```

合集页发现并归档：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py album "https://mp.weixin.qq.com/mp/appmsgalbum?..." --output wechat-album --archive --article-zip
```

历史链接发现：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py history \
  --profile-url "https://mp.weixin.qq.com/mp/profile_ext?..." \
  --cookie "你的合法Cookie" \
  --limit 20 \
  --output wechat-history
```

历史发现并归档：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py history \
  --profile-url "https://mp.weixin.qq.com/mp/profile_ext?..." \
  --cookie "你的合法Cookie" \
  --limit 20 \
  --archive \
  --output wechat-history
```

## 增量归档

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py batch \
  --links examples/batch-links.txt \
  --output wechat-batch \
  --incremental \
  --catalog wechat-batch/catalog.json
```

增量模式会维护 `catalog.json`，并输出 `incremental-report.md/json`。它只记录文章 URL、标题、公众号、发布时间和本地归档目录，不保存 Cookie、token 或浏览器本地存储。

## 飞书 / IMA handoff 发布

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py publish \
  --archive wechat-batch \
  --target both \
  --mode handoff \
  --destination "目标飞书文档或 IMA 知识库" \
  --output wechat-publish-package
```

生成的 `handoff-tasks.json` 可交给有授权的飞书 / IMA 写入步骤执行。Skill 不会在无授权时声称已经写入外部知识库。

## 边界

- 只处理用户有权访问的内容。
- 合集页解析依赖公开 HTML/JS 暴露内容，可能只拿到部分条目。
- 历史接口依赖登录态与微信页面参数，可能过期或变化。
- PDF/DOCX 输出以可读备份为目标，不保证完整复刻公众号复杂排版。
