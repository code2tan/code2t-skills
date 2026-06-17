# wiki_tree.py 使用文档

## 概述

`wiki_tree.py` 是飞书知识库节点缓存工具，基于 SQLite + FTS5 全文搜索。支持多知识空间管理、节点树缓存、模糊搜索、按需同步。

数据库文件默认位于脚本同级目录的 `../wiki_tree.db`（即 `lark-doc-to-wiki/wiki_tree.db`），可通过 `--db-path` 参数自定义。

## 命令总览

| 命令 | 用途 |
|------|------|
| `space-add` | 注册新的知识空间 |
| `sync` | 从 API 全量拉取节点树并更新缓存 |
| `search` | FTS5 全文搜索节点标题（内置按需同步） |
| `export` | 导出知识空间完整树形结构为 JSON |
| `info` | 查看单个节点的详细信息 |
| `children` | 列出某节点的直接子节点 |
| `log` | 查看同步历史记录 |

## 命令详解

### space-add — 注册知识空间

首次使用前，需要将飞书知识空间注册到本地数据库。

```bash
python3 scripts/wiki_tree.py space-add --space-name "K.B.LLM DEV"
```

该命令通过 `lark-cli wiki +space-list` 查询空间 ID，写入本地 `spaces` 表。只需执行一次，后续所有命令都可以通过 `--space-name` 或 `--space-id` 引用该空间。

**参数：**

| 参数 | 必需 | 说明 |
|------|------|------|
| `--space-name` | 是 | 飞书知识空间名称 |
| `--db-path` | 否 | 自定义数据库路径 |

**输出示例：**

```json
{"ok": true, "space_id": "7494564759545659393", "name": "K.B.LLM DEV"}
```

---

### sync — 同步节点树

从飞书 API 递归拉取知识空间的完整节点树，与本地数据库做差异对比后更新缓存。

```bash
# 同步指定空间
python3 scripts/wiki_tree.py sync --space-name "K.B.LLM DEV"

# 按 space_id 同步
python3 scripts/wiki_tree.py sync --space-id 7494564759545659393

# 同步所有已注册空间
python3 scripts/wiki_tree.py sync --all
```

**参数：**

| 参数 | 必需 | 说明 |
|------|------|------|
| `--space-name` | 三选一 | 空间名称 |
| `--space-id` | 三选一 | 空间 ID |
| `--all` | 三选一 | 同步所有已注册空间 |
| `--db-path` | 否 | 自定义数据库路径 |

**同步机制：**

- 以 `node_token` 为唯一键，对比 `title`、`obj_type`、`has_child`、`parent_token` 字段
- API 有、DB 无 → 新增（`added`）
- API 有、DB 有但字段变化 → 更新（`updated`）
- DB 有、API 无 → 删除（`deleted`）
- 同步过程受锁保护，同一空间同时只能有一个同步进程

**输出示例：**

```json
{
  "ok": true,
  "space_id": "7494564759545659393",
  "total": 156,
  "added": 3,
  "deleted": 1,
  "updated": 5
}
```

---

### search — 全文搜索

FTS5 全文搜索节点标题，支持中英文模糊匹配。内置按需同步机制——缓存过期或无结果时自动触发同步。

```bash
# 按节点名称搜索
python3 scripts/wiki_tree.py search "线性代数" --space-name "K.B.LLM DEV"

# 限制返回数量
python3 scripts/wiki_tree.py search "math" --space-name "K.B.LLM DEV" --limit 10

# 按 space_id 搜索
python3 scripts/wiki_tree.py search "设计文档" --space-id 7494564759545659393
```

**参数：**

| 参数 | 必需 | 说明 |
|------|------|------|
| `query` | 是（位置参数） | 搜索关键词 |
| `--space-name` | 二选一 | 空间名称 |
| `--space-id` | 二选一 | 空间 ID |
| `--limit` | 否 | 返回数量上限（默认 20） |
| `--db-path` | 否 | 自定义数据库路径 |

**搜索特性：**

- **中文搜索**：每个 CJK 字符独立分词并做前缀匹配，"线性" 可匹配 "线性代数"、"线性回归" 等
- **英文搜索**：FTS5 内置 tokenizer，支持词形变化和子串匹配
- **布尔查询**：支持 `AND`、`OR`、`NOT` 运算符，如 `"线性 AND 代数"`
- **FTS5 不可用时降级**：自动回退到 SQL `LIKE` 模糊匹配

**按需同步策略：**

```
search 执行
  ├── 该空间从未同步？
  │     └── 自动触发首次全量同步 → 搜索并返回
  ├── 有匹配结果 + 缓存新鲜（< 10 分钟）
  │     └── 直接返回缓存结果
  ├── 有匹配结果 + 缓存过期（≥ 10 分钟）
  │     └── 返回缓存结果，后台触发同步刷新
  └── 无匹配结果 + 缓存过期
        ├── 拿到同步锁 → 同步 → 重新搜索 → 返回
        └── 未拿到锁 → 等待其他进程同步完成（最长 60s）→ 重试
```

**输出示例：**

```json
{
  "ok": true,
  "results": [
    {
      "node_token": "VhxSwcHz9iq4cEkPoHac5g25nFH",
      "title": "线性代数基础",
      "obj_type": "docx",
      "has_child": false,
      "parent_token": "Xa3SwsoFliktPKkABwHc4ecVnFd",
      "rank": -2.5
    }
  ],
  "total": 1,
  "synced": true
}
```

---

### export — 导出树形结构

将知识空间的完整节点层级结构导出为 JSON。

```bash
# 按空间名称导出
python3 scripts/wiki_tree.py export --space-name "K.B.LLM DEV"

# 紧凑输出（单行，无缩进）
python3 scripts/wiki_tree.py export --space-name "K.B.LLM DEV" --compact

# 自定义缩进
python3 scripts/wiki_tree.py export --space-id 7494564759545659393 --indent 4
```

**参数：**

| 参数 | 必需 | 说明 |
|------|------|------|
| `--space-name` | 二选一 | 空间名称 |
| `--space-id` | 二选一 | 空间 ID |
| `--compact` | 否 | 紧凑输出，无缩进换行 |
| `--indent` | 否 | JSON 缩进空格数（默认 2） |
| `--db-path` | 否 | 自定义数据库路径 |

**输出结构：**

```json
{
  "ok": true,
  "space": {
    "space_id": "7494564759545659393",
    "name": "K.B.LLM DEV",
    "root_token": null
  },
  "node_count": 156,
  "tree": [
    {
      "node_token": "Xa3SwsoFliktPKkABwHc4ecVnFd",
      "title": "01 基础知识",
      "obj_type": "folder",
      "node_type": "origin",
      "has_child": true,
      "parent_token": "",
      "children": [
        {
          "node_token": "VhxSwcHz9iq4cEkPoHac5g25nFH",
          "title": "线性代数基础",
          "obj_type": "docx",
          "node_type": "origin",
          "has_child": false,
          "parent_token": "Xa3SwsoFliktPKkABwHc4ecVnFd"
        }
      ]
    }
  ]
}
```

节点按 `sort_order, title` 排序。`has_child` 为 `true` 的节点包含 `children` 数组，递归展开。

> **注意**：导出前需先 `sync` 该空间，否则数据库中无数据。若数据库已通过 `search` 或 `sync` 同步过则可以直接导出。

---

### info — 查看节点详情

```bash
python3 scripts/wiki_tree.py info --node-token "VhxSwcHz9iq4cEkPoHac5g25nFH"
```

**参数：**

| 参数 | 必需 | 说明 |
|------|------|------|
| `--node-token` | 是 | 飞书节点 token |
| `--db-path` | 否 | 自定义数据库路径 |

---

### children — 列出子节点

```bash
python3 scripts/wiki_tree.py children --parent-token "Xa3SwsoFliktPKkABwHc4ecVnFd"
```

**参数：**

| 参数 | 必需 | 说明 |
|------|------|------|
| `--parent-token` | 是 | 父节点 token |
| `--db-path` | 否 | 自定义数据库路径 |

---

### log — 查看同步历史

```bash
# 查看指定空间的同步历史
python3 scripts/wiki_tree.py log --space-name "K.B.LLM DEV" --limit 5

# 查看所有空间的同步历史
python3 scripts/wiki_tree.py log --limit 20
```

**参数：**

| 参数 | 必需 | 说明 |
|------|------|------|
| `--space-name` | 否 | 过滤指定空间 |
| `--space-id` | 否 | 过滤指定空间 |
| `--limit` | 否 | 返回条数（默认 10） |
| `--db-path` | 否 | 自定义数据库路径 |

---

## 典型工作流

```bash
# 1. 首次使用：注册知识空间
python3 scripts/wiki_tree.py space-add --space-name "K.B.LLM DEV"

# 2. 同步节点树（也可跳过，search 会自动触发首次同步）
python3 scripts/wiki_tree.py sync --space-name "K.B.LLM DEV"

# 3. 搜索目标节点
python3 scripts/wiki_tree.py search "线性代数" --space-name "K.B.LLM DEV"

# 4. 导出完整树形结构
python3 scripts/wiki_tree.py export --space-name "K.B.LLM DEV" > tree.json

# 5. 查看同步历史
python3 scripts/wiki_tree.py log --space-name "K.B.LLM DEV"
```

## 数据库

默认数据库文件：`lark-doc-to-wiki/wiki_tree.db`

包含四张表：
- `spaces` — 已注册的知识空间
- `nodes` — 缓存的节点数据
- `nodes_fts` — FTS5 全文索引
- `sync_log` — 同步历史记录

## 依赖

- Python 3.7+
- SQLite 3（含 FTS5 模块）
- `lark-cli`（飞书命令行工具，需在 PATH 中可用）
