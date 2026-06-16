#!/usr/bin/env python3
"""
lark-doc-to-wiki 准备工作脚本

功能：
1. 通过 wiki_tree.py 查找知识库父节点（SQLite + FTS5 搜索，内置按需同步）
2. 在父节点下新建子节点（使用源文档标题）
3. 读取源文档内容，提取图片 token
4. 下载所有图片到临时目录
5. 构建含图片占位的 XML 内容文件

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
        "--doc", doc_url, "--format", "json"
    ], "fetch-source-doc")
    if not result or not result.get("ok"):
        print("  Failed to fetch source document", file=sys.stderr)
        return None
    return result.get("data", {}).get("document", {}).get("content", "")


def extract_image_tokens(content):
    """从文档 XML 中提取所有图片 token"""
    images = []
    pattern = re.compile(r'<img\s[^>]*?src="([^"]+)"[^>]*?/?>')
    for match in pattern.finditer(content):
        token = match.group(1)
        full_tag = match.group(0)
        name_match = re.search(r'name="([^"]*)"', full_tag)
        name = name_match.group(1) if name_match else f"img_{token[:8]}"
        images.append({"token": token, "name": name, "full_tag": full_tag})
    return images


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


def build_content_with_placeholders(content, downloaded_images):
    """构建含图片占位的 XML 内容"""
    new_content = content
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

    # Step 4: 下载图片
    if images:
        print(f"\nStep 4: Downloading {len(images)} images...")
        downloaded = download_images(images, rel_out)
        print(f"  Downloaded {len(downloaded)}/{len(images)}")
    else:
        downloaded = []
        print("\nStep 4: No images to download")

    # Step 5: 构建含占位的 XML
    print("\nStep 5: Building content XML with placeholders...")
    xml_content = build_content_with_placeholders(content, downloaded)
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
    lark-cli docs +update --api-version v2 --doc "{target_doc_id}" --command overwrite --content @{xml_rel}

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
