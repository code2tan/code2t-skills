---
name: lark-doc-to-wiki
description: 将飞书文档内容（含图片、引用、格式）整理迁移到知识库指定父节点下，在父节点下新建子节点并填充内容。当用户说"把这篇文章整理到知识库"、"把文档迁移到 wiki 节点"、"复制文档到知识库"、"把文章搬到知识库"、"将文档内容同步到知识库"、"保存这篇文章到知识库"、"归档文档到知识库"、"把这篇 doc 整理到 xxx 节点下"、"把文档整理过去需要处理图片"时触发。即使文档不在飞书域名下（如 doubao.com），只要路径模式包含 /docx/ 或 /wiki/ 也应使用本 skill。
allowed-tools: Bash(python3 scripts/wiki_tree.py *), Bash(python3 scripts/prepare.py *), Bash(lark-cli *), Bash(grep *), Read, Write, Grep
---

# lark-doc-to-wiki：文档整理到飞书知识库

将飞书文档（docx）的内容完整迁移到知识库指定父节点下。脚本会在父节点下**新建子节点**（使用源文档标题），然后将内容写入新节点。支持处理图片、文档引用链接、callout 高亮框、列表、表格、嵌入电子表格等所有富文本格式。嵌入电子表格会自动通过 `lark-cli sheets +csv-get` 读取数据并转为内联 HTML 表格。

## 前置条件

- 操作使用 `--as user` 身份
- **首次使用某知识空间前，必须先注册该空间**，否则 `wiki_tree.py` 找不到目标父节点：
  ```bash
  python3 scripts/wiki_tree.py space-add --space-name "<你的知识空间名>"
  ```
  `wiki_tree.py` 使用 SQLite + FTS5 缓存知识库节点结构，`space-add` 通过 API 查询空间 ID 并写入本地数据库。每个空间只需执行一次，后续自动同步。
- `prepare.py` 不再硬编码任何空间 ID，需要通过 `--target-token`（自动反查空间）或 `--target-name + --space-name` 显式指定。

## 工作流概览

整个过程分 6 个阶段，其中第一阶段由 Python 脚本自动完成（包括提取嵌入电子表格并转为内联表格）：

| 阶段 | 做什么 | 谁做 |
|------|--------|------|
| 准备 | 查找父节点 → 新建子节点 → 提取嵌入电子表格并转为内联表格 → 下载图片 → 构建 XML | `prepare.py` 脚本 |
| 验证表格 | 检查 `meta.json` 中嵌入表格转换结果，确认 `content.xml` 无残留 `<sheet` 标签 | agent |
| 写入 | 将 XML 覆写到空白子文档 | `lark-cli` |
| 图片 | 上传图片到文档末尾 → 移动到正确位置 | `lark-cli` |
| 公式 | 将含 `<latex>` 的段落设为居中 | `lark-cli` |
| 清理 | 删除临时文件 | `prepare.py --cleanup` |

## 飞书嵌入电子表格（`<sheet>`）的检测与处理

飞书文档中可以通过 `<sheet>` 标签嵌入电子表格数据。`prepare.py` 脚本会自动检测并转换这些嵌入表格为内联 HTML `<table>`，但 agent 在执行过程中也需要主动验证处理结果。

### 检测源文档是否包含嵌入电子表格

执行 `prepare.py` 后，读取 `meta.json` 中的 `embedded_sheets` 数组（用 `Read` 工具直接读 `lark_doc_to_wiki_temp/meta.json`）。

或者在 `prepare.py` 的输出中查看 `Step 4` 的日志：
- `Found N embedded sheet(s)` — 发现 N 个嵌入电子表格
- `Converted to inline table (M rows x K cols)` — 成功转换为内联表格
- `Skipped: ...` — 转换失败，原因可能是权限不足或表格为空

### 三种处理结果

| 场景 | `meta.json` 中 `converted` 字段 | 处理方式 |
|------|-------------------------------|---------|
| 源文档没有嵌入表格 | `embedded_sheets` 数组为空 | 无需额外处理 |
| 嵌入表格转换成功 | `true`，含 `rows` 和 `columns` | 已替换为 `<table>` XML，直接 overwrite |
| 嵌入表格转换失败 | `false`，含 `error` 说明 | **必须告知用户**，说明哪些表格因何原因未转换 |

### 验证转换结果

`prepare.py` 完成后，确认 `content.xml` 中不再包含 `<sheet` 标签，而是包含 `<table>` 标签。用 `Grep` 工具检查：

```
Grep pattern="<sheet"  path="lark_doc_to_wiki_temp/content.xml"  output_mode="count"
Grep pattern="<table>" path="lark_doc_to_wiki_temp/content.xml"  output_mode="count"
```

如果第一条仍能匹配到 `<sheet`，说明有嵌入表格未被正确替换，需要排查原因并手动处理（通常是因为权限不足或 sheet 标签格式异常）。

### 为什么嵌入表格需要特殊处理

飞书知识库的文档（docx）不支持 `<sheet>` 标签直接嵌入电子表格。直接在知识库文档中写入 `<sheet>` 标签会导致渲染错误或内容丢失。因此必须将其转换为知识库支持的格式——内联 HTML `<table>`。转换后的表格保留原始数据（行列结构），但不保留原始电子表格的公式、样式和交互功能。这是一个**数据迁移**操作，而非完整的功能复制。

## 第一阶段：准备

脚本自动完成：通过 `wiki_tree.py`（SQLite + FTS5 全文搜索）查找目标父节点、在父节点下新建子节点、读取源文档、提取嵌入电子表格并通过 `lark-cli sheets +csv-get` 读取数据转为内联 HTML 表格、下载所有图片、构建含图片占位和内联表格的 XML。

**重要：确保前置条件中的 `space-add` 已为目标空间执行过**，否则 `wiki_tree.py` 没有空间注册信息，搜索会失败。`prepare.py` 内部调用 `wiki_tree.py search`，该命令内置按需同步机制——缓存过期或无结果时会自动从飞书 API 拉取最新节点数据，不需要手动触发 sync。

```bash
# 按节点名称查找（必须同时指定空间）
python3 scripts/prepare.py --source-doc "<源文档URL>" --target-name "节点名称" --space-name "<知识空间名>"

# 按节点 token（自动从 API 反查空间，不需要 --space-name）
python3 scripts/prepare.py --source-doc "<源文档URL>" --target-token "<节点token>"

# 按 space-id（与 --space-name 二选一）
python3 scripts/prepare.py --source-doc "<源文档URL>" --target-name "节点名称" --space-id "<空间ID>"
```

**输出文件（在 `lark_doc_to_wiki_temp/` 下）：**

| 文件 | 说明 |
|------|------|
| `content.xml` | 含 `[图片占位: xxx]` 和内联表格的 XML 内容 |
| `meta.json` | 元信息：`target_doc_id`（新子节点的文档 ID）、`downloaded_images`、`embedded_sheets`（嵌入电子表格转换结果）等 |
| `img_1.png`... | 下载的图片文件 |

读取 `meta.json`，**`target_doc_id`** 就是后续所有 `docs +update` / `docs +media-insert` 需要的文档 ID。

`embedded_sheets` 数组中每个元素记录一个嵌入电子表格的转换结果：
- `converted: true` 表示成功转为内联表格，同时包含 `rows` 和 `columns` 计数
- `converted: false` 表示转换失败（如无权限访问），同时包含 `error` 说明原因

节点名称查找流程：`prepare.py` → `wiki_tree.py search`（SQLite FTS5 全文搜索，内置按需同步）→ 获取 `node_token` → `lark-cli wiki +node-get` 获取 `obj_token` 与真实 `space_id`。`wiki_tree.py` 自动管理缓存，搜索时若缓存过期或未命中会自动从飞书 API 拉取最新数据。后续创建子节点使用 API 返回的真实 `space_id`，因此本脚本支持任意知识空间，不绑定特定空间。

## 第二阶段：验证嵌入表格处理结果

在 overwrite 之前，先确认嵌入表格被正确处理（详见上文 "飞书嵌入电子表格的检测与处理" 章节）：
1. 读 `meta.json` 中 `embedded_sheets`，若有 `converted: false` 项，告知用户哪些表格未被转换
2. 用 `Grep` 检查 `content.xml` 中是否还有残留的 `<sheet` 标签
3. 只有验证通过后才进入第三阶段

## 第三阶段：写入文档内容

新创建的子节点是空白的，将准备好的 XML 覆写进去：

```bash
lark-cli docs +update --api-version v2 --doc "<target_doc_id>" --command overwrite --doc-format xml --content @lark_doc_to_wiki_temp/content.xml
```

## 第四阶段：插入并整理图片

### 4a. 将图片插入文档末尾

对 `meta.json` 中 `downloaded_images` 数组的**每张图片**执行以下命令一次（每次只插一张）：

```bash
lark-cli docs +media-insert --doc "<target_doc_id>" --file "<saved_path>" --align center
```

> 此处不需要记录返回值——下一步会通过 `+fetch --detail with-ids` 重新拉取所有 block 的最终 ID。

### 4b. 获取文档 block 结构

```bash
lark-cli docs +fetch --api-version v2 --doc "<target_doc_id>" --detail with-ids
```

从返回中找出：
- 所有 `[图片占位: xxx]` 文本 block 的 ID（用于第 4c 删除）
- 每张图片应"插入位置之前"的那个 block 的 ID（用于第 4d 移动锚点）
- 每张追加在文档末尾的图片 block 的 ID（即 `block_type=27` 的 image block）

### 4c. 删除占位文本 block

可一次性批量删除所有占位 block：

```bash
lark-cli docs +update --api-version v2 --doc "<target_doc_id>" --command block_delete --block-id "<id1>,<id2>,..."
```

### 4d. 将图片移动到正确位置

`block_move_after` 一次只能移动一组图片到一个锚点。**对每张图片单独执行一次**该命令：

```bash
lark-cli docs +update --api-version v2 --doc "<target_doc_id>" --command block_move_after --block-id "<前一个block_id>" --src-block-ids "<图片block_id>"
```

## 第五阶段：公式居中

将包含 `<latex>` 标签的 `<p>` 段落设为居中：

```bash
lark-cli docs +update --api-version v2 --doc "<target_doc_id>" --command str_replace \
  --pattern "<p><latex>" --content '<p align="center"><latex>'
```

如果原 `<p>` 已有其他属性（如 `id`），在原有属性基础上追加 `align="center"`。

## 第六阶段：验证与清理

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

1. 脚本自动提取 `<img>` 标签（兼容 `token="..."` 和 `src="..."` 两种格式）并替换为 `[图片占位: 名称]`
2. 用 `media-insert` 从本地文件上传（总是追加到末尾）
3. 用 `block_move_after` 移动到正确位置（每张图片一次命令）
4. 先删除占位 block 再移动图片，避免 block_id 变化

### 公式处理

源文档的 `<latex>` 标签嵌在 `<p>` 中，脚本不自动处理。agent 在 overwrite 后通过 `str_replace` 将 `<p><latex>` 替换为 `<p align="center"><latex>`。

## 注意事项

1. **新建子节点是安全的**：不会影响父节点已有内容，也不会影响其他同级节点
2. **`media-insert` 总是追加到末尾**：图片插入后需要用 `block_move_after` 重新定位
3. **文档引用保留**：`<cite type="doc" doc-id="xxx">` 保持原样，引用关系在新文档中有效
4. **缓存自动更新**：`wiki_tree.py` 内置按需同步机制，搜索时若缓存过期或无结果会自动从 API 拉取最新数据。
5. **嵌入电子表格**：详见上文 "飞书嵌入电子表格（`<sheet>`）的检测与处理" 章节。
6. **不绑定特定知识空间**：脚本通过 `wiki +node-get` API 实时获取真实 `space_id`，无任何硬编码空间。任何用户在任何空间使用本 skill 前，只需先 `space-add` 自己的目标空间一次。

## 参考文件

- `scripts/wiki_tree.py` — 知识库节点缓存工具（SQLite + FTS5 搜索，内置按需同步）
- `scripts/prepare.py` — 准备和清理脚本
- [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md) — 认证和全局参数
- [`../lark-doc/references/lark-doc-xml.md`](../lark-doc/references/lark-doc-xml.md) — XML 语法规则
- [`../lark-doc/references/lark-doc-fetch.md`](../lark-doc/references/lark-doc-fetch.md) — 获取文档
- [`../lark-doc/references/lark-doc-update.md`](../lark-doc/references/lark-doc-update.md) — 更新文档
- [`../lark-doc/references/lark-doc-media-insert.md`](../lark-doc/references/lark-doc-media-insert.md) — 插入图片
- [`../lark-doc/references/style/lark-doc-style.md`](../lark-doc/references/style/lark-doc-style.md) — 样式指南
