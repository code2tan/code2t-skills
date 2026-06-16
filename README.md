# code2t-skills

code2tan 的 Claude Code Skills 仓库，包含多个实用技能，用于增强 Claude Code 在飞书文档操作和技术翻译场景中的能力。

## 安装

### 前置条件

- [Claude Code](https://docs.anthropic.com/zh-CN/docs/claude-code/overview)（支持 Skills 的版本）
- [lark-cli](https://github.com/code2tan/lark-cli)（飞书文档相关 Skill 的前置 CLI 工具）
- Python 3.8+

### 安装 Skills

#### 方式一：插件市场安装（推荐）

在 Claude Code 中执行以下命令添加本仓库为插件市场并安装：

```
/plugin marketplace add https://github.com/code2tan/code2t-skills.git
```

然后安装对应的 Skill：

```
/plugin install doc-translator@code2t-skills
/plugin install lark-doc-to-wiki@code2t-skills
```

安装完成后 Claude Code 会自动加载这些 Skills。

#### 方式二：手动安装

将 Skill 目录复制到 Claude Code 的 skills 目录下：

```bash
# 用户级（所有项目可用）
cp -r doc-translator ~/.claude/skills/
cp -r lark-doc-to-wiki ~/.claude/skills/

# 项目级（仅当前项目可用）
cp -r doc-translator .claude/skills/
cp -r lark-doc-to-wiki .claude/skills/
```

安装后重启 Claude Code 即可使用。

### 验证安装

在 Claude Code 中运行 `/skills` 查看已安装的 Skill 列表，确认 `doc-translator` 和 `lark-doc-to-wiki` 出现在列表中。

### 更新

插件市场安装方式：

```
# 刷新插件市场（获取最新版本）
/plugin marketplace update code2t-skills
```

配置后重启 Claude Code 即可加载更新后的 Skills。也可以为插件市场启用自动更新，Claude Code 在启动时会自动检查并更新：

```
/plugin marketplace update code2t-skills --auto
```

手动安装方式：

```bash
cd /path/to/code2t-skills
git pull
```

### 卸载

```
/plugin uninstall doc-translator@code2t-skills
/plugin uninstall lark-doc-to-wiki@code2t-skills
```

如需同时删除插件数据，加 `--prune`：

```
/plugin uninstall doc-translator@code2t-skills --prune
```

手动安装的卸载方式：

```bash
rm -rf ~/.claude/skills/doc-translator
rm -rf ~/.claude/skills/lark-doc-to-wiki
```

## Skills

### doc-translator — 技术文档中文翻译器

将技术/学术 Markdown 文档翻译为中文，专为机器学习、数学、计算机科学领域文档优化。

**功能特点：**
- 术语管理：ML/AI 术语首次出现标注英文，使用 SQLite 术语库持久化
- 公式处理：保留 LaTeX 源码，自动转换行内 ASCII 数学表达式为 `$...$` 格式，连等公式换行对齐
- 代码注释：为核心算法代码添加详细中文注释（WHAT → HOW → WHY 三层深度模型）
- Mermaid 图表：完整保留不翻译
- 大文件分块翻译：> 800 行按章节切分

**触发方式：** `翻译这篇文章`、`把这篇英文转成中文`、`翻译技术文档`、`翻译论文/教程`

**参考文件：**
- `doc-translator/references/formula-rules.md` — 公式处理详细规则
- `doc-translator/references/code-comment-rules.md` — 代码注释密度指南
- `doc-translator/references/terminology.db` — SQLite 术语数据库
- `doc-translator/scripts/term_manager.py` — 术语管理脚本

### lark-doc-to-wiki — 飞书文档迁移到知识库

将飞书文档（Docx）完整迁移到知识库指定父节点下，保留图片、文档引用、callout 高亮框、列表、表格等所有富文本格式。

**功能特点：**
- 自动查找父节点：基于 SQLite + FTS5 全文搜索，支持模糊匹配
- 图片迁移：自动下载并上传到知识库文档的正确位置
- 公式居中：自动处理 `<latex>` 段落的居中对齐
- 文档引用保留：`<cite>` 引用关系在新文档中自动生效
- 缓存自动同步：搜索时按需从飞书 API 拉取最新节点数据

**触发方式：** `把这篇文章整理到知识库`、`把文档迁移到 wiki 节点`、`复制文档到知识库`、`归档文档到知识库`

**前置步骤（首次使用）：**

```bash
# 注册知识空间（仅需运行一次）
cd lark-doc-to-wiki
python3 scripts/wiki_tree.py space-add --space-name "你的知识库名称"
```

**工作流程：** 准备（查找父节点 → 新建子节点 → 下载图片 → 构建 XML）→ 写入文档 → 插入图片 → 公式居中 → 验证清理

**参考文件：**
- `lark-doc-to-wiki/scripts/prepare.py` — 准备与清理脚本
- `lark-doc-to-wiki/scripts/wiki_tree.py` — 知识库节点缓存工具（SQLite + FTS5）
- `lark-doc-to-wiki/WIKI_TREE_DESIGN.md` — wiki_tree 数据库设计文档

## 项目结构

```
code2t-skills/
├── .claude-plugin/
│   └── marketplace.json             # 插件市场清单（Claude Code 识别入口）
├── doc-translator/
│   ├── .claude-plugin/
│   │   └── plugin.json              # 插件清单
│   ├── SKILL.md                     # Skill 定义与工作流程
│   ├── evals/
│   │   └── evals.json               # 评估用例
│   ├── references/
│   │   ├── code-comment-rules.md    # 代码注释规则
│   │   ├── formula-rules.md         # 公式处理规则
│   │   └── terminology.db           # SQLite 术语库
│   └── scripts/
│       ├── term_manager.py          # 术语检测与管理
│       ├── detect_formulas.py       # 公式检测
│       ├── detect_code_comments.py  # 代码注释检测
│       └── check_mermaid.py         # Mermaid 图表检查
└── lark-doc-to-wiki/
    ├── .claude-plugin/
    │   └── plugin.json              # 插件清单
    ├── SKILL.md                     # Skill 定义与工作流程
    ├── WIKI_TREE_DESIGN.md          # wiki_tree 数据库设计
    └── scripts/
        ├── prepare.py               # 准备与清理
        └── wiki_tree.py             # 知识库节点缓存（SQLite + FTS5）
```

## 许可证

MIT License — 详见 [LICENSE](LICENSE)
