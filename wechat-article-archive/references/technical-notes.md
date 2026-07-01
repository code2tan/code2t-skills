# 技术方案说明

## A. 当前文章抓取增强

输入公众号文章 URL 后，请求 HTML 页面并解析：

- 标题：`#activity-name` 或页面变量。
- 公众号名称：`#js_name` 或页面变量。
- 作者：`#js_author_name` 或页面变量。
- 正文：`#js_content`。
- 图片：`data-src`、`src`、`data-original`。

增强点：

- 请求重试：`--retries`。
- 图片下载失败写入 `metadata.json`。
- 复杂嵌入内容替换为占位，并写入 `degraded`。
- `--formats md,html,json,docx,pdf` 控制输出格式。
- `--zip` 打包单篇目录。

## B. 批量归档增强

- `--links` 读取文本链接。
- 使用 `dict.fromkeys` 去重并保序。
- `--resume` 根据 `manifest.csv` 跳过已成功 URL。
- `--delay-min/--delay-max` 随机限速。
- 每篇文章复用 current 归档逻辑。
- 生成 `manifest.csv`、`failures.json`、`index.md`。
- `--zip` 打包整批目录。

## C. 历史文章抓取增强

- 使用用户提供的合法 Cookie。
- 支持 `--profile-url` 或 `--biz` + token 参数。
- 请求 `profile_ext?action=getmsg&f=json`。
- 解析 `general_msg_list`，提取主文章和多图文子文章。
- 输出链接清单，必要时交给 batch 归档。

## 失败处理

- 页面不可访问：返回明确错误。
- 正文节点缺失：提示可能需要登录或页面结构变化。
- 图片下载失败：不阻断正文归档，记录到 metadata。
- 历史接口异常：保存响应或错误文件。
