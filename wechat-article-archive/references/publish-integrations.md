# 飞书 / IMA 发布集成说明

## 设计原则

- 默认先生成可复核的发布交接包，避免在没有授权时伪造线上写入结果。
- 在线写入需要用户明确提供目标飞书文档/知识库或 IMA 知识库配置，并由对应授权能力执行。
- 发布包不得包含 Cookie、token、浏览器本地存储等敏感信息。
- 写入前必须使用 `source_url`、`final_url`、标题、公众号名、发布时间或 `catalog.json` 做去重。

## publish 输出

```text
publish-package/
  index.md
  documents.jsonl
  assets.jsonl
  publish-manifest.json
  handoff-tasks.json
  handoff.md
```

字段说明：

- `documents.jsonl`：每行一篇文章，包含 `title`、`article_md`、`article_dir` 等路径信息。
- `assets.jsonl`：图片和附件清单，用于上传素材或关联知识条目。
- `publish-manifest.json`：本次发布目标、模式、文档数、素材数和目标位置。
- `handoff-tasks.json`：可由飞书/IMA 写入流程消费的机器可读任务清单。
- `handoff.md`：给用户或下一步 Agent 阅读的执行说明。

## 模式

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py publish \
  --archive wechat-batch-archive \
  --target both \
  --mode handoff \
  --destination "demo-knowledge-base" \
  --output wechat-publish-package
```

- `offline`：只整理本地文件，不表达线上写入意图。
- `handoff`：生成 `handoff-tasks.json`，供授权后的飞书/IMA 写入流程执行。
- `online-request`：记录用户希望线上写入的目标，但仍需要外部授权能力真正执行。

## 飞书写入建议

1. 使用 `lark-doc` 创建或打开目标文档 / Wiki。
2. 写入 `index.md` 作为资料库目录页。
3. 逐条读取 `documents.jsonl`，将对应 `article.md` 内容追加为章节或子文档。
4. 图片按 `assets.jsonl` 映射上传为附件或素材，并替换 Markdown 引用。
5. 写入前读取目标文档已有索引，按原文 URL 或 stable key 去重。
6. 无权限时交付离线包和 `handoff.md`。

## IMA 知识库写入建议

1. 使用 `ima-skill` 创建或选择知识库。
2. 将 `documents.jsonl` 中的文章逐篇上传为知识条目。
3. `assets.jsonl` 作为图片附件清单。
4. 使用 `catalog.json` / `source_url` 避免重复上传。
5. 无 token 或权限不足时交付离线包。

## 去重与增量更新

批量归档可启用：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py batch \
  --links links.txt \
  --output wechat-batch-archive \
  --incremental \
  --catalog wechat-batch-archive/catalog.json
```

输出：

- `catalog.json`：已归档文章索引。
- `incremental-report.json`：本轮 added / skipped / failed 明细。
- `incremental-report.md`：人类可读增量报告。

注意：`catalog.json` 不保存 Cookie/token，只保存文章 URL、标题、公众号、发布时间和本地路径等归档元数据。
