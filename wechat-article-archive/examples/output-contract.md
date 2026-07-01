# 输出契约

## 单篇 current

```text
wechat-archive/
  公众号名称/
    文章标题-哈希/
      article.md
      article.html
      metadata.json
      article.docx        # 可选
      article.pdf         # 可选
      images/
      docx-warning.txt    # 仅转换失败时出现
      pdf-warning.txt     # 仅转换失败时出现
    文章标题-哈希.zip     # 使用 --zip 时出现
```

## 批量 batch

```text
wechat-batch/
  manifest.csv
  failures.json
  index.md
  articles/
    公众号名称/
      文章标题-哈希/
        article.md
        article.html
        metadata.json
        images/
wechat-batch.zip          # 使用 --zip 时出现
```

## 历史 history

```text
wechat-history/
  history-links.txt
  history-items.json
  history-response.json   # 接口异常时出现
  history-error.txt       # 请求异常时出现
  archive/                # 使用 --archive 时出现
```
