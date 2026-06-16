#!/usr/bin/env python3
"""
wiki_tree: SQLite-backed wiki node cache with FTS5 full-text search.

Commands:
  search <query>       FTS5 search with on-demand sync
  sync                 Full recursive pull + diff from API
  log                  View sync history
  info                 Node details by token
  children             List child nodes
  space-add            Register a new knowledge space
  export               Export space tree structure as JSON

Database: ../wiki_tree.db (sibling to scripts/ directory)
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).parent.parent / "wiki_tree.db"
SYNC_STALE_SECONDS = 600          # 10 minutes
SYNC_LOCK_TIMEOUT_MINUTES = 5     # for crashed sync recovery
SEARCH_WAIT_TIMEOUT = 60          # max wait when no results and lock is held
SEARCH_WAIT_INTERVAL = 2          # polling interval
SHORT_QUERY_MAX_CHARS = 3         # auto-append * for short CJK queries


# ── Utilities ─────────────────────────────────────────────────

def run_lark(args, description=""):
    """Run lark-cli and return parsed JSON, or None on failure."""
    cmd = ["lark-cli"] + args
    if description:
        print(f"[{description}] Running: lark-cli {' '.join(args[:4])}...", file=sys.stderr)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"  Timeout ({description})", file=sys.stderr)
        return None
    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout)[:300]
        print(f"  Error ({description}): {error_msg}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error ({description}): {e}", file=sys.stderr)
        return None


def get_db(db_path=None):
    """Open SQLite connection, create tables if needed, return (conn, path)."""
    path = str(db_path or DEFAULT_DB)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    return conn, path


# ── Schema ────────────────────────────────────────────────────

def _create_tables(conn):
    """Create all tables, indexes, and FTS triggers. Idempotent."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS spaces (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            space_id   TEXT    NOT NULL UNIQUE,
            name       TEXT    NOT NULL,
            root_token TEXT,
            created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS nodes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            space_id     TEXT    NOT NULL,
            node_token   TEXT    NOT NULL,
            parent_token TEXT    DEFAULT '',
            title        TEXT    NOT NULL,
            obj_type     TEXT    NOT NULL DEFAULT 'docx',
            node_type    TEXT    NOT NULL DEFAULT 'origin',
            has_child    INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (space_id) REFERENCES spaces(space_id) ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_token   ON nodes(node_token);
        CREATE        INDEX IF NOT EXISTS idx_nodes_space    ON nodes(space_id);
        CREATE        INDEX IF NOT EXISTS idx_nodes_parent   ON nodes(space_id, parent_token);
        CREATE        INDEX IF NOT EXISTS idx_nodes_title    ON nodes(space_id, title);

        CREATE TABLE IF NOT EXISTS sync_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            space_id      TEXT    NOT NULL,
            started_at    TEXT    NOT NULL,
            finished_at   TEXT,
            status        TEXT    NOT NULL DEFAULT 'running',
            total_nodes   INTEGER NOT NULL DEFAULT 0,
            added_nodes   INTEGER NOT NULL DEFAULT 0,
            deleted_nodes INTEGER NOT NULL DEFAULT 0,
            updated_nodes INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_sync_log_space ON sync_log(space_id, started_at);
    """)

    # FTS5 virtual table — standalone with CJK-space-separated titles
    # We manage FTS content manually (not external content) so we can
    # insert space-separated CJK text for proper tokenization.
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                title,
                space_id UNINDEXED,
                content=''
            )
        """)
    except sqlite3.OperationalError:
        pass  # FTS5 not available; search will fall back to LIKE


def _has_fts5(conn):
    """Check if nodes_fts table exists (FTS5 available)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nodes_fts'"
    ).fetchone()
    return row is not None


def _cjk_tokenize(text):
    """Insert spaces between CJK characters for FTS5 unicode61 tokenizer.

    FTS5 unicode61 treats consecutive CJK chars as one token, making prefix
    matching impossible for multi-char queries. Spacing them out fixes this:
    "线性回归" -> "线 性 回 归" so each char is an independent token.
    """
    result = []
    for ch in text:
        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            if result and result[-1] != ' ':
                result.append(' ')
            result.append(ch)
            result.append(' ')
        else:
            result.append(ch)
    return ''.join(result).strip()


def _fts_insert_node(conn, node_id, title, space_id):
    """Insert a node title into FTS index with CJK tokenization."""
    if not _has_fts5(conn):
        return
    tokenized = _cjk_tokenize(title)
    conn.execute(
        "INSERT INTO nodes_fts(rowid, title, space_id) VALUES (?, ?, ?)",
        [node_id, tokenized, space_id]
    )


def _fts_delete_node(conn, node_id):
    """Delete a node from FTS index."""
    if not _has_fts5(conn):
        return
    conn.execute("INSERT INTO nodes_fts(nodes_fts, rowid, title, space_id) VALUES ('delete', ?, ?, ?)",
                 [node_id, '', ''])


# ── Space resolution ──────────────────────────────────────────

def _resolve_space_id(conn, space_name=None, space_id=None, auto_register=True):
    """Resolve space_id from name or id. Auto-registers if not found."""
    if space_id:
        return space_id

    if space_name:
        row = conn.execute(
            "SELECT space_id FROM spaces WHERE name = ?", [space_name]
        ).fetchone()
        if row:
            return row["space_id"]

        if auto_register:
            sid = _auto_register_space(conn, space_name)
            if sid:
                return sid

    return None


def _auto_register_space(conn, space_name):
    """Look up space by name via API and register it. Returns space_id or None."""
    print(f"  Auto-registering space '{space_name}'...", file=sys.stderr)
    result = run_lark(["wiki", "+space-list", "--format", "json"], "list-spaces")
    if not result or not result.get("ok"):
        print(f"  Failed to list spaces", file=sys.stderr)
        return None

    for s in result.get("data", {}).get("spaces", []):
        if s.get("name") == space_name:
            space_id = s["space_id"]
            conn.execute(
                "INSERT OR IGNORE INTO spaces (space_id, name) VALUES (?, ?)",
                [space_id, space_name]
            )
            conn.commit()
            print(f"  Registered space '{space_name}': {space_id}", file=sys.stderr)
            return space_id

    print(f"  Space '{space_name}' not found", file=sys.stderr)
    return None


# ── Sync lock ─────────────────────────────────────────────────

def _try_acquire_lock(conn, space_id):
    """Try to acquire sync lock. Returns True on success."""
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        return False

    try:
        running = conn.execute(
            "SELECT id FROM sync_log WHERE space_id = ? AND status = 'running' "
            "AND started_at > datetime('now', 'localtime', ?)",
            [space_id, f'-{SYNC_LOCK_TIMEOUT_MINUTES} minutes']
        ).fetchone()
        if running:
            conn.rollback()
            return False

        conn.execute(
            "INSERT INTO sync_log (space_id, started_at, status) VALUES (?, datetime('now', 'localtime'), 'running')",
            [space_id]
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def _release_lock(conn, space_id, status, **stats):
    """Release sync lock and record results."""
    row = conn.execute(
        "SELECT id FROM sync_log WHERE space_id = ? AND status = 'running' "
        "ORDER BY id DESC LIMIT 1",
        [space_id]
    ).fetchone()
    if row:
        conn.execute(
            """UPDATE sync_log SET status = ?, finished_at = datetime('now', 'localtime'),
               total_nodes = ?, added_nodes = ?, deleted_nodes = ?,
               updated_nodes = ?, error_message = ?
               WHERE id = ?""",
            [status, stats.get('total', 0), stats.get('added', 0),
             stats.get('deleted', 0), stats.get('updated', 0),
             stats.get('error', ''), row["id"]]
        )
    conn.commit()


# ── Sync ──────────────────────────────────────────────────────

def _fetch_all_nodes(space_id):
    """Recursively pull all nodes from API. Returns flat list of dicts."""
    all_nodes = []

    def fetch_children(parent_token=None):
        kwargs = ["wiki", "+node-list", "--space-id", space_id,
                   "--page-all", "--format", "json"]
        if parent_token:
            kwargs.extend(["--parent-node-token", parent_token])
        label = f"sync-nodes-{parent_token[:8] if parent_token else 'root'}"
        result = run_lark(kwargs, label)
        if not result or not result.get("ok"):
            return
        for n in result.get("data", {}).get("nodes", []):
            node = {
                "node_token": n["node_token"],
                "parent_token": n.get("parent_node_token", ""),
                "title": n["title"],
                "obj_type": n.get("obj_type", "docx"),
                "has_child": n.get("has_child", False),
                "node_type": n.get("node_type", "origin"),
            }
            all_nodes.append(node)
            if n.get("has_child"):
                fetch_children(n["node_token"])

    fetch_children()
    return all_nodes


def _sync_space(conn, space_id):
    """Sync a single space: pull all nodes, diff, update DB. Returns stats dict."""
    started = time.time()
    print(f"Syncing space {space_id}...", file=sys.stderr)

    try:
        api_nodes = _fetch_all_nodes(space_id)
    except Exception as e:
        return {"error": str(e), "total": 0, "added": 0, "deleted": 0, "updated": 0}

    api_tokens = {n["node_token"] for n in api_nodes}
    stats = {"added": 0, "deleted": 0, "updated": 0, "total": len(api_nodes)}

    # Build lookup of existing DB nodes
    db_rows = conn.execute(
        "SELECT id, node_token, title, obj_type, has_child, parent_token FROM nodes WHERE space_id = ?",
        [space_id]
    ).fetchall()
    db_by_token = {r["node_token"]: r for r in db_rows}
    db_tokens = set(db_by_token.keys())

    with conn:
        for node in api_nodes:
            existing = db_by_token.get(node["node_token"])
            if existing is None:
                cursor = conn.execute(
                    """INSERT INTO nodes (space_id, node_token, parent_token, title, obj_type, node_type, has_child)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [space_id, node["node_token"], node["parent_token"], node["title"],
                     node["obj_type"], node["node_type"], node["has_child"]]
                )
                _fts_insert_node(conn, cursor.lastrowid, node["title"], space_id)
                stats["added"] += 1
            else:
                changed = (
                    existing["title"] != node["title"] or
                    existing["obj_type"] != node["obj_type"] or
                    existing["has_child"] != node["has_child"] or
                    existing["parent_token"] != node["parent_token"]
                )
                if changed:
                    conn.execute(
                        """UPDATE nodes SET title=?, obj_type=?, has_child=?, parent_token=?,
                           updated_at=datetime('now', 'localtime') WHERE node_token=? AND space_id=?""",
                        [node["title"], node["obj_type"], node["has_child"],
                         node["parent_token"], node["node_token"], space_id]
                    )
                    # Update FTS: delete old, insert new
                    _fts_delete_node(conn, existing["id"])
                    _fts_insert_node(conn, existing["id"], node["title"], space_id)
                    stats["updated"] += 1

        # Delete nodes no longer in API
        to_delete = db_tokens - api_tokens
        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            # Delete FTS entries first
            delete_ids = [db_by_token[t]["id"] for t in to_delete if t in db_by_token]
            for nid in delete_ids:
                _fts_delete_node(conn, nid)
            conn.execute(
                f"DELETE FROM nodes WHERE space_id = ? AND node_token IN ({placeholders})",
                [space_id] + list(to_delete)
            )
            stats["deleted"] = len(to_delete)

    elapsed = time.time() - started
    print(f"Sync complete: {stats['total']} nodes, +{stats['added']} -{stats['deleted']} ~{stats['updated']} in {elapsed:.1f}s", file=sys.stderr)
    return stats


def cmd_sync(args):
    """Handle sync command."""
    conn, db_path = get_db(args.db_path)

    if args.all:
        spaces = conn.execute("SELECT space_id, name FROM spaces").fetchall()
        if not spaces:
            print(json.dumps({"ok": False, "error": "No spaces registered. Use space-add first."}))
            return
        results = []
        for sp in spaces:
            if not _try_acquire_lock(conn, sp["space_id"]):
                print(f"  Space '{sp['name']}' is already being synced, skipping", file=sys.stderr)
                continue
            try:
                stats = _sync_space(conn, sp["space_id"])
                if "error" in stats:
                    _release_lock(conn, sp["space_id"], "failed", error=stats["error"])
                else:
                    _release_lock(conn, sp["space_id"], "success", **stats)
                results.append({"space_id": sp["space_id"], "name": sp["name"], **stats})
            except Exception as e:
                _release_lock(conn, sp["space_id"], "failed", error=str(e))
                results.append({"space_id": sp["space_id"], "name": sp["name"], "error": str(e)})
        print(json.dumps({"ok": True, "results": results}, ensure_ascii=False))
    else:
        space_id = _resolve_space_id(conn, args.space_name, args.space_id)
        if not space_id:
            print(json.dumps({"ok": False, "error": "Space not found. Use space-add first."}))
            return

        if not _try_acquire_lock(conn, space_id):
            print(json.dumps({"ok": False, "error": "Sync already in progress for this space"}))
            return

        try:
            stats = _sync_space(conn, space_id)
            if "error" in stats:
                _release_lock(conn, space_id, "failed", error=stats["error"])
            else:
                _release_lock(conn, space_id, "success", **stats)
            print(json.dumps({"ok": True, "space_id": space_id, **stats}, ensure_ascii=False))
        except Exception as e:
            _release_lock(conn, space_id, "failed", error=str(e))
            print(json.dumps({"ok": False, "space_id": space_id, "error": str(e)}))


# ── FTS5 Search ───────────────────────────────────────────────

def _sanitize_fts_query(query):
    """Prepare user input for FTS5 MATCH.

    CJK chars are space-separated and prefix-matched so unicode61 can
    tokenize individual characters. Latin text uses phrase matching.
    """
    query = query.strip()
    if not query:
        return query

    # If user is using FTS5 boolean operators, pass through as-is
    if re.search(r'\b(AND|OR|NOT|NEAR)\b', query, re.IGNORECASE):
        return query

    has_cjk = bool(re.search(r'[一-鿿]', query))

    if has_cjk:
        # Build prefix terms: each CJK char gets "ch"*
        chars = [ch for ch in query if '一' <= ch <= '鿿']
        tokens = [f'"{ch}"*' for ch in chars]
        return " ".join(tokens)

    safe = query.replace('"', '""')
    return f'"{safe}"'


def _last_sync_time(conn, space_id):
    """Return datetime string of last successful sync, or None."""
    row = conn.execute(
        "SELECT finished_at FROM sync_log WHERE space_id = ? AND status = 'success' ORDER BY finished_at DESC LIMIT 1",
        [space_id]
    ).fetchone()
    return row["finished_at"] if row else None


def _is_sync_stale(conn, space_id):
    """Check if last sync is older than SYNC_STALE_SECONDS."""
    last = _last_sync_time(conn, space_id)
    if not last:
        return True
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - last_dt).total_seconds() > SYNC_STALE_SECONDS
    except (ValueError, TypeError):
        return True


def _search_fts(conn, query, space_id, limit):
    """Execute FTS5 search. Returns list of Row objects, or empty list on error."""
    if not _has_fts5(conn):
        return _search_like(conn, query, space_id, limit)

    sanitized = _sanitize_fts_query(query)
    if not sanitized:
        return []

    try:
        return conn.execute(
            """SELECT n.node_token, n.title, n.obj_type, n.has_child, n.parent_token,
                      n.node_type, n.space_id, fts.rank
               FROM nodes_fts fts
               JOIN nodes n ON n.id = fts.rowid
               WHERE nodes_fts MATCH ? AND n.space_id = ?
               ORDER BY fts.rank
               LIMIT ?""",
            [sanitized, space_id, limit]
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"  FTS5 query error: {e}, falling back to LIKE", file=sys.stderr)
        return _search_like(conn, query, space_id, limit)


def _search_like(conn, query, space_id, limit):
    """Fallback LIKE search when FTS5 is unavailable."""
    pattern = f"%{query}%"
    return conn.execute(
        """SELECT node_token, title, obj_type, has_child, parent_token,
                  node_type, space_id, NULL AS rank
           FROM nodes WHERE space_id = ? AND title LIKE ?
           ORDER BY title LIMIT ?""",
        [space_id, pattern, limit]
    ).fetchall()


def _format_results(rows, synced=False):
    """Format search results as JSON-serializable dict."""
    results = []
    for r in rows:
        results.append({
            "node_token": r["node_token"],
            "title": r["title"],
            "obj_type": r["obj_type"],
            "has_child": bool(r["has_child"]),
            "parent_token": r["parent_token"],
            "rank": r["rank"] if "rank" in r.keys() and r["rank"] is not None else None,
        })
    return {"ok": True, "results": results, "total": len(results), "synced": synced}


def cmd_search(args):
    """Handle search command with on-demand sync."""
    conn, db_path = get_db(args.db_path)

    space_id = _resolve_space_id(conn, args.space_name, args.space_id)
    if not space_id:
        print(json.dumps({"ok": False, "error": "Space not found. Use space-add first."}))
        return

    limit = args.limit or 20

    # Check if space has ever been synced
    ever_synced = _last_sync_time(conn, space_id) is not None
    if not ever_synced:
        print("  Space never synced, triggering initial sync...", file=sys.stderr)
        if _try_acquire_lock(conn, space_id):
            try:
                stats = _sync_space(conn, space_id)
                if "error" in stats:
                    _release_lock(conn, space_id, "failed", error=stats["error"])
                else:
                    _release_lock(conn, space_id, "success", **stats)
            except Exception as e:
                _release_lock(conn, space_id, "failed", error=str(e))
        else:
            # Wait for another process to finish syncing
            _wait_for_sync(conn, space_id)

    # Search
    rows = _search_fts(conn, args.query, space_id, limit)

    if rows:
        if _is_sync_stale(conn, space_id):
            # Stale cache — try to sync in background but return current results
            if _try_acquire_lock(conn, space_id):
                try:
                    stats = _sync_space(conn, space_id)
                    if "error" in stats:
                        _release_lock(conn, space_id, "failed", error=stats["error"])
                    else:
                        _release_lock(conn, space_id, "success", **stats)
                    # Re-search with fresh data
                    rows = _search_fts(conn, args.query, space_id, limit)
                    print(json.dumps(_format_results(rows, synced=True), ensure_ascii=False))
                    return
                except Exception as e:
                    _release_lock(conn, space_id, "failed", error=str(e))
        # Return cached results
        print(json.dumps(_format_results(rows, synced=False), ensure_ascii=False))
    else:
        # No results — sync if cache is stale, otherwise return empty
        if not _is_sync_stale(conn, space_id):
            print(json.dumps({"ok": True, "results": [], "total": 0, "synced": False}))
            return

        if _try_acquire_lock(conn, space_id):
            try:
                stats = _sync_space(conn, space_id)
                if "error" in stats:
                    _release_lock(conn, space_id, "failed", error=stats["error"])
                else:
                    _release_lock(conn, space_id, "success", **stats)
                rows = _search_fts(conn, args.query, space_id, limit)
                print(json.dumps(_format_results(rows, synced=True), ensure_ascii=False))
                return
            except Exception as e:
                _release_lock(conn, space_id, "failed", error=str(e))
        else:
            # Someone else is syncing — wait and retry
            if _wait_for_sync(conn, space_id):
                rows = _search_fts(conn, args.query, space_id, limit)
                print(json.dumps(_format_results(rows, synced=True), ensure_ascii=False))
            else:
                print(json.dumps({"ok": True, "results": [], "total": 0, "synced": False,
                                  "hint": "Sync in progress, try again shortly"}))


def _wait_for_sync(conn, space_id):
    """Poll until sync completes or timeout. Returns True if data appeared."""
    deadline = time.time() + SEARCH_WAIT_TIMEOUT
    while time.time() < deadline:
        time.sleep(SEARCH_WAIT_INTERVAL)
        row = conn.execute(
            "SELECT status FROM sync_log WHERE space_id = ? AND status != 'running' ORDER BY id DESC LIMIT 1",
            [space_id]
        ).fetchone()
        if row:
            return True
    return False


# ── Other commands ────────────────────────────────────────────

def cmd_log(args):
    """Handle log command."""
    conn, _ = get_db(args.db_path)
    space_id = _resolve_space_id(conn, args.space_name, args.space_id, auto_register=False)

    if space_id:
        rows = conn.execute(
            "SELECT * FROM sync_log WHERE space_id = ? ORDER BY started_at DESC LIMIT ?",
            [space_id, args.limit or 10]
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY started_at DESC LIMIT ?",
            [args.limit or 10]
        ).fetchall()

    logs = [dict(r) for r in rows]
    print(json.dumps({"ok": True, "logs": logs}, ensure_ascii=False, indent=2))


def cmd_info(args):
    """Handle info command."""
    conn, _ = get_db(args.db_path)
    row = conn.execute(
        "SELECT * FROM nodes WHERE node_token = ?", [args.node_token]
    ).fetchone()
    if row:
        print(json.dumps({"ok": True, "node": dict(row)}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"ok": False, "error": "Node not found"}))


def cmd_children(args):
    """Handle children command."""
    conn, _ = get_db(args.db_path)
    rows = conn.execute(
        "SELECT node_token, title, obj_type, has_child, node_type FROM nodes "
        "WHERE parent_token = ? ORDER BY sort_order, title",
        [args.parent_token]
    ).fetchall()
    children = [dict(r) for r in rows]
    print(json.dumps({"ok": True, "children": children, "total": len(children)}, ensure_ascii=False, indent=2))


def cmd_space_add(args):
    """Handle space-add command."""
    conn, _ = get_db(args.db_path)
    space_id = _auto_register_space(conn, args.space_name)
    if space_id:
        print(json.dumps({"ok": True, "space_id": space_id, "name": args.space_name}))
    else:
        print(json.dumps({"ok": False, "error": f"Space '{args.space_name}' not found via API"}))


# ── Export ────────────────────────────────────────────────────

def _build_tree(conn, space_id, parent_token=""):
    """Recursively build a tree structure from nodes. Returns list of dicts."""
    rows = conn.execute(
        """SELECT node_token, title, obj_type, has_child, node_type, parent_token
           FROM nodes WHERE space_id = ? AND parent_token = ?
           ORDER BY sort_order, title""",
        [space_id, parent_token]
    ).fetchall()

    result = []
    for r in rows:
        node = {
            "node_token": r["node_token"],
            "title": r["title"],
            "obj_type": r["obj_type"],
            "node_type": r["node_type"],
            "has_child": bool(r["has_child"]),
            "parent_token": r["parent_token"],
        }
        if r["has_child"]:
            children = _build_tree(conn, space_id, r["node_token"])
            if children:
                node["children"] = children
        result.append(node)
    return result


def cmd_export(args):
    """Handle export command."""
    conn, _ = get_db(args.db_path)

    space_id = _resolve_space_id(conn, args.space_name, args.space_id)
    if not space_id:
        print(json.dumps({"ok": False, "error": "Space not found. Use space-add first."}))
        return

    # Get space info
    space = conn.execute(
        "SELECT space_id, name, root_token FROM spaces WHERE space_id = ?", [space_id]
    ).fetchone()

    tree = _build_tree(conn, space_id)
    node_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM nodes WHERE space_id = ?", [space_id]
    ).fetchone()["cnt"]

    output = {
        "ok": True,
        "space": {
            "space_id": space["space_id"],
            "name": space["name"],
            "root_token": space["root_token"],
        },
        "node_count": node_count,
        "tree": tree,
    }

    indent = args.indent or 2
    print(json.dumps(output, ensure_ascii=False, indent=None if args.compact else indent))


# ── CLI ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="wiki_tree: SQLite-backed wiki node cache")
    subparsers = parser.add_subparsers(dest="command")

    # search
    p = subparsers.add_parser("search", help="FTS5 search for nodes")
    p.add_argument("query", help="Search query")
    p.add_argument("--space-name", help="Space name")
    p.add_argument("--space-id", help="Space ID")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--db-path", default=str(DEFAULT_DB))

    # sync
    p = subparsers.add_parser("sync", help="Sync node tree from API")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--space-name")
    group.add_argument("--space-id")
    group.add_argument("--all", action="store_true")
    p.add_argument("--db-path", default=str(DEFAULT_DB))

    # log
    p = subparsers.add_parser("log", help="View sync history")
    p.add_argument("--space-name")
    p.add_argument("--space-id")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--db-path", default=str(DEFAULT_DB))

    # info
    p = subparsers.add_parser("info", help="Node details")
    p.add_argument("--node-token", required=True)
    p.add_argument("--db-path", default=str(DEFAULT_DB))

    # children
    p = subparsers.add_parser("children", help="List child nodes")
    p.add_argument("--parent-token", required=True)
    p.add_argument("--db-path", default=str(DEFAULT_DB))

    # space-add
    p = subparsers.add_parser("space-add", help="Register a new knowledge space")
    p.add_argument("--space-name", required=True)
    p.add_argument("--db-path", default=str(DEFAULT_DB))

    # export
    p = subparsers.add_parser("export", help="Export space tree structure as JSON")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--space-name")
    group.add_argument("--space-id")
    p.add_argument("--compact", action="store_true", help="Output without indentation")
    p.add_argument("--indent", type=int, default=2, help="JSON indent level (default 2)")
    p.add_argument("--db-path", default=str(DEFAULT_DB))

    args = parser.parse_args()

    if args.command == "search":
        cmd_search(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "info":
        cmd_info(args)
    elif args.command == "children":
        cmd_children(args)
    elif args.command == "space-add":
        cmd_space_add(args)
    elif args.command == "export":
        cmd_export(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
