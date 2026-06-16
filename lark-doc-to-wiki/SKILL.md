---
name: lark-doc-to-wiki
description: 将飞书文档内容（含图片、引用、格式）整理迁移到知识库指定父节点下，在父节点下新建子节点并填充内容。当用户说"把这篇文章整理到知识库"、"把文档迁移到 wiki 节点"、"复制文档到知识库"、"把文章搬到知识库"、"将文档内容同步到知识库"、"保存这篇文章到知识库"、"归档文档到知识库"、"把这篇 doc 整理到 xxx 节点下"、"把文档整理过去需要处理图片"时触发。即使文档不在飞书域名下（如 doubao.com），只要路径模式包含 /docx/ 或 /wiki/ 也应使用本 skill。
allowed-tools: Bash(python3 scripts/wiki_tree.py *), Bash(python3 scripts/prepare.py *), Bash(lark-cli *), Read, Write
---

# lark-doc-to-wiki：文档整理到飞书知识库

将飞书文档（docx）的内容完整迁移到知识库指定父节点下。脚本会在父节点下**新建子节点**（使用源文档标题），然后将内容写入新节点。支持处理图片、文档引用链接、callout 高亮框、列表、表格等所有富文本格式。

## 前置条件

- 操作使用 `--as user` 身份
- **首次使用前，必须先注册知识空间**，否则 `wiki_tree.py` 找不到目标父节点：
  ```bash
  python3 scripts/wiki_tree.py space-add --space-name "K.B.LLM DEV"
  ```
  `wiki_tree.py` 使用 SQLite + FTS5 缓存知识库节点结构，`space-add` 通过 API 查询空间 ID 并写入本地数据库。只需执行一次，后续自动同步。

## 工作流概览

整个过程分 5 个阶段，其中第一阶段由 Python 脚本自动完成：

| 阶段 | 做什么 | 谁做 |
|------|--------|------|
| 准备 | 查找父节点 → 新建子节点 → 下载图片 → 构建 XML | `prepare.py` 脚本 |
| 写入 | 将 XML 覆写到空白子文档 | `lark-cli` |
| 图片 | 上传图片到文档末尾 → 移动到正确位置 | `lark-cli` |
| 公式 | 将含 `<latex>` 的段落设为居中 | `lark-cli` |
| 清理 | 删除临时文件 | `prepare.py --cleanup` |

## 第一阶段：准备

脚本自动完成：通过 `wiki_tree.py`（SQLite + FTS5 全文搜索）查找目标父节点、在父节点下新建子节点、读取源文档、下载所有图片、构建含图片占位的 XML。

**重要：确保前置条件中的 `space-add` 已执行过**，否则 `wiki_tree.py` 没有空间注册信息，搜索会失败。`prepare.py` 内部调用 `wiki_tree.py search`，该命令内置按需同步机制——缓存过期或无结果时会自动从飞书 API 拉取最新节点数据，不需要手动触发 sync。

```bash
# 按节点名称查找（推荐）
python3 scripts/prepare.py --source-doc "<源文档URL>" --target-name "节点名称"

# 按节点 token
python3 scripts/prepare.py --source-doc "<源文档URL>" --target-token "<节点token>"

# 指定知识空间
python3 scripts/prepare.py --source-doc "<源文档URL>" --target-name "节点名称" --space-name "K.B.LLM DEV"
```

**输出文件（在 `lark_doc_to_wiki_temp/` 下）：**

| 文件 | 说明 |
|------|------|
| `content.xml` | 含 `[图片占位: xxx]` 的 XML 内容 |
| `meta.json` | 元信息：`target_doc_id`（新子节点的文档 ID）、`downloaded_images` 等 |
| `img_1.png`... | 下载的图片文件 |

读取 `meta.json`，**`target_doc_id`** 就是后续所有 `docs +update` / `docs +media-insert` 需要的文档 ID。

节点名称查找流程：`prepare.py` → `wiki_tree.py search`（SQLite FTS5 全文搜索，内置按需同步）→ 获取 `node_token` → `lark-cli wiki +node-get` 获取 `obj_token`。`wiki_tree.py` 自动管理缓存，搜索时若缓存过期或未命中会自动从飞书 API 拉取最新数据。

## 第二阶段：写入文档内容

新创建的子节点是空白的，将准备好的 XML 覆写进去：

```bash
lark-cli docs +update --api-version v2 --doc "<target_doc_id>" --command overwrite --content @lark_doc_to_wiki_temp/content.xml
```

## 第三阶段：插入并整理图片

### 3a. 将图片插入文档末尾

对 `meta.json` 中 `downloaded_images` 数组的每张图片执行，记录返回的 `block_id`：

```bash
lark-cli docs +media-insert --doc "<target_doc_id>" --file "<saved_path>" --align center
```

### 3b. 获取文档 block 结构

```bash
lark-cli docs +fetch --api-version v2 --doc "<target_doc_id>" --detail with-ids
```

找到所有 `[图片占位: xxx]` block 的 ID，以及每张图片应插入位置的前一个 block 的 ID。

### 3c. 删除占位文本 block

```bash
lark-cli docs +update --api-version v2 --doc "<target_doc_id>" --command block_delete --block-id "<id1>,<id2>,..."
```

### 3d. 将图片移动到正确位置

```bash
lark-cli docs +update --api-version v2 --doc "<target_doc_id>" --command block_move_after --block-id "<前一个block_id>" --src-block-ids "<图片block_id>"
```

## 第四阶段：公式居中

将包含 `<latex>` 标签的 `<p>` 段落设为居中：

```bash
lark-cli docs +update --api-version v2 --doc "<target_doc_id>" --command str_replace \
  --pattern "<p><latex>" --content '<p align="center"><latex>'
```

如果原 `<p>` 已有其他属性（如 `id`），在原有属性基础上追加 `align="center"`。

## 第五阶段：验证与清理

```bash
# 验证
lark-cli docs +fetch --api-version v2 --doc "<target_doc_id>"

# 清理
python3 scripts/prepare.py --cleanup
```

确认：文档标题正确、图片在正确位置、文档引用链接完整、公式居中。

## 核心规则

### 操作顺序

先下载所有图片 → 再 overwrite 内容 → 再插入图片到末尾 → 再移动图片到正确位置。不要边下载边插入，要批量完成每个阶段。每个 `docs +update` 命令只做一件事。

### 图片处理

1. 脚本自动提取 `<img src="token">` 并替换为 `[图片占位: 名称]`
2. 用 `media-insert` 从本地文件上传（总是追加到末尾）
3. 用 `block_move_after` 移动到正确位置
4. 先删除占位 block 再移动图片，避免 block_id 变化

### 公式处理

源文档的 `<latex>` 标签嵌在 `<p>` 中，脚本不自动处理。agent 在 overwrite 后通过 `str_replace` 将 `<p><latex>` 替换为 `<p align="center"><latex>`。

## 注意事项

1. **新建子节点是安全的**：不会影响父节点已有内容，也不会影响其他同级节点
2. **`media-insert` 总是追加到末尾**：图片插入后需要用 `block_move_after` 重新定位
3. **文档引用保留**：`<cite type="doc" doc-id="xxx">` 保持原样，引用关系在新文档中有效
4. **缓存自动更新**：`wiki_tree.py` 内置按需同步机制，搜索时若缓存过期或无结果会自动从 API 拉取最新数据。

## 参考文件

- `scripts/wiki_tree.py` — 知识库节点缓存工具（SQLite + FTS5 搜索，内置按需同步）
- `scripts/prepare.py` — 准备和清理脚本
- [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md) — 认证和全局参数
- [`../lark-doc/references/lark-doc-xml.md`](../lark-doc/references/lark-doc-xml.md) — XML 语法规则
- [`../lark-doc/references/lark-doc-fetch.md`](../lark-doc/references/lark-doc-fetch.md) — 获取文档
- [`../lark-doc/references/lark-doc-update.md`](../lark-doc/references/lark-doc-update.md) — 更新文档
- [`../lark-doc/references/lark-doc-media-insert.md`](../lark-doc/references/lark-doc-media-insert.md) — 插入图片
- [`../lark-doc/references/style/lark-doc-style.md`](../lark-doc/references/style/lark-doc-style.md) — 样式指南
