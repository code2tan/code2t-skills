#!/usr/bin/env python3
"""
prepare.py 中纯函数的单元测试

只测试不依赖外部 IO（lark-cli、文件系统、网络）的函数：
  - extract_image_tokens
  - extract_sheet_tags
  - csv_to_table_xml
  - build_content_with_placeholders

运行（从 lark-doc-to-wiki/ 根目录或仓库根目录均可）：
  python3 lark-doc-to-wiki/tests/test_prepare.py
  # 或
  python3 -m unittest discover lark-doc-to-wiki/tests

退出码 0 表示全部通过；非 0 表示有失败。
"""

import io
import sys
import os
import unittest
from contextlib import redirect_stdout, redirect_stderr

# 测试位于 tests/，被测代码位于 ../scripts/，把 scripts 加进 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
sys.path.insert(0, _SCRIPTS_DIR)
import prepare  # noqa: E402


def _silently(callable_, *args, **kwargs):
    """运行函数并丢弃 stdout/stderr，返回结果"""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return callable_(*args, **kwargs)


class TestExtractImageTokens(unittest.TestCase):
    def test_token_attr_format(self):
        # fetch v2 返回 token="..." 形式
        content = '<doc><img token="abc123" name="cat.png"/></doc>'
        imgs = prepare.extract_image_tokens(content)
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0]["token"], "abc123")
        self.assertEqual(imgs[0]["name"], "cat.png")

    def test_src_attr_format(self):
        # 兼容 src="..." 形式
        content = '<doc><img src="xyz789"/></doc>'
        imgs = prepare.extract_image_tokens(content)
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0]["token"], "xyz789")
        # 没有 name 属性时，自动生成 img_<token前8位>
        self.assertEqual(imgs[0]["name"], "img_xyz789")

    def test_multiple_images_preserve_order(self):
        content = (
            '<doc>'
            '<img token="t1" name="a.png"/>'
            '<p>between</p>'
            '<img token="t2" name="b.png"/>'
            '</doc>'
        )
        imgs = prepare.extract_image_tokens(content)
        self.assertEqual([i["token"] for i in imgs], ["t1", "t2"])

    def test_no_images(self):
        self.assertEqual(prepare.extract_image_tokens("<doc>no img</doc>"), [])


class TestExtractSheetTags(unittest.TestCase):
    def test_paired_tags(self):
        content = '<sheet token="abc" sheet-id="s1"></sheet>'
        sheets = _silently(prepare.extract_sheet_tags, content)
        self.assertEqual(len(sheets), 1)
        self.assertEqual(sheets[0]["token"], "abc")
        self.assertEqual(sheets[0]["sheet_id"], "s1")
        self.assertEqual(sheets[0]["full_tag"], '<sheet token="abc" sheet-id="s1"></sheet>')

    def test_self_closing_tags(self):
        content = '<sheet token="abc" sheet-id="s1"/>'
        sheets = _silently(prepare.extract_sheet_tags, content)
        self.assertEqual(len(sheets), 1)
        self.assertEqual(sheets[0]["full_tag"], '<sheet token="abc" sheet-id="s1"/>')

    def test_self_closing_with_space(self):
        # 自闭合带空格的形式 <sheet ... />
        content = '<sheet token="abc" sheet-id="s1" />'
        sheets = _silently(prepare.extract_sheet_tags, content)
        self.assertEqual(len(sheets), 1)

    def test_skips_blank_type(self):
        content = '<sheet token="abc" sheet-id="s1" type="blank"></sheet>'
        sheets = _silently(prepare.extract_sheet_tags, content)
        self.assertEqual(sheets, [])

    def test_skips_missing_attrs(self):
        # 缺 sheet-id
        content = '<sheet token="abc"></sheet>'
        sheets = _silently(prepare.extract_sheet_tags, content)
        self.assertEqual(sheets, [])

    def test_attribute_order_insensitive(self):
        content = '<sheet sheet-id="s1" token="abc"></sheet>'
        sheets = _silently(prepare.extract_sheet_tags, content)
        self.assertEqual(len(sheets), 1)
        self.assertEqual(sheets[0]["token"], "abc")
        self.assertEqual(sheets[0]["sheet_id"], "s1")

    def test_multiple_sheets_no_overlap(self):
        # 两个相邻的 sheet 标签必须分别匹配，非贪婪 .*? 应就近匹配
        content = (
            '<sheet token="t1" sheet-id="s1"></sheet>'
            '<p>middle</p>'
            '<sheet token="t2" sheet-id="s2"></sheet>'
        )
        sheets = _silently(prepare.extract_sheet_tags, content)
        self.assertEqual(len(sheets), 2)
        self.assertEqual(sheets[0]["token"], "t1")
        self.assertEqual(sheets[1]["token"], "t2")
        # 关键：不能把两个 sheet 合并成一个 full_tag
        self.assertNotIn("t2", sheets[0]["full_tag"])
        self.assertNotIn("</sheet><p>", sheets[0]["full_tag"])

    def test_sheet_with_inner_content(self):
        # 飞书可能在 <sheet> 内塞缩略图标签等内容
        content = '<sheet token="abc" sheet-id="s1"><thumb url="x"/></sheet>'
        sheets = _silently(prepare.extract_sheet_tags, content)
        self.assertEqual(len(sheets), 1)
        # full_tag 应包含完整的元素，包括内部内容
        self.assertIn("<thumb", sheets[0]["full_tag"])
        self.assertTrue(sheets[0]["full_tag"].endswith("</sheet>"))

    def test_no_sheet(self):
        content = '<doc><p>no sheet</p></doc>'
        self.assertEqual(_silently(prepare.extract_sheet_tags, content), [])


class TestCsvToTableXml(unittest.TestCase):
    def test_empty_inputs(self):
        self.assertEqual(prepare.csv_to_table_xml([], []), "")
        self.assertEqual(prepare.csv_to_table_xml([], ["A"]), "")
        self.assertEqual(prepare.csv_to_table_xml([{"row_number": 1, "values": {}}], []), "")

    def test_basic_two_rows(self):
        rows = [
            {"row_number": 1, "values": {"A": "Name", "B": "Age"}},
            {"row_number": 2, "values": {"A": "Alice", "B": "30"}},
        ]
        xml = prepare.csv_to_table_xml(rows, ["A", "B"])
        self.assertIn("<thead><tr><th>Name</th><th>Age</th></tr></thead>", xml)
        self.assertIn("<tbody><tr><td>Alice</td><td>30</td></tr></tbody>", xml)
        self.assertTrue(xml.startswith("<table>"))
        self.assertTrue(xml.endswith("</table>"))

    def test_xml_escaping(self):
        # 单元格内容含 & < > 必须被转义
        rows = [
            {"row_number": 1, "values": {"A": "<header>"}},
            {"row_number": 2, "values": {"A": "a & b > c"}},
        ]
        xml = prepare.csv_to_table_xml(rows, ["A"])
        self.assertIn("<th>&lt;header&gt;</th>", xml)
        self.assertIn("<td>a &amp; b &gt; c</td>", xml)
        # 没有未转义的尖括号或与号穿透到表格中
        self.assertNotIn("<header>", xml.replace("&lt;header&gt;", ""))

    def test_none_cell_treated_as_empty(self):
        rows = [
            {"row_number": 1, "values": {"A": "h"}},
            {"row_number": 2, "values": {"A": None}},
        ]
        xml = prepare.csv_to_table_xml(rows, ["A"])
        self.assertIn("<td></td>", xml)

    def test_missing_col_in_row_treated_as_empty(self):
        # row 缺少某列时，应得到空 td 而不是 KeyError
        rows = [
            {"row_number": 1, "values": {"A": "h1", "B": "h2"}},
            {"row_number": 2, "values": {"A": "v1"}},  # 缺 B
        ]
        xml = prepare.csv_to_table_xml(rows, ["A", "B"])
        self.assertIn("<td>v1</td><td></td>", xml)

    def test_single_row_no_tbody(self):
        # 只有一行（即只有表头）时，不应生成 tbody
        rows = [{"row_number": 1, "values": {"A": "x"}}]
        xml = prepare.csv_to_table_xml(rows, ["A"])
        self.assertIn("<thead>", xml)
        self.assertNotIn("<tbody>", xml)


class TestBuildContentWithPlaceholders(unittest.TestCase):
    """关键回归测试：
    - sheet 替换在 img 替换之前；替换后无残留闭合标签
    - img 占位包在 <p> 中（避免 overwrite 时被丢弃）
    - 占位带 1-based 索引（让重名图片能被唯一定位）
    """

    def test_sheet_replaced_before_img(self):
        # 验证 sheet 替换发生在 img 替换之前的执行顺序
        content = (
            '<doc>'
            '<sheet token="t1" sheet-id="s1"></sheet>'
            '<img token="img-tok" name="x.png"/>'
            '</doc>'
        )
        downloaded = [{
            "index": 0,
            "full_tag": '<img token="img-tok" name="x.png"/>',
            "name": "x.png",
        }]
        sheet_replacements = [{
            "full_tag": '<sheet token="t1" sheet-id="s1"></sheet>',
            "table_xml": "<table><tr><td>data</td></tr></table>",
        }]
        result = prepare.build_content_with_placeholders(
            content, downloaded, sheet_replacements
        )
        self.assertIn("<table><tr><td>data</td></tr></table>", result)
        # 占位必须包在 <p> 里且带索引号 #1
        self.assertIn("<p>[图片占位 #1: x.png]</p>", result)
        # 关键：替换后绝不能残留 <sheet 或 </sheet>
        self.assertNotIn("<sheet", result)
        self.assertNotIn("</sheet>", result)
        # 也不能有残留的 img 标签
        self.assertNotIn("<img", result)

    def test_placeholder_wrapped_in_p_tag(self):
        # 占位必须包在 <p> 中——这是为了让飞书 overwrite 时把它当成正常段落 block
        content = '<doc><img token="t" name="image.png"/></doc>'
        downloaded = [{
            "index": 0,
            "full_tag": '<img token="t" name="image.png"/>',
            "name": "image.png",
        }]
        result = prepare.build_content_with_placeholders(content, downloaded, None)
        self.assertEqual(result, '<doc><p>[图片占位 #1: image.png]</p></doc>')

    def test_placeholders_are_unique_with_index(self):
        # 多张同名图片（飞书默认都是 image.png）必须靠索引号区分
        content = (
            '<doc>'
            '<img token="t1" name="image.png"/>'
            '<p>middle</p>'
            '<img token="t2" name="image.png"/>'
            '</doc>'
        )
        downloaded = [
            {"index": 0, "full_tag": '<img token="t1" name="image.png"/>', "name": "image.png"},
            {"index": 1, "full_tag": '<img token="t2" name="image.png"/>', "name": "image.png"},
        ]
        result = prepare.build_content_with_placeholders(content, downloaded, None)
        self.assertIn("<p>[图片占位 #1: image.png]</p>", result)
        self.assertIn("<p>[图片占位 #2: image.png]</p>", result)
        # 两个占位字符串必须不一致
        self.assertNotEqual(
            result.count("<p>[图片占位 #1: image.png]</p>"), 0
        )
        self.assertNotEqual(
            result.count("<p>[图片占位 #2: image.png]</p>"), 0
        )

    def test_no_sheet_replacements(self):
        # sheet_replacements 为 None 或空列表时不影响 img 替换
        content = '<doc><img token="t" name="a.png"/></doc>'
        downloaded = [{
            "index": 0,
            "full_tag": '<img token="t" name="a.png"/>',
            "name": "a.png",
        }]
        # None
        r1 = prepare.build_content_with_placeholders(content, downloaded, None)
        self.assertIn("<p>[图片占位 #1: a.png]</p>", r1)
        # 空列表
        r2 = prepare.build_content_with_placeholders(content, downloaded, [])
        self.assertEqual(r1, r2)

    def test_blank_sheet_preserved(self):
        # blank sheet 不在 sheet_replacements 中，原样保留
        # （应当仍然是允许的 — 上层 SKILL.md 要求 agent 验证后告知用户）
        content = '<doc><sheet token="t" sheet-id="s" type="blank"></sheet></doc>'
        result = prepare.build_content_with_placeholders(content, [], [])
        self.assertIn('type="blank"', result)


class TestColumnHelpers(unittest.TestCase):
    """字母列号 ↔ 索引互转、A1 range → 列字母列表的纯函数测试。

    这些是 lark-cli 1.x 不再返回 col_indices 后的兜底实现；
    必须保证常见 spreadsheet 范围都能正确还原列序。
    """

    def test_alpha_to_idx_single(self):
        self.assertEqual(prepare._alpha_to_idx("A"), 0)
        self.assertEqual(prepare._alpha_to_idx("B"), 1)
        self.assertEqual(prepare._alpha_to_idx("Z"), 25)

    def test_alpha_to_idx_double(self):
        self.assertEqual(prepare._alpha_to_idx("AA"), 26)
        self.assertEqual(prepare._alpha_to_idx("AZ"), 51)
        self.assertEqual(prepare._alpha_to_idx("BA"), 52)

    def test_idx_to_alpha_roundtrip(self):
        for letters in ["A", "Z", "AA", "AZ", "BA", "ZZ", "AAA"]:
            self.assertEqual(
                prepare._idx_to_alpha(prepare._alpha_to_idx(letters)),
                letters,
            )

    def test_alpha_range_simple(self):
        self.assertEqual(prepare._alpha_range("A", "C"), ["A", "B", "C"])
        self.assertEqual(prepare._alpha_range("A", "A"), ["A"])

    def test_alpha_range_across_double(self):
        # Y, Z, AA, AB
        self.assertEqual(prepare._alpha_range("Y", "AB"), ["Y", "Z", "AA", "AB"])

    def test_derive_col_indices_from_range(self):
        # 来自 +csv-get 的 actual_range="A1:C6"
        cols = prepare._derive_col_indices("A1:C6", [])
        self.assertEqual(cols, ["A", "B", "C"])

    def test_derive_col_indices_from_rows_when_range_missing(self):
        # 没有 range 时，从 rows 中收集出现过的列字母并按字母顺序排序
        rows = [
            {"row_number": 1, "values": {"A": "x", "C": "z"}},
            {"row_number": 2, "values": {"B": "y"}},
        ]
        cols = prepare._derive_col_indices(None, rows)
        self.assertEqual(cols, ["A", "B", "C"])

    def test_derive_col_indices_handles_double_letter_range(self):
        cols = prepare._derive_col_indices("A1:AB10", [])
        # 总共 28 列：A..Z, AA, AB
        self.assertEqual(len(cols), 28)
        self.assertEqual(cols[0], "A")
        self.assertEqual(cols[-1], "AB")


class TestEndToEndSheetExtractionAndReplacement(unittest.TestCase):
    """
    端到端验证：从 fetched XML 提取 sheet → 假装成功转换 → 替换 → 校验无残留。
    这是修复 #1（残留 </sheet> 污染 XML）的真正回归测试。
    """

    def test_paired_tag_no_residue(self):
        original = (
            '<doc>'
            '<p>before</p>'
            '<sheet token="ABC" sheet-id="S1"></sheet>'
            '<p>after</p>'
            '</doc>'
        )
        sheets = _silently(prepare.extract_sheet_tags, original)
        self.assertEqual(len(sheets), 1)
        replacements = [{
            "full_tag": sheets[0]["full_tag"],
            "table_xml": "<table>OK</table>",
        }]
        result = prepare.build_content_with_placeholders(original, [], replacements)
        self.assertEqual(
            result,
            '<doc><p>before</p><table>OK</table><p>after</p></doc>'
        )

    def test_self_closing_no_residue(self):
        original = '<doc><sheet token="ABC" sheet-id="S1"/></doc>'
        sheets = _silently(prepare.extract_sheet_tags, original)
        replacements = [{
            "full_tag": sheets[0]["full_tag"],
            "table_xml": "<table>OK</table>",
        }]
        result = prepare.build_content_with_placeholders(original, [], replacements)
        self.assertEqual(result, '<doc><table>OK</table></doc>')

    def test_two_adjacent_sheets_no_overlap(self):
        original = (
            '<sheet token="t1" sheet-id="s1"></sheet>'
            '<sheet token="t2" sheet-id="s2"></sheet>'
        )
        sheets = _silently(prepare.extract_sheet_tags, original)
        self.assertEqual(len(sheets), 2)
        replacements = [
            {"full_tag": sheets[0]["full_tag"], "table_xml": "<table>A</table>"},
            {"full_tag": sheets[1]["full_tag"], "table_xml": "<table>B</table>"},
        ]
        result = prepare.build_content_with_placeholders(original, [], replacements)
        self.assertEqual(result, '<table>A</table><table>B</table>')


if __name__ == "__main__":
    unittest.main(verbosity=2)
