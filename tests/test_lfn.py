from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "cli" / "lfn.py"
MODULE_SPEC = importlib.util.spec_from_file_location("lfn_module", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"无法加载模块: {MODULE_PATH}")
lfn = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = lfn
MODULE_SPEC.loader.exec_module(lfn)


UTC8 = timezone(timedelta(hours=8))


class LfnTimestampTests(unittest.TestCase):
    """测试时间戳相关功能"""

    def test_add_note_to_date_appends_24_hour_timestamp(self) -> None:
        content = "2026.03.24\n\n- \n"
        now = datetime(2026, 3, 24, 9, 7, tzinfo=UTC8)

        updated = lfn.add_note_to_date(content, now, "今天记一条")

        self.assertIn("- 09:07 | 今天记一条", updated)

    def test_add_note_to_date_normalizes_existing_timestamp_suffix(self) -> None:
        content = "2026.03.24\n\n- \n"
        now = datetime(2026, 3, 24, 18, 45, tzinfo=UTC8)

        updated = lfn.add_note_to_date(content, now, "今天记一条 | 08:30")

        self.assertIn("- 08:30 | 今天记一条", updated)
        self.assertNotIn("- 今天记一条 | 08:30 | 18:45", updated)
        self.assertNotIn("- 今天记一条 | 08:30", updated)


class LfnDateTimeTests(unittest.TestCase):
    """测试日期时间相关函数"""

    def test_format_date(self) -> None:
        """测试日期格式化"""
        date = datetime(2026, 3, 24)
        self.assertEqual(lfn.format_date(date), "2026.03.24")

        date2 = datetime(2025, 12, 1)
        self.assertEqual(lfn.format_date(date2), "2025.12.01")

    def test_format_note_time(self) -> None:
        """测试笔记时间格式化"""
        date = datetime(2026, 3, 24, 9, 7)
        self.assertEqual(lfn.format_note_time(date), "09:07")

        date2 = datetime(2026, 3, 24, 23, 59)
        self.assertEqual(lfn.format_note_time(date2), "23:59")

        date3 = datetime(2026, 3, 24, 0, 0)
        self.assertEqual(lfn.format_note_time(date3), "00:00")

    def test_format_note_with_timestamp_adds_timestamp(self) -> None:
        """测试为笔记添加时间戳"""
        note = "这是一条笔记"
        date = datetime(2026, 3, 24, 9, 7)
        result = lfn.format_note_with_timestamp(note, date)
        self.assertEqual(result, "09:07 | 这是一条笔记")

    def test_format_note_with_timestamp_keeps_existing_timestamp(self) -> None:
        """测试保留已有时间戳的笔记"""
        note = "08:30 | 这是一条笔记"
        date = datetime(2026, 3, 24, 9, 7)
        result = lfn.format_note_with_timestamp(note, date)
        self.assertEqual(result, "08:30 | 这是一条笔记")

    def test_format_note_with_timestamp_normalizes_existing_suffix(self) -> None:
        """测试把已有后置时间统一成前置时间。"""
        note = "这是一条笔记 | 08:30"
        date = datetime(2026, 3, 24, 9, 7)
        result = lfn.format_note_with_timestamp(note, date)
        self.assertEqual(result, "08:30 | 这是一条笔记")

    def test_format_note_with_timestamp_empty_note(self) -> None:
        """测试空笔记处理"""
        note = "   "
        date = datetime(2026, 3, 24, 9, 7)
        result = lfn.format_note_with_timestamp(note, date)
        self.assertEqual(result, "")

    def test_parse_date_line_valid(self) -> None:
        """测试解析有效日期行"""
        result = lfn.parse_date_line("2026.03.24")
        self.assertIsNotNone(result)
        assert result is not None  # for type checker
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 3)
        self.assertEqual(result.day, 24)

    def test_parse_date_line_invalid(self) -> None:
        """测试解析无效日期行"""
        self.assertIsNone(lfn.parse_date_line("不是日期"))
        self.assertIsNone(lfn.parse_date_line("2026/03/24"))
        self.assertIsNone(lfn.parse_date_line("24.03.2026"))
        self.assertIsNone(lfn.parse_date_line(""))

    def test_parse_date_line_invalid_date(self) -> None:
        """测试解析无效日期值"""
        self.assertIsNone(lfn.parse_date_line("2026.13.45"))  # 无效月份和日期
        self.assertIsNone(lfn.parse_date_line("2026.02.30"))  # 无效日期

    def test_get_utc8_now(self) -> None:
        """测试获取 UTC+8 时间"""
        now = lfn.get_utc8_now()
        self.assertEqual(now.tzinfo.utcoffset(None), timedelta(hours=8))


class LfnDateSectionTests(unittest.TestCase):
    """测试日期 section 相关功能"""

    def test_check_date_exists_true(self) -> None:
        """测试检查存在的日期"""
        content = "2026.03.24\n\n- 笔记1\n- 笔记2\n\n2026.03.25\n\n- 笔记3"
        date = datetime(2026, 3, 24)
        self.assertTrue(lfn.check_date_exists(content, date))

    def test_check_date_exists_false(self) -> None:
        """测试检查不存在的日期"""
        content = "2026.03.24\n\n- 笔记1\n- 笔记2"
        date = datetime(2026, 3, 25)
        self.assertFalse(lfn.check_date_exists(content, date))

    def test_add_new_date(self) -> None:
        """测试添加新日期"""
        content = "2026.03.24\n\n- 笔记1"
        date = datetime(2026, 3, 25)
        result = lfn.add_new_date(content, date)
        self.assertIn("2026.03.25", result)
        self.assertIn("- ", result)

    def test_add_new_date_trims_trailing_whitespace(self) -> None:
        """测试添加新日期时修剪尾部空白"""
        content = "2026.03.24\n\n- 笔记1\n\n\n"
        date = datetime(2026, 3, 25)
        result = lfn.add_new_date(content, date)
        # 应该只有一个空行分隔
        self.assertIn("\n\n2026.03.25", result)


class LfnGetNotesTests(unittest.TestCase):
    """测试获取笔记功能"""

    def test_get_today_notes_with_notes(self) -> None:
        """测试获取有笔记的日期"""
        content = "2026.03.24\n\n- 笔记1\n- 笔记2\n\n2026.03.25\n\n- 笔记3"
        date = datetime(2026, 3, 24)
        notes = lfn.get_today_notes(content, date)
        self.assertEqual(notes, ["笔记1", "笔记2"])

    def test_get_today_notes_empty(self) -> None:
        """测试获取没有笔记的日期"""
        content = "2026.03.24\n\n- \n\n2026.03.25\n\n- 笔记1"
        date = datetime(2026, 3, 24)
        notes = lfn.get_today_notes(content, date)
        self.assertEqual(notes, [])

    def test_get_today_notes_not_exists(self) -> None:
        """测试获取不存在的日期"""
        content = "2026.03.24\n\n- 笔记1"
        date = datetime(2026, 3, 25)
        notes = lfn.get_today_notes(content, date)
        self.assertEqual(notes, [])

    def test_get_all_notes(self) -> None:
        """测试获取所有笔记"""
        content = """2026.03.24

- 笔记1
- 笔记2

2026.03.25

- 笔记3
-

2026.03.26

- 笔记4"""
        sections = lfn.get_all_notes(content)
        self.assertEqual(len(sections), 3)
        self.assertEqual(sections[0], ("2026.03.24", ["笔记1", "笔记2"]))
        self.assertEqual(sections[1], ("2026.03.25", ["笔记3"]))
        self.assertEqual(sections[2], ("2026.03.26", ["笔记4"]))

    def test_get_all_notes_empty(self) -> None:
        """测试空内容"""
        content = ""
        sections = lfn.get_all_notes(content)
        self.assertEqual(sections, [])

    def test_get_all_notes_no_notes(self) -> None:
        """测试没有笔记的日期"""
        content = "2026.03.24\n\n- \n\n2026.03.25\n\n- 笔记1"
        sections = lfn.get_all_notes(content)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0], ("2026.03.24", []))
        self.assertEqual(sections[1], ("2026.03.25", ["笔记1"]))


class LfnWeekRangeTests(unittest.TestCase):
    """测试周范围相关功能"""

    def test_get_last_week_range_monday(self) -> None:
        """测试从周一开始的上周范围"""
        # 2026年3月23日是周一
        monday = datetime(2026, 3, 23)
        start, end = lfn.get_last_week_range(monday)
        # 上周应该是3月16日（周一）到3月22日（周日）
        self.assertEqual(start, datetime(2026, 3, 16))
        self.assertEqual(end, datetime(2026, 3, 22))

    def test_get_last_week_range_sunday(self) -> None:
        """测试从周日开始的上周范围"""
        # 2026年3月22日是周日
        sunday = datetime(2026, 3, 22)
        start, end = lfn.get_last_week_range(sunday)
        # 上周应该是3月9日（周一）到3月15日（周日）
        self.assertEqual(start, datetime(2026, 3, 9))
        self.assertEqual(end, datetime(2026, 3, 15))

    def test_get_last_week_range_wednesday(self) -> None:
        """测试从周三开始的上周范围"""
        # 2026年3月25日是周三
        wednesday = datetime(2026, 3, 25)
        start, end = lfn.get_last_week_range(wednesday)
        # 上周应该是3月16日（周一）到3月22日（周日）
        self.assertEqual(start, datetime(2026, 3, 16))
        self.assertEqual(end, datetime(2026, 3, 22))

    def test_filter_sections_by_date_range(self) -> None:
        """测试按日期范围筛选"""
        sections = [
            ("2026.03.16", ["周一笔记"]),
            ("2026.03.17", ["周二笔记"]),
            ("2026.03.20", ["周五笔记"]),
            ("2026.03.23", ["下周一笔记"]),
        ]
        start = datetime(2026, 3, 16)
        end = datetime(2026, 3, 22)
        filtered = lfn.filter_sections_by_date_range(sections, start, end)
        self.assertEqual(len(filtered), 3)
        self.assertEqual(filtered[0], ("2026.03.16", ["周一笔记"]))
        self.assertEqual(filtered[1], ("2026.03.17", ["周二笔记"]))
        self.assertEqual(filtered[2], ("2026.03.20", ["周五笔记"]))

    def test_filter_sections_by_date_range_empty(self) -> None:
        """测试按日期范围筛选无结果"""
        sections = [
            ("2026.03.16", ["周一笔记"]),
        ]
        start = datetime(2026, 3, 20)
        end = datetime(2026, 3, 22)
        filtered = lfn.filter_sections_by_date_range(sections, start, end)
        self.assertEqual(filtered, [])

    def test_render_week_notes_markdown(self) -> None:
        """测试渲染周笔记 Markdown"""
        sections = [
            ("2026.03.16", ["周一笔记1", "周一笔记2"]),
            ("2026.03.17", ["周二笔记"]),
        ]
        start = datetime(2026, 3, 16)
        end = datetime(2026, 3, 22)
        result = lfn.render_week_notes_markdown(sections, start, end)
        # 代码中 week_number = isocalendar().week + 1，所以第12周会显示为第13周
        self.assertIn("# 第13周", result)
        self.assertIn("2026.03.16 - 2026.03.22", result)
        self.assertIn("## 2026.03.16", result)
        self.assertIn("- 周一笔记1", result)
        self.assertIn("- 周二笔记", result)

    def test_render_week_notes_markdown_empty(self) -> None:
        """测试渲染空周笔记"""
        sections: list[tuple[str, list[str]]] = []
        start = datetime(2026, 3, 16)
        end = datetime(2026, 3, 22)
        result = lfn.render_week_notes_markdown(sections, start, end)
        # 代码中 week_number = isocalendar().week + 1，所以第12周会显示为第13周
        self.assertIn("# 第13周", result)
        self.assertIn("(这一周还没有 note)", result)


class LfnDocumentTests(unittest.TestCase):
    """测试文档处理功能"""

    def test_normalize_document_text(self) -> None:
        """测试文档文本规范化"""
        content = "Line 1\r\nLine 2\rLine 3\n\n\n"
        result = lfn.normalize_document_text(content)
        self.assertEqual(result, "Line 1\nLine 2\nLine 3\n")

    def test_normalize_document_text_already_normalized(self) -> None:
        """测试已规范化的文本"""
        content = "Line 1\nLine 2\nLine 3\n"
        result = lfn.normalize_document_text(content)
        self.assertEqual(result, "Line 1\nLine 2\nLine 3\n")

    def test_find_date_section_range(self) -> None:
        """测试查找日期 section 范围"""
        lines = [
            "2026.03.23",
            "",
            "- 笔记1",
            "2026.03.24",
            "",
            "- 笔记2",
        ]
        result = lfn.find_date_section_range(lines, "2026.03.24")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result, (3, 6))

    def test_find_date_section_range_not_found(self) -> None:
        """测试查找不存在的日期 section"""
        lines = ["2026.03.23", "", "- 笔记1"]
        result = lfn.find_date_section_range(lines, "2026.03.24")
        self.assertIsNone(result)

    def test_find_date_section_range_at_end(self) -> None:
        """测试查找末尾的日期 section"""
        lines = [
            "2026.03.23",
            "",
            "- 笔记1",
            "2026.03.24",
            "",
            "- 笔记2",
        ]
        result = lfn.find_date_section_range(lines, "2026.03.23")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result, (0, 3))

    def test_parse_note_editor_text(self) -> None:
        """测试解析编辑器文本"""
        text = "笔记1\n笔记2\n- 笔记3\n\n- \n笔记4"
        result = lfn.parse_note_editor_text(text)
        self.assertEqual(result, ["笔记1", "笔记2", "笔记3", "笔记4"])

    def test_parse_note_editor_text_empty(self) -> None:
        """测试解析空编辑器文本"""
        text = "\n\n- \n\n"
        result = lfn.parse_note_editor_text(text)
        self.assertEqual(result, [])

    def test_replace_notes_for_date(self) -> None:
        """测试替换日期笔记"""
        content = "2026.03.24\n\n- 旧笔记1\n- 旧笔记2\n\n2026.03.25\n\n- 其他笔记"
        date = datetime(2026, 3, 24)
        new_notes = ["新笔记1", "新笔记2"]
        result = lfn.replace_notes_for_date(content, date, new_notes)
        self.assertIn("- 新笔记1", result)
        self.assertIn("- 新笔记2", result)
        self.assertNotIn("旧笔记1", result)
        self.assertIn("- 其他笔记", result)

    def test_replace_notes_for_date_adds_date_if_not_exists(self) -> None:
        """测试替换不存在的日期笔记"""
        content = "2026.03.23\n\n- 笔记\n"
        date = datetime(2026, 3, 24)
        new_notes = ["新笔记"]
        result = lfn.replace_notes_for_date(content, date, new_notes)
        self.assertIn("2026.03.24", result)
        self.assertIn("- 新笔记", result)

    def test_replace_notes_for_date_empty_notes(self) -> None:
        """测试替换为空笔记列表"""
        content = "2026.03.24\n\n- 旧笔记\n"
        date = datetime(2026, 3, 24)
        new_notes: list[str] = []
        result = lfn.replace_notes_for_date(content, date, new_notes)
        self.assertIn("- ", result)
        self.assertNotIn("旧笔记", result)

    def test_build_today_editor_text(self) -> None:
        """测试构建今天编辑器文本"""
        content = "2026.03.24\n\n- 笔记1\n- 笔记2\n\n2026.03.25\n\n- 笔记3"
        date = datetime(2026, 3, 24)
        result = lfn.build_today_editor_text(content, date)
        self.assertEqual(result, "笔记1\n笔记2")


class LfnAddNoteTests(unittest.TestCase):
    """测试添加笔记功能"""

    def test_add_note_to_date_new_date(self) -> None:
        """测试向新日期添加笔记 - add_note_to_date 需要日期已存在"""
        # 先添加日期，然后添加笔记
        content = "2026.03.23\n\n- 笔记\n"
        date = datetime(2026, 3, 24, 10, 30)
        # 先用 add_new_date 创建日期
        content_with_date = lfn.add_new_date(content, date)
        # 然后再添加笔记
        result = lfn.add_note_to_date(content_with_date, date, "新笔记")
        self.assertIn("2026.03.24", result)
        self.assertIn("- 10:30 | 新笔记", result)

    def test_add_note_to_date_existing_date_replace_empty(self) -> None:
        """测试替换空笔记行"""
        content = "2026.03.24\n\n- \n"
        date = datetime(2026, 3, 24, 10, 30)
        result = lfn.add_note_to_date(content, date, "新笔记")
        self.assertIn("- 10:30 | 新笔记", result)
        # 应该没有空笔记行
        self.assertNotIn("- \n- 新笔记", result)

    def test_add_note_to_date_add_to_existing(self) -> None:
        """测试向已有笔记的日期添加"""
        content = "2026.03.24\n\n- 笔记1\n"
        date = datetime(2026, 3, 24, 10, 30)
        result = lfn.add_note_to_date(content, date, "笔记2")
        self.assertIn("- 笔记1", result)
        self.assertIn("- 10:30 | 笔记2", result)

    def test_add_note_to_date_between_dates(self) -> None:
        """测试在两个日期之间添加笔记 - 手动构建包含中间日期的内容"""
        # 手动构建包含 3月24日 的内容
        content = "2026.03.23\n\n- 笔记1\n\n2026.03.24\n\n- \n\n2026.03.25\n\n- 笔记2\n"
        date = datetime(2026, 3, 24, 10, 30)
        # 添加笔记到已有的 3月24日
        result = lfn.add_note_to_date(content, date, "中间笔记")
        # 应该在3月23和3月25之间
        lines = result.split("\n")
        date_23_idx = next(i for i, line in enumerate(lines) if "2026.03.23" in line)
        date_24_idx = next(i for i, line in enumerate(lines) if "2026.03.24" in line)
        date_25_idx = next(i for i, line in enumerate(lines) if "2026.03.25" in line)
        self.assertLess(date_23_idx, date_24_idx)
        self.assertLess(date_24_idx, date_25_idx)

    def test_add_note_to_date_at_end(self) -> None:
        """测试在文件末尾添加笔记"""
        content = "2026.03.24\n\n- 笔记1\n"
        date = datetime(2026, 3, 24, 10, 30)
        result = lfn.add_note_to_date(content, date, "笔记2")
        self.assertIn("- 笔记1", result)
        self.assertIn("- 10:30 | 笔记2", result)


class LfnUtilityTests(unittest.TestCase):
    """测试工具函数"""

    def test_format_command_message_both(self) -> None:
        """测试格式化命令消息 - stdout 和 stderr 都有"""
        result = lfn.format_command_message("stdout内容", "stderr内容", default="默认")
        self.assertIn("stdout内容", result)
        self.assertIn("stderr内容", result)

    def test_format_command_message_stdout_only(self) -> None:
        """测试格式化命令消息 - 只有 stdout"""
        result = lfn.format_command_message("stdout内容", None, default="默认")
        self.assertEqual(result, "stdout内容")

    def test_format_command_message_empty(self) -> None:
        """测试格式化命令消息 - 都为空"""
        result = lfn.format_command_message(None, "   ", default="默认消息")
        self.assertEqual(result, "默认消息")


class LfnBuildNumberedNotesTests(unittest.TestCase):
    """测试编号笔记构建功能"""

    def test_build_numbered_notes(self) -> None:
        """测试构建编号笔记"""
        notes = ["笔记1", "笔记2", "笔记3"]
        table = lfn.build_numbered_notes(notes)
        self.assertIsNotNone(table)

    def test_build_numbered_notes_single(self) -> None:
        """测试构建单个编号笔记"""
        notes = ["笔记1"]
        table = lfn.build_numbered_notes(notes)
        self.assertIsNotNone(table)

    def test_build_numbered_notes_empty(self) -> None:
        """测试构建空笔记列表"""
        notes: list[str] = []
        table = lfn.build_numbered_notes(notes)
        self.assertIsNotNone(table)

    def test_build_numbered_notes_many(self) -> None:
        """测试构建大量编号笔记"""
        notes = [f"笔记{i}" for i in range(1, 101)]
        table = lfn.build_numbered_notes(notes)
        self.assertIsNotNone(table)


if __name__ == "__main__":
    unittest.main()
