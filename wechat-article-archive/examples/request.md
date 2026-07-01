# 示例请求

## 抓取当前文章

```text
请使用 wechat-article-archive，把这篇公众号文章保存为 Markdown、HTML、JSON、Word、PDF，并输出 ZIP：
https://mp.weixin.qq.com/s/D1V-eAfJFX_PwS8DxCgJaQ
```

## 批量归档

```text
请读取 links.txt，批量归档这些公众号文章，生成 index.md、失败清单和 ZIP。
```

## 合集页导出

```text
请把这个公众号合集导出为文章链接清单：
https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&album_id=...
```

## 一键合集归档

```text
请把这个公众号合集一键归档为本地资料库，生成 index、失败清单和 ZIP：
https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&album_id=...
```

## 浏览器上下文模式

```text
我已经在真实浏览器打开了公众号历史页/合集页，请读取当前页面上下文，自动提取文章链接并归档。
```

Agent 应先使用浏览器读取工具保存当前页面 URL/HTML/正文到 JSON，再调用：

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py browser-context --input browser-context.json --output output/browser-links --archive
```

## 飞书 / IMA 发布

```text
抓取完成后，请把归档结果整理成飞书和 IMA 知识库导入包；如果我已提供目标文档或知识库，再尝试在线写入。
```

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py publish --archive output/wechat-workflow/archive --target both --output output/publish-package --zip
```

## 增量资料库更新

```text
请把这批公众号文章增量更新到已有资料库，跳过已经归档过的文章，并生成增量报告。
```

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py batch --links links.txt --output wechat-batch --incremental --catalog wechat-batch/catalog.json
```

## 指定目标的飞书 / IMA Handoff

```text
请把归档结果整理成可写入飞书文档和 IMA 知识库的 handoff 包，目标知识库是 demo-knowledge-base。
```

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py publish --archive wechat-batch --target both --mode handoff --destination "demo-knowledge-base" --output wechat-publish-package
```
