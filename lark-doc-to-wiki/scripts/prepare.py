#!/usr/bin/env python3
"""
lark-doc-to-wiki 准备工作脚本

功能：
1. 通过 wiki_tree.py 查找知识库父节点（SQLite + FTS5 搜索，内置按需同步）
2. 在父节点下新建子节点（使用源文档标题）
3. 读取源文档内容，提取图片 token 和嵌入电子表格
4. 通过 lark-cli sheets +csv-get 读取嵌入电子表格数据，转为内联 HTML 表格
5. 下载所有图片到临时目录
6. 构建含图片占位和内联表格的 XML 内容文件

用法：
  # 按节点名称查找（推荐）
  python3 prepare.py --source-doc <URL> --target-name "节点名称"

  # 按节点 token
  python3 prepare.py --source-doc <URL> --target-token <token>

  # 清理临时文件
  python3 prepare.py --cleanup
"""

import argparse
import json
import os
import subprocess
import sys
import re
import shutil

# 默认知识空间
DEFAULT_SPACE_ID = "7494564759545659393"
DEFAULT_SPACE_NAME = "K.B.LLM DEV"


def run_lark(args, description=""):
    """运行 lark-cli 命令并返回解析后的 JSON"""
    cmd = ["lark-cli"] + args
    if description:
        print(f"[{description}] Running: lark-cli {' '.join(args[:4])}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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




def resolve_target_node(name=None, token=None, space_id=None, space_name=None):
    """解析目标节点。

    token 路径：直接调用 wiki +node-get。
    name 路径：调用 wiki_tree.py search → 获取 node_token → wiki +node-get 获取 obj_token。
    wiki_tree.py 内置按需同步，自动处理缓存新鲜度。

    返回: (node_token, obj_token, title) 或 None
    """
    if token:
        if not token.startswith("wik"):
            node_url = f"https://feishu.cn/wiki/{token}"
            result = run_lark(["wiki", "+node-get", "--node-token", node_url,
                                "--format", "json"], "get-target-node")
        else:
            result = run_lark(["wiki", "+node-get", "--node-token", token,
                                "--format", "json"], "get-target-node")
        if result and result.get("ok"):
            d = result.get("data", {})
            return (d.get("node_token"), d.get("obj_token"), d.get("title"))
        print(f"  Failed to resolve token: {token}", file=sys.stderr)
        return None

    if not name:
        return None

    # 通过 wiki_tree.py 搜索（内置按需同步）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    wiki_tree = os.path.join(script_dir, "wiki_tree.py")

    cmd = [sys.executable, wiki_tree, "search", name, "--limit", "5"]
    if space_name:
        cmd.extend(["--space-name", space_name])
    elif space_id:
        cmd.extend(["--space-id", space_id])

    print(f"  [wiki_tree] Searching for '{name}'...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"  [wiki_tree] Search timed out", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"  [wiki_tree] Search failed: {(result.stderr or '')[:200]}", file=sys.stderr)
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  [wiki_tree] Invalid JSON output", file=sys.stderr)
        return None

    if not data.get("ok") or not data.get("results"):
        print(f"  Node '{name}' not found in wiki tree", file=sys.stderr)
        return None

    best = data["results"][0]
    node_token = best["node_token"]
    print(f"  [wiki_tree] Found: {best['title']} ({node_token})")

    # 通过 wiki +node-get 获取 obj_token
    node_url = f"https://feishu.cn/wiki/{node_token}"
    result = run_lark(["wiki", "+node-get", "--node-token", node_url,
                        "--format", "json"], "get-target-node")
    if result and result.get("ok"):
        d = result.get("data", {})
        return (d.get("node_token"), d.get("obj_token"), d.get("title"))

    print(f"  Failed to resolve node_token: {node_token}", file=sys.stderr)
    return None


# ── 创建子节点 ──────────────────────────────────────────────

def create_child_node(parent_node_token, title, space_id):
    """在父节点下新建子节点。返回 (node_token, obj_token) 或 None。"""
    kwargs = [
        "wiki", "+node-create",
        "--parent-node-token", parent_node_token,
        "--obj-type", "docx",
        "--title", title,
        "--format", "json"
    ]
    if space_id:
        kwargs.extend(["--space-id", space_id])
    result = run_lark(kwargs, f"create-child-node '{title}'")
    if not result or not result.get("ok"):
        print(f"  Failed to create child node '{title}'", file=sys.stderr)
        return None
    data = result.get("data", {})
    node_token = data.get("node_token")
    obj_token = data.get("obj_token")
    print(f"  Created child node: {title} (doc_id: {obj_token})")
    return (node_token, obj_token)


# ── 文档处理 ──────────────────────────────────────────────

def fetch_document(doc_url):
    """获取源文档内容"""
    result = run_lark([
        "docs", "+fetch", "--api-version", "v2",
        "--doc", doc_url, "--format", "json",
        "--doc-format", "xml"
    ], "fetch-source-doc")
    if not result or not result.get("ok"):
        print("  Failed to fetch source document", file=sys.stderr)
        return None
    return result.get("data", {}).get("document", {}).get("content", "")


def extract_image_tokens(content):
    """从文档 XML 中提取所有图片 token"""
    images = []
    # fetch 返回 <img token="..." .../> 格式；也兼容 src="..." 格式
    pattern = re.compile(r'<img\s[^>]*?(?:token|src)="([^"]+)"[^>]*?/?>')
    for match in pattern.finditer(content):
        token = match.group(1)
        full_tag = match.group(0)
        name_match = re.search(r'name="([^"]*)"', full_tag)
        name = name_match.group(1) if name_match else f"img_{token[:8]}"
        images.append({"token": token, "name": name, "full_tag": full_tag})
    return images


def extract_sheet_tags(content):
    """从文档 XML 中提取所有嵌入电子表格标签

    匹配格式: <sheet token="SPREADSHEET_TOKEN" sheet-id="SHEET_ID"></sheet>
    属性顺序不敏感。跳过 type="blank" 的空白 sheet（无数据可读）。

    返回: [{"token": "...", "sheet_id": "...", "full_tag": "..."}, ...]
    """
    sheets = []
    # 分两步匹配：先用宽泛正则匹配完整 <sheet> 标签，再从中提取属性
    tag_pattern = re.compile(r'<sheet\s[^>]*?/?>', re.IGNORECASE)
    token_pattern = re.compile(r'token="([^"]+)"', re.IGNORECASE)
    sheet_id_pattern = re.compile(r'sheet-id="([^"]+)"', re.IGNORECASE)

    for match in tag_pattern.finditer(content):
        full_tag = match.group(0)
        # 跳过空白 sheet（type="blank" 无实际数据）
        if 'type="blank"' in full_tag:
            token_m = token_pattern.search(full_tag)
            token_preview = token_m.group(1)[:16] if token_m else "?"
            print(f"  Skip: blank sheet (token={token_preview}...)")
            continue
        token_m = token_pattern.search(full_tag)
        sid_m = sheet_id_pattern.search(full_tag)
        if not token_m or not sid_m:
            # 缺少必要属性，跳过
            continue
        sheets.append({
            "token": token_m.group(1),
            "sheet_id": sid_m.group(1),
            "full_tag": full_tag
        })
    return sheets


def fetch_sheet_csv(token, sheet_id):
    """通过 lark-cli sheets +csv-get 读取电子表格数据

    使用 --rows-json 模式获取结构化数据，便于后续构建表格。

    返回: (rows_data, col_indices) 元组，或 None（读取失败时）
        rows_data: [{"row_number": N, "values": {"A": "val", ...}}, ...]
        col_indices: ["A", "B", ...]
    """
    cmd = [
        "lark-cli", "sheets", "+csv-get",
        "--spreadsheet-token", token,
        "--sheet-id", sheet_id,
        "--rows-json",
        "--format", "json"
    ]
    print(f"    [sheets +csv-get] token={token[:16]}... sheet_id={sheet_id[:8]}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"    Timeout reading sheet data", file=sys.stderr)
        return None
    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout)[:300]
        print(f"    Error reading sheet: {error_msg}", file=sys.stderr)
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}", file=sys.stderr)
        return None
    if not data.get("ok"):
        print(f"    API error: {json.dumps(data)[:200]}", file=sys.stderr)
        return None
    rows_data = data.get("data", {}).get("rows", [])
    col_indices = data.get("data", {}).get("col_indices", [])
    if not rows_data:
        print(f"    Sheet is empty (no rows)")
    else:
        print(f"    OK: {len(rows_data)} rows, {len(col_indices)} columns")
    return (rows_data, col_indices)


def csv_to_table_xml(rows_data, col_indices):
    """将 rows-json 格式的数据转换为 HTML <table> XML

    rows_data: [{"row_number": N, "values": {"A": "val", "B": "val"}}, ...]
    col_indices: ["A", "B", ...]

    第一行作为表头 (<thead><tr><th>)，其余行作为表体 (<tbody><tr><td>)。
    空表格返回空字符串。
    """
    if not rows_data or not col_indices:
        return ""

    # 对单元格内容进行 XML 转义
    def escape_xml(text):
        if text is None:
            return ""
        text = str(text)
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        return text

    parts = ["<table>"]

    # 第一行作为表头
    header_row = rows_data[0]
    parts.append("<thead><tr>")
    for col in col_indices:
        val = header_row.get("values", {}).get(col, "")
        parts.append(f"<th>{escape_xml(val)}</th>")
    parts.append("</tr></thead>")

    # 其余行作为表体
    if len(rows_data) > 1:
        parts.append("<tbody>")
        for row in rows_data[1:]:
            parts.append("<tr>")
            for col in col_indices:
                val = row.get("values", {}).get(col, "")
                parts.append(f"<td>{escape_xml(val)}</td>")
            parts.append("</tr>")
        parts.append("</tbody>")

    parts.append("</table>")
    return "".join(parts)


def download_images(images, output_dir):
    """使用 docs +media-preview 下载所有图片

    lark-cli --output 只接受 cwd 下的相对路径，
    因此脚本会 cd 到 output_dir 再下载。
    """
    original_cwd = os.getcwd()
    abs_dir = os.path.abspath(output_dir)
    os.makedirs(abs_dir, exist_ok=True)
    os.chdir(abs_dir)

    downloaded = []
    try:
        for i, img in enumerate(images):
            output_name = f"img_{i+1}"
            result = run_lark([
                "docs", "+media-preview", "--token", img["token"],
                "--output", output_name, "--format", "json"
            ], f"download-img-{i+1}")
            if result and result.get("ok"):
                saved_path = result.get("data", {}).get("saved_path", "")
                downloaded.append({
                    "index": i, "token": img["token"], "name": img["name"],
                    "saved_path": saved_path, "full_tag": img["full_tag"]
                })
                print(f"  OK: {img['name']} -> {os.path.basename(saved_path)}")
            else:
                print(f"  FAIL: img {i+1} ({img['name']})", file=sys.stderr)
    finally:
        os.chdir(original_cwd)
    return downloaded


def build_content_with_placeholders(content, downloaded_images, sheet_replacements=None):
    """构建含图片占位的 XML 内容，同时替换嵌入电子表格为内联表格

    sheet_replacements: [{"full_tag": "...", "table_xml": "<table>...</table>"}, ...]
    """
    new_content = content
    # 先替换嵌入电子表格
    if sheet_replacements:
        for sheet in sheet_replacements:
            new_content = new_content.replace(sheet["full_tag"], sheet["table_xml"])
    # 再替换图片占位
    for img in downloaded_images:
        new_content = new_content.replace(img["full_tag"],
                                          f"[图片占位: {img['name']}]")
    return new_content


# ── 主流程 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="lark-doc-to-wiki 准备工作")
    parser.add_argument("--source-doc", required=True, help="源文档 URL 或 token")
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--target-token", help="目标知识库节点 token")
    target_group.add_argument("--target-name", help="目标知识库节点名称")
    parser.add_argument("--space-name", default=DEFAULT_SPACE_NAME,
                        help="知识空间名称（默认 K.B.LLM DEV）")
    parser.add_argument("--output-dir", default="./lark_doc_to_wiki_temp",
                        help="临时文件目录")
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    # lark-cli 文件路径要求是 cwd 下的相对路径
    rel_out = args.output_dir

    print("=" * 50)

    # Step 0: 解析目标父节点
    label = f"name '{args.target_name}'" if args.target_name else "token"
    print(f"Step 0: Resolving parent node by {label}...")
    resolved = resolve_target_node(
        name=args.target_name, token=args.target_token,
        space_name=args.space_name
    )
    if not resolved:
        sys.exit(1)
    parent_node_token, parent_obj_token, parent_title = resolved
    print(f"  Parent node: {parent_title}")
    print(f"  Parent doc ID: {parent_obj_token}")

    # Step 1: 获取源文档
    print("\nStep 1: Fetching source document...")
    content = fetch_document(args.source_doc)
    if not content:
        sys.exit(1)
    src_title = (re.search(r'<title>([^<]*)</title>', content)
                 or [None, "Untitled"]).group(1)
    print(f"  Source: {src_title}")

    # Step 2: 在父节点下新建子节点
    print(f"\nStep 2: Creating child node '{src_title}' under '{parent_title}'...")
    space_id = DEFAULT_SPACE_ID
    child = create_child_node(parent_node_token, src_title, space_id)
    if not child:
        sys.exit(1)
    child_node_token, target_doc_id = child
    print(f"  Child node token: {child_node_token}")

    # Step 3: 提取图片
    print("\nStep 3: Extracting image tokens...")
    images = extract_image_tokens(content)
    print(f"  Found {len(images)} image(s)")

    # Step 4: 提取并转换嵌入电子表格
    print("\nStep 4: Extracting and converting embedded sheets...")
    sheet_tags = extract_sheet_tags(content)
    print(f"  Found {len(sheet_tags)} embedded sheet(s)")
    sheet_replacements = []
    embedded_sheets = []
    if sheet_tags:
        for i, st in enumerate(sheet_tags):
            print(f"  [{i+1}/{len(sheet_tags)}] Sheet: token={st['token'][:16]}... sheet_id={st['sheet_id'][:8]}...")
            csv_result = fetch_sheet_csv(st["token"], st["sheet_id"])
            if csv_result:
                rows_data, col_indices = csv_result
                table_xml = csv_to_table_xml(rows_data, col_indices)
                if table_xml:
                    sheet_replacements.append({
                        "full_tag": st["full_tag"],
                        "table_xml": table_xml
                    })
                    embedded_sheets.append({
                        "token": st["token"],
                        "sheet_id": st["sheet_id"],
                        "converted": True,
                        "rows": len(rows_data),
                        "columns": len(col_indices)
                    })
                    print(f"    -> Converted to inline table ({len(rows_data)} rows x {len(col_indices)} cols)")
                else:
                    embedded_sheets.append({
                        "token": st["token"],
                        "sheet_id": st["sheet_id"],
                        "converted": False,
                        "error": "Empty result after conversion"
                    })
                    print(f"    -> Skipped: empty table", file=sys.stderr)
            else:
                embedded_sheets.append({
                    "token": st["token"],
                    "sheet_id": st["sheet_id"],
                    "converted": False,
                    "error": "Failed to read sheet data"
                })
                print(f"    -> Skipped: failed to read data (sheet may be inaccessible)", file=sys.stderr)
        print(f"  Converted {len(sheet_replacements)}/{len(sheet_tags)} sheet(s) to inline tables")
    else:
        print("  No embedded sheets found")

    # Step 5: 下载图片
    if images:
        print(f"\nStep 5: Downloading {len(images)} images...")
        downloaded = download_images(images, rel_out)
        print(f"  Downloaded {len(downloaded)}/{len(images)}")
    else:
        downloaded = []
        print("\nStep 5: No images to download")

    # Step 6: 构建含占位的 XML
    print("\nStep 6: Building content XML with placeholders...")
    xml_content = build_content_with_placeholders(content, downloaded, sheet_replacements)
    xml_rel = os.path.join(rel_out, "content.xml")
    with open(os.path.join(output_dir, "content.xml"), "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"  Saved: {xml_rel}")

    # 保存元信息
    meta = {
        "source_doc": args.source_doc,
        "source_title": src_title,
        "parent_node_token": parent_node_token,
        "parent_title": parent_title,
        "child_node_token": child_node_token,
        "target_doc_id": target_doc_id,
        "space_id": space_id,
        "downloaded_images": downloaded,
        "embedded_sheets": embedded_sheets,
        "xml_content_path": xml_rel,
        "output_dir": rel_out
    }
    meta_rel = os.path.join(rel_out, "meta.json")
    with open(os.path.join(output_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"\nMeta saved: {meta_rel}")
    print("=" * 50)

    # 输出下一步指引
    print(f"""
=== Next Steps ===
Child node created: "{src_title}" under "{parent_title}"
Target doc ID: {target_doc_id}

  Phase 1 — overwrite XML (fill the new blank document):
    lark-cli docs +update --api-version v2 --doc "{target_doc_id}" --command overwrite --doc-format xml --content @{xml_rel}

  Phase 2 — insert images (at end):
    # for each image in meta.json 'downloaded_images':
    lark-cli docs +media-insert --doc "{target_doc_id}" --file <saved_path> --align center

  Phase 3 — fetch block IDs, delete placeholders, move images:
    lark-cli docs +fetch --api-version v2 --doc "{target_doc_id}" --detail with-ids
    lark-cli docs +update --api-version v2 --doc "{target_doc_id}" --command block_delete --block-id <placeholder_ids>
    lark-cli docs +update --api-version v2 --doc "{target_doc_id}" --command block_move_after --block-id <target> --src-block-ids <img_block_id>

  Cleanup:
    python3 {sys.argv[0]} --cleanup
""")


def cleanup(output_dir="./lark_doc_to_wiki_temp"):
    """清理临时文件"""
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
        print(f"Cleaned up: {output_dir}")
    else:
        print(f"Not found: {output_dir}")


if __name__ == "__main__":
    if "--cleanup" in sys.argv:
        output_dir = "./lark_doc_to_wiki_temp"
        for i, arg in enumerate(sys.argv):
            if arg == "--output-dir" and i + 1 < len(sys.argv):
                output_dir = sys.argv[i + 1]
                break
        cleanup(output_dir)
    else:
        main()
