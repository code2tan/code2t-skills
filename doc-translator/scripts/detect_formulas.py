#!/usr/bin/env python3
"""
公式检测脚本 — 替代 SKILL.md 步骤 4.3 中由 LLM 执行的 inline math 扫描。

扫描 Markdown 文件，检测：
A. LaTeX 公式（$...$、$$...$$、\begin{...}）
B. 行内数学表达式（正文中的 ASCII 数学表达式，如 y_i、w^T、||w||）
C. 公式代码块（无语言标识的 ``` 块，仅含数学表达式）
D. 连等公式（多个连续等号）

用法:
    python3 detect_formulas.py <input.md> [--output formulas.json]

输出格式（兼容 SKILL.md 翻译计划）:
{
  "latex_formulas": [{"line": 10, "type": "inline|block|env", "content": "..."}],
  "inline_math": [{"line": 31, "match": "y_i", "context": "...", "action": "转 $y_i$"}],
  "formula_code_blocks": [{"start_line": 31, "end_line": 33, "content": "...", "action": "转为 $$...$$ LaTeX 格式"}],
  "chain_equalities": [{"line": 50, "content": "..."}],
  "counts": {"latex": 8, "inline_math": 15, "formula_blocks": 5, "chain_eq": 2}
}
"""

import re
import sys
import json
import argparse
from pathlib import Path


def detect_formulas(filepath: str) -> dict:
    """
    扫描 Markdown 文件，检测所有公式相关元素。

    Args:
        filepath: Markdown 文件路径

    Returns:
        检测结果字典
    """
    content = Path(filepath).read_text(encoding='utf-8')
    lines = content.split('\n')

    # ── 预计算排除区域 ──
    mermaid_spans = [(m.start(), m.end()) for m in re.finditer(r'```mermaid.*?```', content, re.DOTALL)]
    code_block_spans = []  # 有语言标识的代码块
    formula_block_spans = []  # 无语言标识的公式块

    in_code = False
    code_start = 0
    code_lang = ''
    code_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not in_code:
            if stripped.startswith('```'):
                in_code = True
                code_start = i
                code_lang = stripped[3:].strip()
                code_lines = []
        else:
            if stripped == '```':
                code_end = i
                if code_lang == '':
                    # 可能是公式代码块
                    block_content = '\n'.join(code_lines)
                    if not re.search(r'\b(import|def |class |for |while |return |print\(|self\.|if |elif )', block_content):
                        if '=' in block_content and re.search(r'[*^]|sum|log|sigmoid|softmax|TP|FP|FN|TN|Loss|MSE|R\^2|\b(w|x|y|z|b)\s*[=+\-*]|dMSE|dL/d|lambda|frac|\b(max|min|exp)\s*\(', block_content):
                            formula_block_spans.append({
                                'start_line': code_start + 1,
                                'end_line': code_end + 1,
                                'content': block_content.strip(),
                            })
                else:
                    code_block_spans.append((code_start, code_end))
                in_code = False
                code_lines = []
            else:
                code_lines.append(line)

    # ── A. LaTeX 公式检测 ──
    latex_formulas = []
    in_code_block = False

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # 独立公式 $$...$$
        if stripped.startswith('$$') or stripped.endswith('$$'):
            latex_formulas.append({'line': line_num, 'type': 'block', 'content': stripped})
            continue

        # LaTeX 环境
        env_match = re.search(r'\\begin\{(\w+)\}', line)
        if env_match:
            latex_formulas.append({
                'line': line_num,
                'type': 'env',
                'env_name': env_match.group(1),
                'content': stripped,
            })
            continue

        # 行内公式 $...$（不在代码块内）
        inline_matches = re.findall(r'\$([^\$]+)\$', line)
        for m in inline_matches:
            latex_formulas.append({'line': line_num, 'type': 'inline', 'content': m.strip()})

    # ── B. 行内数学表达式检测 ──
    inline_math_patterns = [
        # 下标变量: y_i, x_i, alpha_i (短变量名，不是英文单词)
        (r'(?<![\w.])\b([a-z]{1,3})_([a-zA-Z0-9]+)\b(?![_\w])', '转 ${}_{}$'),
        # 上标/转置: w^T, x^2
        (r'\b([a-z]{1,3})\^(\w+)\b', '转 ${}^{}$'),
        # 范数: ||w||
        (r'\|\|([a-z]{1,3})\|\|', '转 $||{}||$'),
        # 点积（中间点）: x_i · x_j
        (r'\b([a-z]{1,4}(?:_\w+)?)\s*[·]\s*([a-z]{1,4}(?:_\w+)?)\b', '转 ${} \\cdot {}$'),
        # 点积（句点形式）: x_i . x_j（仅短变量名）
        (r'\b([a-z]{1,4}(?:_\w+)?)\s+\.\s+([a-z]{1,4}(?:_\w+)?)\b', '转 ${} \\cdot {}$'),
        # 星号乘法（数学上下文）: y_i * (
        (r'([a-z]{1,4}(?:_\w+)?)\s*\*\s*([a-z]{1,4}(?:_\w+)?\s*[\(])', '转 ${} \\cdot ($'),
        # 集合: {-1, +1}, {0, 1}
        (r'\{[-+,\s\d]+\}', '转 LaTeX 集合'),
        # 希腊字母名称: epsilon, gamma, lambda
        (r'(?<![\$\w])\b(epsilon|gamma|lambda|sigma|mu|theta|alpha|beta)\b(?![\w\$])', '转 \\{}'),
        # 数学函数名: max(, min(, exp(, dot(
        (r'\b(max|min|exp|dot|sigmoid|softmax)\s*\(', '转 \\{}'),
        # O(n^2) 复杂度
        (r'O\([a-z]\^\d+\)', '转 O(n^k)'),
    ]

    inline_math_list = []

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        # 跳过代码块
        if stripped.startswith('```'):
            continue
        # 跳过 mermaid 块
        line_start_pos = sum(len(lines[j]) + 1 for j in range(line_num - 1))
        if any(ms <= line_start_pos < me for ms, me in mermaid_spans):
            continue
        # 跳过 URL
        if 'http' in line or 'www.' in line:
            continue

        for pattern, action in inline_math_patterns:
            for m in re.finditer(pattern, line):
                # 排除 URL、import 语句、代码关键字上下文
                context = line[max(0, m.start() - 20):m.end() + 20]
                if re.search(r'(http|import |def |class |from |print\()', context):
                    continue
                inline_math_list.append({
                    'line': line_num,
                    'match': m.group(),
                    'context': context,
                    'action': action,
                })

    # ── C. 公式代码块（已在上面代码块扫描中检测）──

    formula_blocks_output = []
    for fb in formula_block_spans:
        formula_blocks_output.append({
            'start_line': fb['start_line'],
            'end_line': fb['end_line'],
            'content': fb['content'],
            'action': '转为 $$...$$ LaTeX 格式（$$ 独占行）',
        })

    # ── D. 连等公式检测 ──
    chain_equalities = []
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        # 检查 $$ 块中的连等公式
        if stripped.startswith('$$') or stripped.endswith('$$'):
            if line.count('=') >= 2:
                chain_equalities.append({
                    'line': line_num,
                    'content': stripped,
                })

    return {
        'latex_formulas': latex_formulas,
        'inline_math': inline_math_list,
        'formula_code_blocks': formula_blocks_output,
        'chain_equalities': chain_equalities,
        'counts': {
            'latex': len(latex_formulas),
            'inline_math': len(inline_math_list),
            'formula_blocks': len(formula_block_spans),
            'chain_eq': len(chain_equalities),
        }
    }


def main():
    parser = argparse.ArgumentParser(
        description='扫描 Markdown 文件中的公式元素（LaTeX、行内数学、公式代码块、连等公式）'
    )
    parser.add_argument('input', help='输入的 Markdown 文件路径')
    parser.add_argument('--output', '-o', help='输出 JSON 文件路径')
    parser.add_argument('--summary', '-s', action='store_true',
                       help='输出简要摘要')

    args = parser.parse_args()

    filepath = args.input
    if not Path(filepath).exists():
        print(f'错误: 文件不存在 — {filepath}', file=sys.stderr)
        sys.exit(1)

    result = detect_formulas(filepath)

    if args.summary:
        c = result['counts']
        print(f'📊 公式检测结果: {filepath}')
        print(f'   LaTeX 公式: {c["latex"]} 个')
        print(f'   行内数学表达式: {c["inline_math"]} 个')
        print(f'   公式代码块: {c["formula_blocks"]} 个')
        print(f'   连等公式: {c["chain_eq"]} 个')
    else:
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(output, encoding='utf-8')
            print(f'✅ 输出已写入: {args.output}', file=sys.stderr)
        else:
            print(output)


if __name__ == '__main__':
    main()
