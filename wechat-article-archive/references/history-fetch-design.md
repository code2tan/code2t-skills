# 历史文章抓取增强设计

## 目标

在用户提供合法登录态的前提下，尝试从微信公众号历史消息接口获取近期文章链接，并交给 batch 流程归档。

## 支持输入

- `--profile-url`：从用户合法浏览器会话中复制的 `profile_ext` 链接。
- `--biz`：公众号 `__biz`。
- `--cookie`：用户合法 Cookie，history 模式必需。
- `--appmsg-token`、`--pass-ticket`、`--uin`、`--key`、`--scene`：可选页面参数。
- `--offset`、`--count`、`--limit`：分页控制。

## 请求逻辑

1. 优先使用 `--profile-url`，在原 URL 上覆盖 `action=getmsg&f=json&offset=&count=`。
2. 若没有 profile URL，则使用 `--biz` 拼接 `https://mp.weixin.qq.com/mp/profile_ext?action=getmsg...`。
3. 使用用户 Cookie 发起请求。
4. 解析 `general_msg_list` 中的 `app_msg_ext_info` 和 `multi_app_msg_item_list`。
5. 输出 `history-links.txt` 和 `history-items.json`。
6. 如指定 `--archive`，复用 batch 流程继续归档。

## 合规边界

- 不绕过登录态。
- 不破解验证码。
- 不绕过付费、删除、权限或平台风控。
- Cookie 与 token 可能过期，失败时输出响应或错误文件供用户判断。
