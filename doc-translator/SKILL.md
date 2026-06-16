---
name: doc-translator
description: |
  将技术/学术文档翻译为中文的 Skill。当用户需要翻译 Markdown、LaTeX 或混合格式的技术文档时使用，
  尤其适用于机器学习、数学、计算机科学领域的文档。支持公式格式化、术语规范化。
  用户提到"翻译这篇文章/文档"、"把这篇英文转成中文"、"翻译技术文档"、"翻译论文/教程"时触发。
  即使只是说"翻译"但提供了技术文档路径，也应使用此 Skill。
  输出文件保存在源文件同级目录，文件名添加 `-zh` 后缀。
---

# 文档中文翻译器

将技术/学术 Markdown 文档翻译为中文，保持公式格式、代码结构和图片位置不变。

> **全程由主 Agent 直接翻译，不使用 subagent。**

## 工作流程

### 1. 解析输入

- 单文件 → Read 后直接翻译
- 多文件 → 逐个翻译（每完成一个立即汇报）
- 目录 → 询问是否翻译所有 `.md` 文件
- 飞书 URL → 先用 lark-doc skill 导出再翻译
- 直接粘贴内容 → 询问保存路径

### 2. 翻译

按以下规则翻译全文，写出输出文件。

**分块策略**：≤ 800 行直接翻译全文；> 800 行按 H1/H2 章节切分，同一上下文中逐块翻译后拼接。

### 翻译规则

#### 术语处理
- ML/AI 术语、数学概念、算法名、框架名 → **首次出现**标注 `中文（English）`，后续直接用中文
- 无通行中文的术语（Transformer、LoRA）→ 保留英文
- 术语表/Key Terms 表格：第一列保留英文，解释列翻译

#### 翻译 vs 保留

| 翻译 | 保留原文 |
|------|---------|
| 正文、标题、列表、引用、表格描述文字 | Mermaid 块（整块原样复制） |
| 图片 alt 文字 | 代码块内容（仅添加中文注释，不改代码） |
| 无语言标识的纯公式代码块 → 转为 `$$...$$` LaTeX | LaTeX 公式源码（`$`/`$$`/`\begin`） |
| 正文中直接写的 ASCII 数学 → 转为 `$...$` LaTeX | 反引号包裹的代码标识符 |

#### 公式处理

- **`$$...$$` 必须独占行**（前后空行）
- **行内 ASCII 数学表达式**整体包裹为 `$...$`，并转换常见格式：下标 `_i`、上标 `^T`、`||w||` 范数、`alpha` 等希腊字母为 `\alpha`、`*` 乘法为 `\cdot`、函数名如 `max` 为 `\max`
- **连等公式** → 用 `&=` 和 `\\[15pt]` 换行对齐
- ⚠️ 反引号代码标识符、URL 参数不转换
- 详细规则见 `references/formula-rules.md`

#### 代码注释（详见 `references/code-comment-rules.md`）
- 核心算法、数据处理、非自解释逻辑的代码行 → 添加中文注释
- import、简单赋值、自解释代码 → 不加注释
- **注释要写详细**：遵循 WHAT → HOW → WHY 三层深度模型
  - 训练循环、梯度下降等算法代码：写一段策略说明 + 关键步骤 WHY
  - 超参数：给出选择理由
  - 评估/可视化：说明图表传达的信息和视觉编码理由
- 详细规则和丰富的示例对照见 `references/code-comment-rules.md`

#### 可选脚本辅助

翻译前可运行以下脚本辅助检测（非必需，直接翻译也可以）：
```bash
python3 scripts/term_manager.py scan --file <文件> --output /tmp/terms.json
python3 scripts/detect_formulas.py <文件> --output /tmp/formulas.json
```

### 3. 输出

- 路径：源文件同级，文件名 `{原名}-zh.{后缀}`，已存在时询问是否覆盖

### 4. 更新术语库（SQLite）

翻译完成后、汇报前，将本次翻译中确认的新术语持久化到 SQLite 术语库，供后续翻译复用。

**4.1 扫描译文术语覆盖情况**

```bash
python3 scripts/term_manager.py scan --file <输出文件路径> --output /tmp/terms_post.json
```

**4.2 添加新术语到 SQLite**

若本次翻译中遇到术语库未收录的新术语，使用 `add` 子命令直接写入 SQLite：

```bash
python3 scripts/term_manager.py add --en "<英文术语>" --zh "<中文翻译>" --cat "<分类>" [--keep]
```

- `--keep`：标记为保留英文不翻译（如专有名词、缩写）
- 常见分类：`Machine Learning / AI`、`Mathematics`、`Deep Learning Framework`、`Optimization`、`Computer Vision`、`NLP`

**批量导入**：若有多个新术语，先整理为 Markdown 表格格式写入临时文件，再使用 `import` 批量写入 SQLite：

```bash
# 临时文件 /tmp/new_terms.md 格式：
## <Category Name>
| English | 中文 | Notes |
|---------|------|-------|
| Term    | 翻译 | 备注  |

python3 scripts/term_manager.py import --md /tmp/new_terms.md
```

**4.3 确认术语库状态**

```bash
python3 scripts/term_manager.py stats
```

> 💡 **原则**：只添加经过确认、有通行中文译法或明确应保留英文的术语；避免添加临时性、拼写不确定或译法有争议的条目。

### 5. 完成汇报

```
✅ 翻译完成

文件：{原路径} → {输出路径}
行数：{N} → {N} | 术语标注：{N} 个 | 代码注释：{N} 行
```

这是最后一个步骤，不需要其他输出
