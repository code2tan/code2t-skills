# wiki_tree 数据库设计

## 概述

将知识库节点缓存从单一 JSON 文件迁移到 SQLite，作为独立工具 `scripts/wiki_tree.py`。支持多知识空间、模糊搜索、按需同步。零配置，无需 hook。

## 表设计

```sql
-- ── 知识空间 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS spaces (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    space_id   TEXT    NOT NULL UNIQUE,          -- 飞书 space_id
    name       TEXT    NOT NULL,                 -- 空间名称
    root_token TEXT,                             -- 根节点 token（第一层节点的 parent_token）
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── 节点 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nodes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    space_id     TEXT    NOT NULL,               -- 所属空间
    node_token   TEXT    NOT NULL,               -- 飞书 node_token（全局唯一）
    parent_token TEXT    DEFAULT '',             -- 父节点 token，空字符串 = 根层级
    title        TEXT    NOT NULL,               -- 节点标题
    obj_type     TEXT    NOT NULL DEFAULT 'docx',-- docx / folder / sheet / ...
    has_child    INTEGER NOT NULL DEFAULT 0,     -- 是否有子节点
    sort_order   INTEGER NOT NULL DEFAULT 0,     -- 同级排序
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (space_id) REFERENCES spaces(space_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_token   ON nodes(node_token);
CREATE        INDEX IF NOT EXISTS idx_nodes_space    ON nodes(space_id);
CREATE        INDEX IF NOT EXISTS idx_nodes_parent   ON nodes(space_id, parent_token);
CREATE        INDEX IF NOT EXISTS idx_nodes_title    ON nodes(space_id, title);

-- ── FTS5 全文搜索 ─────────────────────────────────────────
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    title,                        -- 节点标题（分词搜索）
    space_id UNINDEXED,           -- 空间隔离，不参与分词但用于过滤
    content='nodes',              -- 外部内容表
    content_rowid='id'
);

-- 触发器：nodes 表增删改时自动同步 FTS 索引
CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, title, space_id) VALUES (new.id, new.title, new.space_id);
END;

CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, title, space_id) VALUES ('delete', old.id, old.title, old.space_id);
END;

CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, title, space_id) VALUES ('delete', old.id, old.title, old.space_id);
    INSERT INTO nodes_fts(rowid, title, space_id) VALUES (new.id, new.title, new.space_id);
END;

-- ── 同步日志 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sync_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    space_id      TEXT    NOT NULL,
    started_at    TEXT    NOT NULL,               -- 同步开始时间
    finished_at   TEXT,                           -- 同步结束时间
    status        TEXT    NOT NULL DEFAULT 'running', -- running / success / failed
    total_nodes   INTEGER NOT NULL DEFAULT 0,     -- 同步后的总节点数
    added_nodes   INTEGER NOT NULL DEFAULT 0,     -- 新增节点数
    deleted_nodes INTEGER NOT NULL DEFAULT 0,     -- 删除节点数（API 返回中已不存在的旧节点）
    updated_nodes INTEGER NOT NULL DEFAULT 0,     -- title/obj_type/has_child 有变化的节点数
    error_message TEXT,                           -- 失败原因
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sync_log_space ON sync_log(space_id, started_at);
```

## 同步策略

采用**全量拉取 + 差异对比**的方式，不使用增量 API：

```
1. 从 API 递归拉取空间完整节点树（与现有 rebuild_cache 逻辑相同）
2. 将 API 返回的节点列表与 nodes 表对比：
   - API 有、DB 无 → INSERT（added_nodes）
   - API 有、DB 有但字段变化 → UPDATE（updated_nodes）
   - DB 有、API 无 → DELETE（deleted_nodes）
3. 写入 sync_log
```

差异对比以 `node_token` 为唯一键，对比 `title`、`obj_type`、`has_child`、`parent_token`、`sort_order` 五个字段。

## FTS5 全文搜索

### 为什么需要 FTS

| | `LIKE '%keyword%'` | FTS5 |
|---|---|---|
| 中文分词 | 不支持（"线性代数" 搜不到 "线性" 开头的行） | 内置分词器，按字/词切分 |
| 英文 | 不支持词形变化 | 内置 tokenizer，`search` 匹配 `Search`、`searching` |
| 性能 | 全表扫描，无法用索引 | FTS 倒排索引，O(log n) |
| 前缀匹配 | 不支持 | `title: math*` |
| 结果排序 | 无 | 内置 `rank`（BM25） |

SQLite 内置 FTS5 模块，零额外依赖。

### 搜索查询

```sql
-- 基础搜索（按相关度排序）
SELECT n.*, fts.rank
FROM nodes_fts fts
JOIN nodes n ON n.id = fts.rowid
WHERE nodes_fts MATCH ?
  AND n.space_id = ?
ORDER BY fts.rank
LIMIT ?;
```

### FTS5 查询语法

| 用户输入 | FTS 查询 | 效果 |
|----------|----------|------|
| `线性代数` | `线性代数` | 精确匹配 |
| `math` | `math` | 子串匹配 |
| `线性` | `线性*` | 前缀匹配（用户输入 ≤3 字时自动加 `*`） |
| `01 fundamentals` | `01 AND fundamentals` | 多词 AND |
| `math OR 线性` | `math OR 线性` | 多词 OR |

`search` 命令对用户输入做简单处理：中文 ≤3 字自动追加 `*`（前缀匹配），英文保持原样（FTS5 默认支持子串）。

### 同步时重建 FTS

全量同步（`sync`）时，先清空再批量写入，触发器自动维护 FTS。但如果同步过程中断，FTS 可能不一致。`sync` 完成后执行一次 `INSERT INTO nodes_fts(nodes_fts) VALUES ('rebuild')` 确保 FTS 与 `nodes` 表完全一致。

## 工具命令

```bash
# 模糊搜索节点标题（内置按需同步）
python3 scripts/wiki_tree.py search "线性代数" --space-name "K.B.LLM DEV"
python3 scripts/wiki_tree.py search "math" --space-name "K.B.LLM DEV" --limit 10

# 手动同步（也支持直接调用）
python3 scripts/wiki_tree.py sync --space-name "K.B.LLM DEV"
python3 scripts/wiki_tree.py sync --space-id 7494564759545659393
python3 scripts/wiki_tree.py sync --all

# 查看同步历史
python3 scripts/wiki_tree.py log --space-name "K.B.LLM DEV" --limit 5

# 查看节点详情
python3 scripts/wiki_tree.py info --node-token "VhxSwcHz9iq4cEkPoHac5g25nFH"

# 列出某节点的子节点
python3 scripts/wiki_tree.py children --parent-token "Xa3SwsoFliktPKkABwHc4ecVnFd"

# 注册新空间（首次使用前）
python3 scripts/wiki_tree.py space-add --space-name "另一个知识库"
```

## 按需同步：search 内置的同步策略

`search` 是主要入口，内部集成了按需同步逻辑。零配置，无需 hook。

### 决策流程

```
search("节点名")
    │
    ├── DB 中有匹配结果？
    │   ├── 是 → 检查该空间最近一次成功同步时间
    │   │         ├── < 10 分钟 → 直接返回缓存结果
    │   │         └── ≥ 10 分钟 → 尝试获取同步锁
    │   │                          ├── 拿到锁 → sync(该空间) → 释放锁 → 重新搜索并返回
    │   │                          └── 没拿到锁 → 直接返回缓存结果（别人在同步）
    │   │
    │   └── 否 → 尝试获取同步锁
    │              ├── 拿到锁 → sync(该空间) → 释放锁 → 重新搜索并返回
    │              └── 没拿到锁 → 等待最多 60s，每 2s 重试一次搜索
    │                              ├── 等到数据 → 返回
    │                              └── 超时 → 返回空（并提示稍后重试）
```

### 关键设计点

**搜索结果优先**：DB 中已有匹配结果时，无论缓存新旧都先返回。后台异步刷新是可选的优化，当前不做——只在搜索命中且缓存过期时才触发同步。

**搜索无结果才触发同步**：这是最常见的场景——用户要找的节点是刚创建的，缓存里还没有。此时触发同步是最有价值的。

**同步锁**：用 SQLite 文件锁（`BEGIN IMMEDIATE`）实现，不引入额外的锁表。同步前在 `sync_log` 中插入一条 `status='running'` 记录作为锁标记，同步完成后更新为 `success`/`failed`。其他进程检查到有 `running` 状态的记录就知道有人在同步。

### 锁的实现

```python
def try_acquire_sync_lock(space_id):
    """尝试获取同步锁。返回 True 表示拿到锁。"""
    # 检查是否有正在进行的同步
    running = db.execute(
        "SELECT id FROM sync_log WHERE space_id = ? AND status = 'running' "
        "AND started_at > datetime('now', '-5 minutes')",
        [space_id]
    ).fetchone()
    if running:
        return False
    # 插入 running 记录作为锁
    db.execute(
        "INSERT INTO sync_log (space_id, started_at, status) VALUES (?, datetime('now'), 'running')",
        [space_id]
    )
    db.commit()
    return True

def release_sync_lock(space_id, status, **stats):
    """释放锁，更新同步结果。"""
    db.execute(
        "UPDATE sync_log SET status = ?, finished_at = datetime('now'), ... "
        "WHERE space_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
        [status, space_id]
    )
    db.commit()
```

**超时保护**：如果同步进程崩溃，`running` 记录会残留。查询锁时加了 `started_at > datetime('now', '-5 minutes')` 条件，超过 5 分钟的 `running` 记录视为无效，可以抢锁。

### 与 prepare.py 的关系

`prepare.py` 调用 `wiki_tree.py search` 查找目标父节点。由于 `search` 内置了按需同步，`prepare.py` 不需要关心缓存是否新鲜——查不到会自动触发同步。

数据流：

```
┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│  prepare.py  │ ──search──→│  wiki_tree   │ ──按需──→│  飞书 API    │
│              │ ←──结果────│  .py         │ ←──数据──│              │
└──────────────┘           │              │           └──────────────┘
                           │  SQLite      │
                           │  wiki_tree   │
                           │  .db         │
                           └──────────────┘
```

## prepare.py 的改动

- 删除 `find_in_cache()`、`find_via_api()`、`rebuild_cache()`、`resolve_space_id()`、`DEFAULT_CACHE_FILE`
- `resolve_target_node()` 改为调用 `wiki_tree.py search <name>` 获取 node_token，再调用 `lark-cli wiki +node-get` 获取 obj_token
- 删除创建子节点后的 `rebuild_cache()` 调用

## 数据库文件位置

默认 `lark-doc-to-wiki/wiki_tree.db`，可通过 `--db-path` 参数自定义。
