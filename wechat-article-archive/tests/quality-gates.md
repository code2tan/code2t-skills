# 发布前质量门禁

## 结构

- 根目录必须包含包级 `SKILL.md`。
- `SKILL.md` 必须包含可解析 YAML front matter。
- ZIP 根层必须是 `wechat-article-archive/SKILL.md`，不得多嵌套一层。

## 脚本

- `scripts/fetch_wechat_article.py` 必须通过 Python AST 或 `py_compile`。
- 以下命令必须可显示 help：
  - `current --help`
  - `batch --help`
  - `album --help`
  - `workflow --help`
  - `browser-context --help`
  - `publish --help`
  - `history --help`

## 当前文章回归

- `tests/regression/baseline-current-article.json` 存在。
- `article.md` / `article.html` / `metadata.json` 存在。
- `title` / `account_name` / `final_url` 非空。
- 单篇 ZIP 命名不得因标题包含小数点被截断。

## 合集页回归

- `tests/regression/album/baseline-album.json` 存在。
- `album-links.txt` 非空。
- `album-items.json` 存在。
- 受限/异常单篇链接可以作为预期失败样本，但必须记录失败原因且不能中断整体批量任务。

## Workflow / Browser / Publish 回归

- `workflow-browser-publish-baseline.json` 存在。
- workflow 能从 album 导出链接并归档至少 1 篇。
- browser-context 能从保存的浏览器页面导出链接，且不得读取 Cookie/token。
- publish 能生成 `index.md`、`documents.jsonl`、`assets.jsonl`、`publish-manifest.json`、`handoff.md`。

## 增量 / Handoff 回归

- `tests/regression/incremental-publish/run-report.json` 存在且状态为 `PASS`。
- `batch --incremental` 能生成 `catalog.json`、`incremental-report.md`、`incremental-report.json`。
- `publish --mode handoff --destination ...` 能生成 `publish-manifest.json`、`handoff-tasks.json`、`HANDOFF.md`。
- handoff 文件不得包含 Cookie、token、浏览器本地存储。

## 洁净度

- ZIP 不得包含 `.DS_Store`、`__pycache__`、`.pyc`、`.log`、`.baiduyun.uploading.cfg`。
- 发布包不得包含 Cookie、token、浏览器本地存储等敏感信息。
