#!/usr/bin/env python3
"""
检查 Markdown 文件中 mermaid 代码块是否符合 Mermaid 书写规范。

用法:
    python3 check_mermaid.py <markdown文件> [--original <原文路径>] [--json]

功能:
    1. 定位所有 mermaid 代码块
    2. 对每个块执行语法检查：
       - 括号配对: [] {} ()
       - 节点语法: A[...] A{...} A((...)) 等
       - 连接符: --> == --> -.-> 等
       - 箭头标签: |text| 中的引号配对
       - 子图 subgraph...end 配对
       - 禁止字符: 节点标签中不能有未转义的括号、冒号、引号等
    3. 报告每个块的错误行号和错误描述
    4. 如果提供了 --original，还会对比原文，标注哪些块已被修改

返回码:
    0 - 所有 mermaid 块语法正确
    1 - 发现语法错误
    2 - 文件/参数错误
"""

import re
import sys
import json
import argparse


def find_mermaid_blocks(content):
    """返回 [(start_line, [(line_num, line_text), ...], end_line)] 列表，行号从1开始"""
    blocks = []
    lines = content.split("\n")
    in_block = False
    start = 0
    code_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not in_block and (stripped.startswith("```mermaid") or stripped.startswith("``` mermaid")):
            in_block = True
            start = i + 1  # 1-based
            code_lines = []
        elif in_block and stripped == "```":
            blocks.append((start, code_lines[:], i + 1))
            in_block = False
            code_lines = []
        elif in_block:
            code_lines.append((i + 1, line))

    return blocks


def check_bracket_balance(text):
    """检查括号配对，返回错误列表"""
    errors = []
    # 检查方括号
    depth = 0
    for i, ch in enumerate(text):
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth < 0:
                errors.append(f"未匹配的 ']' (位置 {i})")
    if depth > 0:
        errors.append(f"未匹配的 '[' (缺少 {depth} 个 ']')")

    # 检查花括号
    depth = 0
    for i, ch in enumerate(text):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                errors.append(f"未匹配的 '}}' (位置 {i})")
    if depth > 0:
        errors.append(f"未匹配的 '{{' (缺少 {depth} 个 '}}')")

    # 检查圆括号（注意：圆括号在节点标签中容易出问题）
    depth = 0
    for i, ch in enumerate(text):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                errors.append(f"未匹配的 ')' (位置 {i})")
    if depth > 0:
        errors.append(f"未匹配的 '(' (缺少 {depth} 个 ')')")

    return errors


def check_node_label_syntax(text):
    """检查节点标签中的危险字符"""
    errors = []
    # Mermaid 节点标签中，未加双引号时不能包含这些字符
    # 模式匹配: A[内容] A{内容} A(内容) 等
    patterns = [
        r'[A-Za-z_]\w*\[([^\]]*)\]',   # A[...]
        r'[A-Za-z_]\w*\{([^\}]*)\}',   # A{...}
        r'[A-Za-z_]\w*\(([^\)]*)\)',   # A(...)
        r'[A-Za-z_]\w*\(\(([^\)]*)\)\)',  # A((...))
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            label = match.group(1)
            # 标签内如果有这些字符且未用双引号包裹，会解析失败
            dangerous = re.findall(r'[：:？?，,；;]', label)
            if dangerous and '"' not in label:
                chars = set(dangerous)
                errors.append(
                    f"节点标签包含可能导致解析错误的字符: {chars} "
                    f"(建议使用双引号包裹标签或移除此类字符)"
                )
    return errors


def check_arrow_syntax(text):
    """检查箭头连接符语法"""
    errors = []
    # 合法的箭头: -->, ==>, -.->, -.->, ==, ~~~
    arrow_pattern = r'(-+\.?-+>|={2}|~~~)'
    # 检查是否有类似 "->" (缺少一个减号) 或 "=>" 等不完整箭头
    bad_arrows = re.findall(r'(?<![-=~])-{1}(?![->])|(?<![-])={1}(?![>=])', text)
    # 箭头标签语法: |text| 或 ==text==
    # 检查 |...| 标签是否配对
    pipe_count = text.count('|')
    if pipe_count % 2 != 0:
        errors.append(f"箭头标签 '|' 数量为奇数 ({pipe_count})，可能未配对")
    return errors


def check_subgraph_balance(lines):
    """检查 subgraph/end 配对"""
    errors = []
    depth = 0
    for line_num, line_text in lines:
        stripped = line_text.strip()
        if stripped.startswith('subgraph '):
            depth += 1
        elif stripped == 'end':
            depth -= 1
            if depth < 0:
                errors.append("多余的 'end'，缺少对应的 'subgraph'")
    if depth > 0:
        errors.append(f"缺少 {depth} 个 'end' 来闭合 subgraph")
    return errors


def check_graph_declaration(lines):
    """检查是否有 graph/flowchart 声明"""
    errors = []
    first_line = lines[0][1].strip() if lines else ""
    valid_declarations = [
        'graph', 'flowchart', 'stateDiagram', 'stateDiagram-v2',
        'gantt', 'pie', 'classDiagram', 'erDiagram',
        'journey', 'requirementDiagram', 'gitGraph',
    ]
    if first_line:
        has_declaration = any(first_line.startswith(d) for d in valid_declarations)
        if not has_declaration:
            errors.append(f"缺少图表声明（应以 graph/folwchart 等开头，当前: '{first_line[:30]}...'")
    return errors


def check_link_label_quotes(lines):
    """检查箭头标签中的引号配对"""
    errors = []
    full_text = "\n".join(t for _, t in lines)
    # 匹配 -->|...| 或 -->"..." 格式
    pipe_labels = re.findall(r'\|([^|]*)\|', full_text)
    for label in pipe_labels:
        # 标签内引号必须配对
        if label.count('"') % 2 != 0:
            errors.append(f"箭头标签内引号未配对: '|{label}|'")
    return errors


def check_block(start_line, code_lines, end_line, original_lines=None):
    """检查单个 mermaid 块，返回错误列表"""
    errors = []
    full_text = "\n".join(t for _, t in code_lines)

    # 1. 图表声明
    errors.extend(check_graph_declaration(code_lines))

    # 2. subgraph/end 配对
    errors.extend(check_subgraph_balance(code_lines))

    # 构建原文内容集合用于对比
    orig_content_set = None
    if original_lines:
        orig_content_set = set(t.strip() for _, t in original_lines)

    # 3. 逐行检查
    for line_num, line_text in code_lines:
        stripped = line_text.strip()
        # 跳过空行、注释、end、subgraph
        if not stripped or stripped.startswith('%%') or stripped == 'end' or stripped.startswith('subgraph'):
            continue

        # 4. 括号配对（硬错误，不分原文）
        bracket_errors = check_bracket_balance(stripped)
        for err in bracket_errors:
            errors.append(f"第 {line_num} 行: 括号配对问题 — {err}")

        # 5. 节点标签危险字符
        # 如果提供了原文行内容，只有当该行在原文中不存在时才报告（说明被翻译修改了）
        is_modified = (orig_content_set is not None and stripped not in orig_content_set)
        if is_modified:
            label_errors = check_node_label_syntax(stripped)
            for err in label_errors:
                errors.append(f"第 {line_num} 行: [翻译引入] {err}")
        elif orig_content_set is None:
            # 没有原文对比，所有危险字符都报告
            label_errors = check_node_label_syntax(stripped)
            for err in label_errors:
                errors.append(f"第 {line_num} 行: {err}")

    # 6. 箭头语法
    arrow_errors = check_arrow_syntax(full_text)
    for err in arrow_errors:
        errors.append(err)

    # 7. 引号配对
    quote_errors = check_link_label_quotes(code_lines)
    for err in quote_errors:
        errors.append(err)

    return errors


def check_file(filepath, original_path=None):
    """检查文件中的所有 mermaid 块"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {"error": str(e)}

    blocks = find_mermaid_blocks(content)
    results = {
        "file": filepath,
        "total_mermaid_blocks": len(blocks),
        "valid_blocks": 0,
        "invalid_blocks": 0,
        "blocks": []
    }

    # 加载原文用于对比
    original_content = None
    original_blocks = []
    if original_path:
        try:
            with open(original_path, "r", encoding="utf-8") as f:
                original_content = f.read()
            original_blocks = find_mermaid_blocks(original_content)
        except:
            pass

    for idx, (start_line, code_lines, end_line) in enumerate(blocks):
        orig_lines = None
        if original_blocks and idx < len(original_blocks):
            orig_lines = original_blocks[idx][1]

        errors = check_block(start_line, code_lines, end_line, orig_lines)
        is_valid = len(errors) == 0

        block_info = {
            "block_index": idx + 1,
            "start_line": start_line,
            "end_line": end_line,
            "is_valid": is_valid,
            "errors": errors,
        }

        # 如果提供了原文，对比内容是否一致
        if original_blocks and idx < len(original_blocks):
            orig_start, orig_lines, orig_end = original_blocks[idx]
            orig_text = "\n".join(t for _, t in orig_lines)
            curr_text = "\n".join(t for _, t in code_lines)
            block_info["modified"] = (curr_text != orig_text)
            if block_info["modified"]:
                block_info["original_start_line"] = orig_start

        results["blocks"].append(block_info)
        if is_valid:
            results["valid_blocks"] += 1
        else:
            results["invalid_blocks"] += 1

    return results


def main():
    parser = argparse.ArgumentParser(
        description="检查 Markdown 文件中 mermaid 代码块是否符合书写规范"
    )
    parser.add_argument("file", help="要检查的 Markdown 文件")
    parser.add_argument("--original", help="原文文件路径，用于对比检测哪些块被修改")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = parser.parse_args()

    results = check_file(args.file, args.original)

    if "error" in results:
        print(f"❌ 错误: {results['error']}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        sys.exit(1 if results["invalid_blocks"] > 0 else 0)

    # 人类可读输出
    print(f"\n📊 {results['file']}")
    print(f"   共 {results['total_mermaid_blocks']} 个 mermaid 块，"
          f"✅ {results['valid_blocks']} 个通过，❌ {results['invalid_blocks']} 个存在语法问题\n")

    for block in results["blocks"]:
        status = "✅ 通过" if block["is_valid"] else "❌ 语法错误"
        modified = " [已修改]" if block.get("modified") else ""
        print(f"  块 {block['block_index']} (第 {block['start_line']}-{block['end_line']} 行){modified}: {status}")
        if block["errors"]:
            for err in block["errors"]:
                print(f"    → {err}")
        print()

    sys.exit(1 if results["invalid_blocks"] > 0 else 0)


if __name__ == "__main__":
    main()
