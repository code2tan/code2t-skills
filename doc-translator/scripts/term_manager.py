#!/usr/bin/env python3
"""
术语检测与管理工具 — 替代 doc-translator-zh 技能中的 Agent 1 (detect-terms)。

功能:
1. 从 terminology.md 导入术语到 SQLite 数据库
2. 基于 Aho-Corasick 算法的高效多模式术语匹配
3. 术语的添加、更新、删除管理

用法:
    # 查看术语库状态
    python3 term_manager.py stats

    # 扫描文本中的术语
    python3 term_manager.py scan --text "Supervised Learning and Neural Networks..."

    # 扫描文件中的术语
    python3 term_manager.py scan --file input.md --output terms.json

    # 添加术语
    python3 term_manager.py add --en "Batch Normalization" --zh "批归一化"

    # 更新术语
    python3 term_manager.py update --en "Batch Normalization" --zh "批量归一化"

    # 删除术语
    python3 term_manager.py delete --en "Batch Normalization"

    # 列出所有术语
    python3 term_manager.py list [--category "Machine Learning"]

    # 从旧版 MD 文件导入（兼容）
    python3 term_manager.py import --md old_terminology.md
"""

import re
import sys
import json
import sqlite3
import argparse
from pathlib import Path
from collections import deque, defaultdict


# ── 数据库路径 ────────────────────────────────────────────────────────
DEFAULT_DB = Path(__file__).parent.parent / "references" / "terminology.db"


def get_db(db_path=None):
    """获取数据库连接，自动创建表。"""
    db = Path(db_path) if db_path else DEFAULT_DB
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_tables(conn)
    return conn, db


def _create_tables(conn):
    """创建术语表。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT NOT NULL UNIQUE,
            chinese TEXT NOT NULL,
            notes TEXT DEFAULT '',
            category TEXT DEFAULT '',
            keep_english INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_terms_english ON terms(english);
        CREATE INDEX IF NOT EXISTS idx_terms_category ON terms(category);

        CREATE TABLE IF NOT EXISTS import_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            count INTEGER NOT NULL,
            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()


# ── Aho-Corasick 多模式匹配算法 (纯 Python 实现) ──────────────────────

class AhoCorasickAutomaton:
    """
    Aho-Corasick 自动机 — 用于从大量关键词中高效扫描文本。

    时间复杂度:
    - 构建: O(Σ|pattern|) — 所有模式串长度之和
    - 匹配: O(|text| + z) — 文本长度 + 匹配次数

    比逐个 re.search 快 N 倍 (N=术语数量)。
    """

    def __init__(self):
        self._goto = {}      # 转移函数: state -> {char -> next_state}
        self._fail = {}      # 失败函数: state -> fail_state
        self._output = {}    # 输出函数: state -> [(pattern, meta)]
        self._states = 0     # 状态计数

    def build(self, patterns):
        """
        构建自动机。

        Args:
            patterns: list of (pattern_string, metadata) 元组
        """
        self._goto = {0: {}}
        self._fail = {0: 0}
        self._output = {0: []}
        self._states = 0

        # 步骤 1: 构建 Trie (goto 函数)
        for pattern, meta in patterns:
            pattern_lower = pattern.lower()
            current = 0
            for char in pattern_lower:
                if char not in self._goto[current]:
                    self._states += 1
                    new_state = self._states
                    self._goto[current][char] = new_state
                    self._goto[new_state] = {}
                    self._output[new_state] = []
                    self._fail[new_state] = 0
                current = self._goto[current][char]
            self._output[current].append((pattern, meta))

        # 步骤 2: 构建失败函数 (BFS)
        queue = deque()

        # 深度为 1 的状态，失败指向 0
        for char, state in self._goto[0].items():
            self._fail[state] = 0
            queue.append(state)

        # BFS 处理更深层
        while queue:
            r = queue.popleft()
            for char, s in self._goto[r].items():
                queue.append(s)
                # 沿着失败链查找
                state = self._fail[r]
                while state != 0 and char not in self._goto.get(state, {}):
                    state = self._fail[state]
                self._fail[s] = self._goto.get(state, {}).get(char, 0)
                if self._fail[s] == s:
                    self._fail[s] = 0
                # 合并输出
                self._output[s] = self._output[s] + self._output[self._fail[s]]

    def search(self, text):
        """
        在文本中搜索所有匹配的模式。

        Args:
            text: 输入文本

        Returns:
            list of (start_pos, end_pos, pattern, metadata)
            按在文本中出现的位置排序。
        """
        results = []
        current = 0
        text_lower = text.lower()

        for i, char in enumerate(text_lower):
            # 沿失败链回退直到找到匹配或回到根
            while current != 0 and char not in self._goto.get(current, {}):
                current = self._fail[current]
            current = self._goto.get(current, {}).get(char, 0)

            # 收集所有匹配
            if self._output[current]:
                for pattern, meta in self._output[current]:
                    pattern_len = len(pattern)
                    start = i - pattern_len + 1
                    results.append((start, i + 1, pattern, meta))

        return results


# ── 术语管理 (CRUD + 导入) ────────────────────────────────────────────

def import_from_markdown(md_path, conn):
    """
    从 terminology.md 格式的术语表导入术语。

    格式:
    ## Category Name
    | English | 中文 | Notes |
    |---------|------|-------|
    | Term | 翻译 | 备注 |
    """
    content = Path(md_path).read_text(encoding='utf-8')
    sections = re.split(r'^## (.+)$', content, flags=re.MULTILINE)

    imported = 0
    current_category = ''

    for i in range(1, len(sections), 2):
        current_category = sections[i].strip()
        section_content = sections[i + 1] if i + 1 < len(sections) else ''

        for line in section_content.split('\n'):
            line = line.strip()
            if not line.startswith('|') or line.startswith('|-'):
                continue

            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) < 2:
                continue

            english = cells[0].strip()
            chinese = cells[1].strip()
            notes = cells[2].strip() if len(cells) > 2 else ''

            if not english or english.startswith('-') or '---' in english:
                continue

            keep = _should_keep_english(english, notes)

            try:
                conn.execute("""
                    INSERT OR REPLACE INTO terms (english, chinese, notes, category, keep_english)
                    VALUES (?, ?, ?, ?, ?)
                """, (english, chinese, notes, current_category, keep))
                imported += 1
            except sqlite3.IntegrityError:
                continue

    conn.execute("INSERT INTO import_log (source, count) VALUES (?, ?)",
                (str(md_path), imported))
    conn.commit()
    return imported


def _should_keep_english(english: str, notes: str) -> bool:
    """判断术语是否应该保留英文不翻译。"""
    if '不翻译' in notes or '不翻译' in english:
        return True

    # 纯大写缩写 (GAN, CNN, RNN, PCA, SVD)
    if re.match(r'^[A-Z]{2,}$', english):
        return True

    # 带连字符的缩写 (t-SNE)
    if re.match(r'^[a-z]+-[A-Z]', english):
        return True

    # CamelCase 专有名词但不是普通术语
    if re.match(r'^[A-Z][a-z]+[A-Z]', english) and len(english) < 20:
        common_terms = {
            'Layer Normalization', 'Self-Attention', 'Multi-Head Attention',
            'Positional Encoding', 'Feed-Forward Network', 'Cross-validation',
            'Semi-supervised Learning', 'Parameter-efficient Fine-tuning'
        }
        if english not in common_terms:
            return True

    return False


def add_term(conn, english, chinese, notes='', category='', keep_english=False):
    """添加新术语。"""
    try:
        conn.execute("""
            INSERT INTO terms (english, chinese, notes, category, keep_english)
            VALUES (?, ?, ?, ?, ?)
        """, (english, chinese, notes, category, int(keep_english)))
        conn.commit()
        print(f'✅ 已添加: {english} → {chinese}')
        return True
    except sqlite3.IntegrityError:
        print(f'❌ 术语已存在: {english}')
        return False


def update_term(conn, english, chinese=None, notes=None, category=None, keep_english=None):
    """更新已有术语。"""
    updates = []
    values = []

    if chinese is not None:
        updates.append('chinese = ?')
        values.append(chinese)
    if notes is not None:
        updates.append('notes = ?')
        values.append(notes)
    if category is not None:
        updates.append('category = ?')
        values.append(category)
    if keep_english is not None:
        updates.append('keep_english = ?')
        values.append(int(keep_english))

    updates.append('updated_at = CURRENT_TIMESTAMP')
    values.append(english)

    sql = f"UPDATE terms SET {', '.join(updates)} WHERE english = ?"
    cursor = conn.execute(sql, values)
    conn.commit()

    if cursor.rowcount > 0:
        print(f'✅ 已更新: {english}')
        return True
    else:
        print(f'❌ 术语不存在: {english}')
        return False


def delete_term(conn, english):
    """删除术语。"""
    cursor = conn.execute("DELETE FROM terms WHERE english = ?", (english,))
    conn.commit()

    if cursor.rowcount > 0:
        print(f'🗑️ 已删除: {english}')
        return True
    else:
        print(f'❌ 术语不存在: {english}')
        return False


def list_terms(conn, category=None):
    """列出所有术语。"""
    if category:
        rows = conn.execute("""
            SELECT english, chinese, notes, category, keep_english
            FROM terms WHERE category LIKE ?
            ORDER BY english
        """, (f'%{category}%',)).fetchall()
    else:
        rows = conn.execute("""
            SELECT english, chinese, notes, category, keep_english
            FROM terms ORDER BY category, english
        """).fetchall()

    print(f'📚 共 {len(rows)} 条术语:')
    current_cat = ''
    for row in rows:
        if row['category'] != current_cat:
            current_cat = row['category']
            print(f'\n## {current_cat}')
        keep_tag = ' [保留英文]' if row['keep_english'] else ''
        notes_tag = f" ({row['notes']})" if row['notes'] else ''
        print(f"  {row['english']}{keep_tag} → {row['chinese']}{notes_tag}")


def show_stats(conn):
    """显示统计信息。"""
    total = conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
    keep_count = conn.execute("SELECT COUNT(*) FROM terms WHERE keep_english = 1").fetchone()[0]
    categories = conn.execute("SELECT DISTINCT category FROM terms ORDER BY category").fetchall()

    print(f'📊 术语统计:')
    print(f'  总计: {total} 条')
    print(f'  保留英文: {keep_count} 条')
    print(f'  需翻译: {total - keep_count} 条')
    print(f'  分类数: {len(categories)}')
    for cat in categories:
        count = conn.execute("SELECT COUNT(*) FROM terms WHERE category = ?", (cat[0],)).fetchone()[0]
        print(f'    {cat[0]}: {count} 条')

    last_import = conn.execute("""
        SELECT source, count, imported_at FROM import_log
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    if last_import:
        print(f'  最近导入: {last_import["count"]} 条 (来自 {last_import["source"]}, {last_import["imported_at"]})')


# ── 术语匹配 (核心功能) ──────────────────────────────────────────────

def scan_text(text: str, conn) -> list:
    """
    扫描文本，找出所有命中的术语。

    Args:
        text: 输入文本
        conn: 数据库连接

    Returns:
        list of dict:
        [
            {
                "line": 123,
                "term": "Supervised Learning",
                "in_glossary": True,
                "translation": "监督学习",
                "annotate": True,
                "category": "Machine Learning / AI",
                "keep_english": False
            }
        ]
    """
    rows = conn.execute("""
        SELECT english, chinese, notes, category, keep_english
        FROM terms
        ORDER BY LENGTH(english) DESC
    """).fetchall()

    if not rows:
        return []

    # 构建自动机
    patterns = []
    term_meta = {}
    for row in rows:
        term = row['english']
        meta = {
            'chinese': row['chinese'],
            'notes': row['notes'],
            'category': row['category'],
            'keep_english': bool(row['keep_english']),
        }
        patterns.append((term, meta))
        term_meta[term] = meta

    ac = AhoCorasickAutomaton()
    ac.build(patterns)

    # 扫描全文
    matches = ac.search(text)

    # 去重 + 添加行号
    seen_terms = set()
    results = []
    lines = text.split('\n')

    # 构建行偏移表 (二分查找用)
    line_offsets = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1

    def pos_to_line(pos):
        """将字符位置转换为行号 (1-based)。"""
        lo, hi = 0, len(line_offsets) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if line_offsets[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid - 1
        return hi + 1

    for start, end, term, meta in matches:
        if term in seen_terms:
            continue
        seen_terms.add(term)

        line_num = pos_to_line(start)
        annotate = not meta['keep_english']

        results.append({
            "line": line_num,
            "term": term,
            "in_glossary": True,
            "translation": meta['chinese'],
            "annotate": annotate,
            "category": meta['category'],
            "keep_english": meta['keep_english'],
            "_start": start,  # 临时字段，用于子串去重
            "_end": end,
        })

    # 子串去重：移除被更长术语完全覆盖的短术语
    results = _deduplicate_subsumed(results)

    # 清理临时字段
    for r in results:
        r.pop('_start', None)
        r.pop('_end', None)

    results.sort(key=lambda x: x['line'])
    return results


def _deduplicate_subsumed(matches: list) -> list:
    """
    去除被更长术语完全覆盖的子串匹配。

    例如：当 "Supervised Learning" 匹配时，
    "Supervised" 如果位置重叠则移除。

    规则：如果匹配 A 的位置范围完全包含在匹配 B 中，
    且 B 比 A 长，则移除 A。
    """
    # 按长度降序排列
    sorted_matches = sorted(matches, key=lambda x: x['_end'] - x['_start'], reverse=True)

    kept = []
    for candidate in sorted_matches:
        c_start, c_end = candidate['_start'], candidate['_end']
        # 检查是否被已保留的任何术语覆盖
        is_subsumed = False
        for keeper in kept:
            k_start, k_end = keeper['_start'], keeper['_end']
            # 如果候选的起始和结束都在已保留术语的范围内
            if c_start >= k_start and c_end <= k_end:
                is_subsumed = True
                break
        if not is_subsumed:
            kept.append(candidate)

    return kept


def scan_file(filepath: str, conn) -> dict:
    """
    扫描 Markdown 文件，输出术语检测结果。

    Returns:
        dict 格式兼容 SKILL.md 翻译计划:
        {
            "total_count": 15,
            "annotate_first_occurrence": ["Supervised Learning", ...],
            "keep_english": ["PyTorch", "NumPy", ...],
            "all_terms": [...]
        }
    """
    content = Path(filepath).read_text(encoding='utf-8')
    matches = scan_text(content, conn)

    annotate_terms = []
    keep_terms = []
    all_terms = []

    for m in matches:
        entry = {
            "line": m['line'],
            "term": m['term'],
            "in_glossary": m['in_glossary'],
            "translation": m['translation'],
            "annotate": m['annotate'],
        }
        all_terms.append(entry)

        if m['keep_english']:
            keep_terms.append(m['term'])
        else:
            annotate_terms.append(m['term'])

    return {
        "total_count": len(matches),
        "annotate_first_occurrence": annotate_terms,
        "keep_english": keep_terms,
        "all_terms": all_terms,
    }


# ── CLI 入口 ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='术语检测与管理工具 — Aho-Corasick 多模式匹配'
    )
    parser.add_argument('--db', help='数据库路径 (默认: references/terminology.db)')

    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # import
    p_import = subparsers.add_parser('import', help='从旧版 Markdown 术语表导入（兼容）')
    p_import.add_argument('--md', required=True, help='terminology.md 文件路径')

    # scan
    p_scan = subparsers.add_parser('scan', help='扫描文本或文件中的术语')
    p_scan.add_argument('--text', help='要扫描的文本')
    p_scan.add_argument('--file', help='要扫描的文件路径')
    p_scan.add_argument('--output', '-o', help='输出 JSON 文件路径')

    # add
    p_add = subparsers.add_parser('add', help='添加新术语')
    p_add.add_argument('--en', required=True, help='英文术语')
    p_add.add_argument('--zh', required=True, help='中文翻译')
    p_add.add_argument('--notes', default='', help='备注')
    p_add.add_argument('--cat', default='', help='分类')
    p_add.add_argument('--keep', action='store_true', help='保留英文不翻译')

    # update
    p_update = subparsers.add_parser('update', help='更新术语')
    p_update.add_argument('--en', required=True, help='英文术语 (主键)')
    p_update.add_argument('--zh', help='新中文翻译')
    p_update.add_argument('--notes', help='新备注')
    p_update.add_argument('--cat', help='新分类')
    p_update.add_argument('--keep', action='store_true', help='标记保留英文')
    p_update.add_argument('--no-keep', action='store_true', help='取消保留英文')

    # delete
    p_delete = subparsers.add_parser('delete', help='删除术语')
    p_delete.add_argument('--en', required=True, help='英文术语')

    # list
    p_list = subparsers.add_parser('list', help='列出所有术语')
    p_list.add_argument('--category', help='按分类过滤')

    # stats
    subparsers.add_parser('stats', help='显示统计')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    conn, db_path = get_db(args.db)

    if args.command == 'import':
        count = import_from_markdown(args.md, conn)
        print(f'✅ 导入完成: {count} 条术语 → {db_path}')

    elif args.command == 'scan':
        if args.text:
            results = scan_text(args.text, conn)
            print(f'🔍 扫描到 {len(results)} 个术语:')
            for r in results:
                tag = '[保留]' if r['keep_english'] else '[翻译]'
                print(f"  行 {r['line']}: {r['term']} → {r['translation']} {tag}")
        elif args.file:
            result = scan_file(args.file, conn)
            output = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(output, encoding='utf-8')
                print(f'✅ 输出已写入: {args.output}', file=sys.stderr)
            else:
                print(output)
            # 摘要
            print(f'\n📊 术语扫描: {args.file}', file=sys.stderr)
            print(f'   总计: {result["total_count"]} 个术语', file=sys.stderr)
            print(f'   需标注首次出现: {len(result["annotate_first_occurrence"])} 个', file=sys.stderr)
            print(f'   保留英文: {len(result["keep_english"])} 个', file=sys.stderr)
        else:
            print('错误: 请提供 --text 或 --file', file=sys.stderr)
            sys.exit(1)

    elif args.command == 'add':
        add_term(conn, args.en, args.zh, args.notes, args.cat, args.keep)

    elif args.command == 'update':
        keep_val = None
        if args.keep:
            keep_val = True
        elif args.no_keep:
            keep_val = False
        update_term(conn, args.en, args.zh, args.notes, args.cat, keep_val)

    elif args.command == 'delete':
        delete_term(conn, args.en)

    elif args.command == 'list':
        list_terms(conn, args.category)

    elif args.command == 'stats':
        show_stats(conn)


if __name__ == '__main__':
    main()
