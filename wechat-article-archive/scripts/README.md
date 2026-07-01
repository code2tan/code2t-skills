# scripts

## current

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py current "https://mp.weixin.qq.com/s/xxxx" --formats md,html,json,docx,pdf --zip
```

## batch

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py batch --links examples/batch-links.txt --resume --zip
```

## album

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py album "https://mp.weixin.qq.com/mp/appmsgalbum?..." --output output/wechat-album --limit 20
```

加 `--archive` 后会把导出的 `album-links.txt` 交给 batch 归档。

## history

```bash
$BOX_AGENT_PYTHON scripts/fetch_wechat_article.py history --profile-url "https://mp.weixin.qq.com/mp/profile_ext?..." --cookie "YOUR_COOKIE" --limit 20
```

history 模式需要用户自己的合法登录态。不要把 Cookie 写入仓库或交付包。
