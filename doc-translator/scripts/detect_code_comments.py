#!/usr/bin/env python3
"""
代码注释检测脚本 — 替代 doc-translator-zh 技能中的 Agent 3 (detect-code)。

扫描 Markdown 文件中的所有代码块，判断哪些代码需要添加中文注释，
并生成注释建议。输出 JSON 格式的 code_blocks 清单。

用法:
    python detect_code_comments.py <input.md> [--output comments.json]

输出格式 (兼容 SKILL.md 步骤 4.2 翻译计划):
    [
      {
        "start": 29,
        "end": 48,
        "language": "python",
        "has_comments": false,
        "needs_comments_at": [37, 40, 41, 47],
        "comment_suggestions": ["计算损失函数关于参数的梯度", ...]
      }
    ]
"""

import re
import sys
import json
import argparse
from pathlib import Path


# ── 语言特定的注释标记 ──────────────────────────────────────────────
COMMENT_MARKERS = {
    "python": "#",
    "py": "#",
    "javascript": "//",
    "js": "//",
    "typescript": "//",
    "ts": "//",
    "java": "//",
    "c": "//",
    "cpp": "//",
    "c++": "//",
    "rust": "//",
    "rs": "//",
    "go": "//",
    "golang": "//",
    "ruby": "#",
    "rb": "#",
    "shell": "#",
    "bash": "#",
    "sh": "#",
    "r": "#",
    "julia": "#",
    "jl": "#",
    "swift": "//",
    "kotlin": "//",
    "kt": "//",
    "scala": "//",
    "php": "//",
    "sql": "--",
    "lua": "--",
    "perl": "#",
    "pl": "#",
}


# ── 简单代码模式（无需注释）──────────────────────────────────────────
SIMPLE_PATTERNS = [
    # import / require / use
    r'^\s*(import|from\s+\S+\s+import|require|using|package)\b',
    # 简单变量赋值 (单值、字面量)
    r'^\s*[a-zA-Z_]\w*\s*=\s*[\d"\'{}\[\]().,\s]+\s*$',
    r'^\s*[a-zA-Z_]\w*\s*=\s*None\s*$',
    r'^\s*[a-zA-Z_]\w*\s*=\s*(True|False)\s*$',
    # print / console.log / fmt.Println
    r'^\s*(print|printf|println|fmt\.Print|console\.log|puts|echo)\b',
    # return 单变量
    r'^\s*return\s+[a-zA-Z_]\w*\s*$',
    # 空行、纯注释行
    r'^\s*$',
    # class/def/function 定义行本身 (单独不需要注释，其内部逻辑需要)
    r'^\s*(class|def|fn|func|function)\s+\w+',
    # 装饰器
    r'^\s*@',
    # 文档字符串开始/结束
    r'^\s*("""|\'\'\'|/\*\*|\*/)\s*$',
]


# ── 需要注释的复杂模式 ──────────────────────────────────────────────
COMPLEX_PATTERNS = [
    # 循环结构
    (r'^\s*(for|while)\b', '循环逻辑'),
    # 条件分支 (非单行 if/else)
    (r'^\s*(if|elif|else|case|switch)\b', '条件判断'),
    # 矩阵/向量运算 (点积、矩阵乘法、reshape 等)
    (r'@(?!")|\.dot\(|\.matmul|\.reshape|\.transpose|\.T\b|np\.\w+|torch\.\w+|tf\.\w+', '矩阵/张量运算'),
    # 列表推导式 / 生成器表达式
    (r'\[.*for\s+\w+\s+in\b.*\]', '推导式/过滤'),
    # 聚合操作 (sum/mean/std/max/min 在数组上)
    (r'\b(sum|mean|std|var|min|max|argmax|argmin|average)\s*\(', '聚合/统计'),
    # 模型训练相关
    (r'\.(fit|predict|train|evaluate|forward|backward|step|zero_grad|backward)\s*\(', '模型训练/推理'),
    # 损失函数
    (r'\b(MSELoss|CrossEntropy|BCELoss|NLLLoss|loss|criterion)\b', '损失计算'),
    # 梯度操作
    (r'\.(backward|zero_grad|clip_grad|grad)', '梯度处理'),
    # 数据加载/划分
    (r'\b(DataLoader|train_test_split|shuffle|batch)\b', '数据处理'),
    # 优化器
    (r'\b(Adam|SGD|AdamW|RMSprop|optimizer)\b', '优化器'),
    # 数学公式 (连等、复杂算术)
    (r'[a-zA-Z_]\w*\s*[+\-*/]=\s*[a-zA-Z_]\w*\s*[*@/+\-]', '数学/数值更新'),
    # 索引/切片操作 (非简单赋值)
    (r'\w+\[.*:.*\]\s*=', '切片/索引赋值'),
    # 函数调用链
    (r'\w+\.\w+\(\)\.\w+', '方法链调用'),
    # 异常处理
    (r'^\s*(try|except|catch|raise|throw)\b', '异常处理'),
    # 文件 I/O
    (r'\b(open|read|write|load|save|dump|loadtxt|genfromtxt)\s*[\(\.].*', '文件/数据 I/O'),
    # lambda / map / filter / reduce
    (r'\b(lambda|map|filter|reduce)\s*[\(:]', '函数式操作'),
    # 类型转换 (复杂)
    (r'np\.array|torch\.tensor|tf\.convert', '类型转换/张量创建'),
    # 广播操作
    (r'\w+\s*\[\s*np\.newaxis|\.unsqueeze|\.expand|\.broadcast', '广播/维度操作'),
]


def is_simple_line(line: str) -> bool:
    """判断一行代码是否属于"简单代码"（无需注释）。"""
    stripped = line.strip()
    # 已经是注释行 → 视为已有注释
    for lang, marker in COMMENT_MARKERS.items():
        if stripped.startswith(marker):
            return True
    for pattern in SIMPLE_PATTERNS:
        if re.match(pattern, stripped):
            return True
    return False


def analyze_code_block(code: str, language: str) -> dict:
    """
    分析单个代码块，返回需要注释的行和建议。

    Returns:
        {
            "has_comments": bool,
            "needs_comments_at": [line_numbers],
            "comment_suggestions": [suggestions]
        }
    """
    lines = code.split('\n')
    total_lines = len(lines)

    # 判断是否已有注释
    comment_marker = COMMENT_MARKERS.get(language.lower(), '#')
    has_comments = any(
        comment_marker in line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith(('"""', "'''", '/*', '*'))
    )

    # 如果代码块很短 (≤5 行)，通常不需要额外注释
    if total_lines <= 5:
        return {
            "has_comments": has_comments,
            "needs_comments_at": [],
            "comment_suggestions": []
        }

    # 统计有效代码行数 (排除空行、纯注释、import、简单赋值)
    code_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith((comment_marker, '"""', "'''", '/*', '//')):
            continue
        if not is_simple_line(stripped):
            code_lines.append((i + 1, stripped))  # 1-based line number

    # 对复杂代码行打标签
    needs_comments = []
    suggestions = []

    for line_num, line_content in code_lines:
        matched_complex = []
        for pattern, label in COMPLEX_PATTERNS:
            if re.search(pattern, line_content):
                matched_complex.append(label)

        if matched_complex:
            needs_comments.append(line_num)
            # 生成注释建议 — 基于匹配的模式标签
            suggestion = _generate_comment_suggestion(line_content, matched_complex, language)
            suggestions.append(suggestion)

    # 限制注释密度：如果太多，只保留最关键的
    max_comments = 5
    if len(needs_comments) > max_comments:
        # 优先保留：模型训练 > 矩阵运算 > 循环 > 其他
        priority_order = ['模型训练/推理', '损失计算', '梯度处理', '矩阵/张量运算',
                         '循环逻辑', '聚合/统计', '数据处理', '优化器']
        scored = []
        for idx, line_num in enumerate(needs_comments):
            priority = 0
            for p, tag in enumerate(priority_order):
                if tag in suggestions[idx]:
                    priority = len(priority_order) - p
                    break
            scored.append((priority, line_num, suggestions[idx]))
        scored.sort(reverse=True)
        needs_comments = [x[1] for x in scored[:max_comments]]
        suggestions = [x[2] for x in scored[:max_comments]]
        # 按行号重新排序
        paired = sorted(zip(needs_comments, suggestions))
        needs_comments = [x[0] for x in paired]
        suggestions = [x[1] for x in paired]

    return {
        "has_comments": has_comments,
        "needs_comments_at": needs_comments,
        "comment_suggestions": suggestions
    }


def _generate_comment_suggestion(line: str, labels: list, language: str) -> str:
    """基于匹配的模式标签生成中文注释建议。"""
    comment_marker = COMMENT_MARKERS.get(language.lower(), '#')

    # 基于标签的通用建议
    if '模型训练/推理' in labels:
        if 'fit' in line:
            return f'{comment_marker} 在训练数据上拟合模型参数'
        elif 'predict' in line:
            return f'{comment_marker} 对新数据进行预测'
        elif 'forward' in line:
            return f'{comment_marker} 前向传播计算输出'
        elif 'backward' in line:
            return f'{comment_marker} 反向传播计算梯度'
        return f'{comment_marker} 模型训练/推理步骤'

    if '损失计算' in labels:
        return f'{comment_marker} 计算预测值与真实值的误差'

    if '梯度处理' in labels:
        if 'zero_grad' in line:
            return f'{comment_marker} 清空上一步累积的梯度'
        elif 'backward' in line:
            return f'{comment_marker} 反向传播计算各参数梯度'
        return f'{comment_marker} 梯度相关操作'

    if '矩阵/张量运算' in labels:
        if '@' in line or 'matmul' in line:
            return f'{comment_marker} 矩阵乘法运算'
        elif 'dot' in line:
            return f'{comment_marker} 向量点积运算'
        elif 'reshape' in line:
            return f'{comment_marker} 重塑张量形状'
        elif 'transpose' in line or '.T' in line:
            return f'{comment_marker} 矩阵转置'
        return f'{comment_marker} 矩阵/张量运算'

    if '循环逻辑' in labels:
        return f'{comment_marker} 遍历处理每个元素'

    if '条件判断' in labels:
        return f'{comment_marker} 根据条件分支处理'

    if '聚合/统计' in labels:
        return f'{comment_marker} 聚合统计数据'

    if '数据处理' in labels:
        if 'train_test_split' in line:
            return f'{comment_marker} 划分训练集与测试集'
        elif 'DataLoader' in line:
            return f'{comment_marker} 创建数据加载器'
        elif 'shuffle' in line:
            return f'{comment_marker} 打乱数据顺序'
        return f'{comment_marker} 数据处理步骤'

    if '优化器' in labels:
        if 'step' in line:
            return f'{comment_marker} 根据梯度更新模型参数'
        return f'{comment_marker} 优化器操作'

    if '推导式/过滤' in labels:
        return f'{comment_marker} 列表推导式处理'

    if '切片/索引赋值' in labels:
        return f'{comment_marker} 切片/索引操作'

    if '广播/维度操作' in labels:
        return f'{comment_marker} 维度变换/广播操作'

    if '类型转换/张量创建' in labels:
        return f'{comment_marker} 类型转换/张量创建'

    if '异常处理' in labels:
        return f'{comment_marker} 异常处理'

    if '文件/数据 I/O' in labels:
        return f'{comment_marker} 文件读写/数据加载'

    if '函数式操作' in labels:
        return f'{comment_marker} 函数式操作'

    if '数学/数值更新' in labels:
        return f'{comment_marker} 数值计算/参数更新'

    if '方法链调用' in labels:
        return f'{comment_marker} 链式方法调用'

    # 默认建议
    return f'{comment_marker} 关键逻辑: {line[:40]}...'


def scan_markdown_file(filepath: str) -> list:
    """
    扫描 Markdown 文件，提取所有代码块并分析。

    Returns:
        list of dicts, 每个 dict 包含:
        - start: int (起始行号, 1-based)
        - end: int (结束行号, 1-based)
        - language: str
        - has_comments: bool
        - needs_comments_at: list[int]
        - comment_suggestions: list[str]
    """
    content = Path(filepath).read_text(encoding='utf-8')
    lines = content.split('\n')

    # 匹配代码块: ```language ... ```
    # 注意: mermaid 代码块不需要注释，直接跳过
    code_block_pattern = re.compile(r'^```(\w+)?\s*$')

    code_blocks = []
    in_block = False
    block_start = 0
    block_lang = ''
    block_lines = []

    for i, line in enumerate(lines):
        if not in_block:
            match = code_block_pattern.match(line.strip())
            if match:
                in_block = True
                block_start = i + 1  # 1-based
                block_lang = match.group(1) or ''
                block_lines = []
        else:
            if line.strip() == '```':
                # 代码块结束
                block_end = i + 1  # 1-based
                code = '\n'.join(block_lines)

                # mermaid / 纯配置不需要注释
                if block_lang.lower() in ('mermaid', 'json', 'yaml', 'yml', 'xml', 'html', 'css', 'toml', 'ini', 'cfg', 'dockerfile', 'makefile'):
                    code_blocks.append({
                        "start": block_start,
                        "end": block_end,
                        "language": block_lang,
                        "has_comments": False,
                        "needs_comments_at": [],
                        "comment_suggestions": []
                    })
                else:
                    analysis = analyze_code_block(code, block_lang)
                    code_blocks.append({
                        "start": block_start,
                        "end": block_end,
                        "language": block_lang,
                        **analysis
                    })

                in_block = False
                block_lines = []
            else:
                block_lines.append(line)

    return code_blocks


def main():
    parser = argparse.ArgumentParser(
        description='扫描 Markdown 文件中的代码块，分析需要添加中文注释的位置。'
    )
    parser.add_argument('input', help='输入的 Markdown 文件路径')
    parser.add_argument('--output', '-o', help='输出 JSON 文件路径 (默认输出到 stdout)')
    parser.add_argument('--summary', '-s', action='store_true',
                       help='输出简要摘要而非完整 JSON')

    args = parser.parse_args()

    filepath = args.input
    if not Path(filepath).exists():
        print(f'错误: 文件不存在 — {filepath}', file=sys.stderr)
        sys.exit(1)

    code_blocks = scan_markdown_file(filepath)

    if args.summary:
        total_blocks = len(code_blocks)
        needs_comment_blocks = sum(1 for b in code_blocks if b['needs_comments_at'])
        total_comment_lines = sum(len(b['needs_comments_at']) for b in code_blocks)

        print(f'📊 代码块扫描结果: {filepath}')
        print(f'   总代码块数: {total_blocks}')
        print(f'   需要注释的代码块: {needs_comment_blocks}')
        print(f'   建议添加注释行数: {total_comment_lines}')

        for i, block in enumerate(code_blocks):
            lang = block['language'] or 'unknown'
            status = '✅ 已有注释' if block['has_comments'] else '📝 需添加注释'
            print(f'   [{i+1}] 行 {block["start"]}-{block["end"]} ({lang}): {status}, '
                  f'建议注释 {len(block["needs_comments_at"])} 行')
    else:
        result = json.dumps(code_blocks, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(result, encoding='utf-8')
            print(f'✅ 输出已写入: {args.output}', file=sys.stderr)
        else:
            print(result)


if __name__ == '__main__':
    main()
