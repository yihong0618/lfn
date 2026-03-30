#!/usr/bin/env python3
"""
用法:
  lfn                     检查/添加当天条目，显示笔记
  lfn <笔记内容>          添加一条笔记到当天
  lfn all                 显示全部日期的笔记
  lfn --week              用 Markdown 打印上周的全部笔记
  lfn --edit              用 Textual 编辑当天笔记
  lfn all --edit          用 Textual 编辑整个 README
  lfn -a, --add <内容>    添加一条笔记到当天
  lfn -s, --show          只显示当天笔记
  lfn -h, --help          显示帮助
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from rich.console import Console
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()


DISCOVERY_ATTEMPTS: list[Path] = []
NOTE_TIME_PREFIX_RE = re.compile(r"^(?P<time>\d{2}:\d{2})\s*\|\s*(?P<body>.+)$")
NOTE_TIME_SUFFIX_RE = re.compile(r"^(?P<body>.+?)\s*\|\s*(?P<time>\d{2}:\d{2})$")


@dataclass
class SaveOutcome:
    message: str
    severity: str = "information"


def discover_source_dir_from_distribution() -> list[Path]:
    """从已安装包的 direct_url 元数据反查源码目录。"""
    try:
        dist = metadata.distribution("lfn")
    except metadata.PackageNotFoundError:
        return []

    direct_url_raw = dist.read_text("direct_url.json")
    if not direct_url_raw:
        return []

    try:
        direct_url = json.loads(direct_url_raw)
    except json.JSONDecodeError:
        return []

    source_url = direct_url.get("url")
    if not isinstance(source_url, str):
        return []

    parsed = urlparse(source_url)
    if parsed.scheme != "file":
        return []

    source_path = unquote(parsed.path)
    if parsed.netloc:
        source_path = f"//{parsed.netloc}{source_path}"
    source_dir = Path(source_path).expanduser()

    return [source_dir, source_dir.parent]


def discover_readme_path() -> Path | None:
    """自动发现 README 路径。"""
    global DISCOVERY_ATTEMPTS
    env_dir = os.environ.get("LIFE_NOTE_DIR")
    cwd = Path.cwd()
    file_dir = Path(__file__).resolve().parent
    home = Path.home()

    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    # 优先使用脚本所在位置和常见源码目录，避免误命中当前工作目录的 README。
    candidates.extend(
        [
            file_dir.parent,
            file_dir,
            home / "repos" / "life_note",
            home / "side" / "life_note",
            home / "life_note",
        ]
    )

    # 从安装元数据反查源码目录（例如 uv tool install 本地路径时）。
    candidates.extend(discover_source_dir_from_distribution())

    # 扫描常见工作目录下一层（如 ~/repos/*/life_note）。
    for root in (home / "repos", home / "side"):
        if root.is_dir():
            candidates.extend(root.glob("*/life_note"))

    # 最后才回退到运行目录。
    candidates.extend([cwd.parent, cwd])

    seen: set[Path] = set()
    attempts: list[Path] = []
    readme_only: list[Path] = []
    for directory in candidates:
        try:
            resolved_dir = directory.resolve()
        except OSError:
            continue

        if resolved_dir in seen:
            continue
        seen.add(resolved_dir)

        readme_path = resolved_dir / "README.md"
        attempts.append(readme_path)
        update_path = resolved_dir / "update.sh"
        if readme_path.exists() and update_path.exists():
            DISCOVERY_ATTEMPTS = attempts
            return readme_path
        if readme_path.exists():
            readme_only.append(readme_path)

    if readme_only:
        DISCOVERY_ATTEMPTS = attempts
        return readme_only[0]

    DISCOVERY_ATTEMPTS = attempts
    return None


README_PATH = discover_readme_path()
LIFE_NOTE_DIR = README_PATH.parent if README_PATH else Path.cwd().resolve().parent
UPDATE_SCRIPT = LIFE_NOTE_DIR / "update.sh"


def get_discovery_hints() -> str:
    if not DISCOVERY_ATTEMPTS:
        return ""

    preview = [str(path) for path in DISCOVERY_ATTEMPTS[:4]]
    if len(DISCOVERY_ATTEMPTS) > 4:
        preview.append("...")

    return "；已尝试: " + "、".join(preview)


def get_utc8_now() -> datetime:
    """获取 UTC+8 的当前时间"""
    utc8 = timezone(timedelta(hours=8))
    return datetime.now(utc8)


def format_date(date: datetime) -> str:
    """格式化日期为 README 中的格式: YYYY.MM.DD"""
    return date.strftime("%Y.%m.%d")


def format_note_time(date: datetime) -> str:
    """格式化笔记附加时间，使用 UTC+8 的 24 小时制 HH:MM。"""
    return date.strftime("%H:%M")


def format_note_with_timestamp(note: str, added_at: datetime) -> str:
    """为命令行添加的笔记统一补充前置时间。"""
    stripped_note = note.strip()
    if not stripped_note:
        return stripped_note

    prefix_match = NOTE_TIME_PREFIX_RE.match(stripped_note)
    if prefix_match is not None:
        return f"{prefix_match.group('time')} | {prefix_match.group('body').strip()}"

    suffix_match = NOTE_TIME_SUFFIX_RE.match(stripped_note)
    if suffix_match is not None:
        return f"{suffix_match.group('time')} | {suffix_match.group('body').strip()}"

    return f"{format_note_time(added_at)} | {stripped_note}"


def parse_date_line(line: str) -> datetime | None:
    """解析日期行，返回 datetime 对象"""
    line = line.strip()
    # 匹配 YYYY.MM.DD 格式
    match = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})$", line)
    if match:
        year, month, day = map(int, match.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return None


def read_readme() -> str:
    """读取 README 内容"""
    if README_PATH is None or not README_PATH.exists():
        console.print(
            f"[red]错误: 找不到 README.md。请设置 LIFE_NOTE_DIR{get_discovery_hints()}[/red]"
        )
        sys.exit(1)
    return README_PATH.read_text(encoding="utf-8")


def write_readme(content: str) -> None:
    """写入 README 内容"""
    if README_PATH is None:
        console.print(
            f"[red]错误: 找不到 README.md。请设置 LIFE_NOTE_DIR{get_discovery_hints()}[/red]"
        )
        sys.exit(1)
    README_PATH.write_text(content, encoding="utf-8")


def format_command_message(
    stdout: str | None, stderr: str | None, *, default: str
) -> str:
    """合并子进程输出，优先保留有意义的提示。"""
    parts = [part.strip() for part in (stdout, stderr) if part and part.strip()]
    return "\n".join(parts) or default


def check_date_exists(content: str, date: datetime) -> bool:
    """检查指定日期是否已存在"""
    date_str = format_date(date)
    for line in content.split("\n"):
        if parse_date_line(line) is not None:
            if line.strip() == date_str:
                return True
    return False


def add_new_date(content: str, date: datetime) -> str:
    """在 README 末尾添加新的日期条目"""
    date_str = format_date(date)

    # 确保内容以换行结尾
    content = content.rstrip()
    # 添加两个换行作为分隔，然后添加日期和空条目
    new_entry = f"\n\n{date_str}\n\n- \n"

    return content + new_entry


def get_today_notes(content: str, date: datetime) -> list[str]:
    """获取指定日期的所有笔记条目"""
    date_str = format_date(date)
    lines = content.split("\n")
    notes = []
    in_target_date = False

    for line in lines:
        stripped = line.strip()

        # 检查是否是日期行
        parsed_date = parse_date_line(stripped)
        if parsed_date is not None:
            if in_target_date:
                # 已经找到目标日期，现在遇到新日期，结束
                break
            if stripped == date_str:
                in_target_date = True
            continue

        # 如果在目标日期范围内，收集笔记
        if in_target_date and stripped.startswith("- "):
            note_content = stripped[2:].strip()
            if note_content:  # 只添加非空内容
                notes.append(note_content)

    return notes


def get_all_notes(content: str) -> list[tuple[str, list[str]]]:
    """获取所有日期的笔记，按 README 中出现顺序返回。"""
    lines = content.split("\n")
    sections: list[tuple[str, list[str]]] = []
    current_date: str | None = None
    current_notes: list[str] = []

    for line in lines:
        stripped = line.strip()
        parsed_date = parse_date_line(stripped)
        if parsed_date is not None:
            if current_date is not None:
                sections.append((current_date, current_notes))
            current_date = stripped
            current_notes = []
            continue

        if current_date is not None and stripped.startswith("- "):
            note_content = stripped[2:].strip()
            if note_content:
                current_notes.append(note_content)

    if current_date is not None:
        sections.append((current_date, current_notes))

    return sections


def get_last_week_range(reference_date: datetime) -> tuple[datetime, datetime]:
    """返回“上周”的起止日期（周一到周日）。"""
    reference_day = datetime(
        reference_date.year, reference_date.month, reference_date.day
    )
    current_week_start = reference_day - timedelta(days=reference_day.weekday())
    last_week_start = current_week_start - timedelta(days=7)
    last_week_end = current_week_start - timedelta(days=1)
    return last_week_start, last_week_end


def filter_sections_by_date_range(
    sections: list[tuple[str, list[str]]],
    start_date: datetime,
    end_date: datetime,
) -> list[tuple[str, list[str]]]:
    """筛选日期落在指定闭区间内的笔记 section。"""
    matched_sections: list[tuple[str, list[str]]] = []
    for date_str, notes in sections:
        parsed_date = parse_date_line(date_str)
        if parsed_date is None:
            continue
        if start_date <= parsed_date <= end_date:
            matched_sections.append((date_str, notes))
    return matched_sections


def render_week_notes_markdown(
    sections: list[tuple[str, list[str]]],
    start_date: datetime,
    end_date: datetime,
) -> str:
    """把上周笔记渲染为便于复制的 Markdown。"""
    week_number = int(start_date.isocalendar().week) + 1
    lines = [
        f"# 第{week_number}周",
        "",
        f"> {format_date(start_date)} - {format_date(end_date)}",
        "",
    ]

    if not sections:
        lines.append("(这一周还没有 note)")
        lines.append("")
        return "\n".join(lines)

    for date_str, notes in sections:
        lines.append(f"## {date_str}")
        lines.append("")
        if notes:
            lines.extend(f"- {note}" for note in notes)
        else:
            lines.append("- ")
        lines.append("")

    return "\n".join(lines)


def normalize_document_text(content: str) -> str:
    """统一换行，并确保文件以单个换行结尾。"""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return normalized + "\n"


def find_date_section_range(lines: list[str], date_str: str) -> tuple[int, int] | None:
    """找到日期 section 的 [start, end) 行区间。"""
    start: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        parsed_date = parse_date_line(stripped)
        if parsed_date is None:
            continue

        if start is None and stripped == date_str:
            start = index
            continue

        if start is not None:
            return start, index

    if start is None:
        return None
    return start, len(lines)


def parse_note_editor_text(text: str) -> list[str]:
    """把编辑器文本解析为笔记列表，每行一条。"""
    notes: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        if not stripped or stripped == "-":
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if stripped:
            notes.append(stripped)
    return notes


def replace_notes_for_date(content: str, date: datetime, notes: list[str]) -> str:
    """替换指定日期的所有笔记。"""
    date_str = format_date(date)
    updated_content = content
    if not check_date_exists(updated_content, date):
        updated_content = add_new_date(updated_content, date)

    lines = updated_content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    section_range = find_date_section_range(lines, date_str)
    if section_range is None:
        raise ValueError(f"找不到日期 section: {date_str}")

    start, end = section_range
    section_lines = [date_str, ""]
    if notes:
        section_lines.extend(f"- {note}" for note in notes)
    else:
        section_lines.append("- ")

    if end < len(lines):
        section_lines.append("")

    merged_lines = lines[:start] + section_lines + lines[end:]
    return normalize_document_text("\n".join(merged_lines))


def build_today_editor_text(content: str, date: datetime) -> str:
    """构建当天编辑器初始文本，每行一条笔记。"""
    return "\n".join(get_today_notes(content, date))


def save_readme_document(new_content: str, *, no_update: bool) -> SaveOutcome:
    """保存 README，并按需执行 update。"""
    current_content = read_readme()
    normalized_current = normalize_document_text(current_content)
    normalized_new = normalize_document_text(new_content)

    if normalized_new == normalized_current:
        return SaveOutcome("没有内容变化")

    write_readme(normalized_new)
    if no_update:
        return SaveOutcome("已保存")

    update_ok, update_message = execute_update()
    if update_ok:
        return SaveOutcome("已保存，并完成 update")
    return SaveOutcome(f"已保存，但 update 失败: {update_message}", severity="warning")


def build_today_save_callback(
    date: datetime, *, no_update: bool
) -> Callable[[str], SaveOutcome]:
    """构建当天编辑器保存回调。"""

    def save_callback(editor_text: str) -> SaveOutcome:
        current_content = read_readme()
        notes = parse_note_editor_text(editor_text)
        updated_content = replace_notes_for_date(current_content, date, notes)
        return save_readme_document(updated_content, no_update=no_update)

    return save_callback


def build_all_save_callback(*, no_update: bool) -> Callable[[str], SaveOutcome]:
    """构建全量 README 编辑器保存回调。"""

    def save_callback(editor_text: str) -> SaveOutcome:
        return save_readme_document(editor_text, no_update=no_update)

    return save_callback


def execute_git_pull() -> tuple[bool, str]:
    """运行 git pull，返回结果与消息。"""
    if not (LIFE_NOTE_DIR / ".git").exists():
        return False, f"找不到 git 仓库: {LIFE_NOTE_DIR}"

    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=LIFE_NOTE_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        message = format_command_message(
            error.stdout,
            error.stderr,
            default="git pull 执行失败",
        )
        return False, message

    message = format_command_message(
        result.stdout,
        result.stderr,
        default="git pull 完成",
    )
    return True, message


def run_git_pull_or_exit() -> None:
    """在写入前同步远端内容；失败时直接退出。"""
    console.print("[dim]正在执行 git pull...[/dim]")
    pull_ok, pull_message = execute_git_pull()
    if pull_ok:
        console.print("[green]✓ git pull 完成[/green]")
        if pull_message != "git pull 完成":
            console.print(f"[dim]{pull_message}[/dim]")
        return

    console.print(f"[red]git pull 失败: {pull_message}[/red]")
    sys.exit(1)


def execute_update() -> tuple[bool, str]:
    """运行 update.sh，返回结果与消息。"""
    if not UPDATE_SCRIPT.exists():
        return False, f"找不到 update 脚本: {UPDATE_SCRIPT}"

    try:
        result = subprocess.run(
            ["bash", str(UPDATE_SCRIPT)],
            cwd=LIFE_NOTE_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        message = format_command_message(
            error.stdout,
            error.stderr,
            default="update 执行失败",
        )
        return False, message

    message = format_command_message(
        result.stdout,
        result.stderr,
        default="update 完成",
    )
    return True, message


def run_update() -> None:
    """运行 update.sh 脚本"""
    console.print("[dim]正在运行 update...[/dim]")
    update_ok, update_message = execute_update()
    if update_ok:
        console.print("[green]✓ update 完成[/green]")
        return

    console.print(f"[yellow]update 执行失败: {update_message}[/yellow]")


def build_numbered_notes(
    notes: list[str], *, number_style: str = "bold bright_white"
) -> Table:
    """渲染固定序号列，保证两位数编号和换行正文对齐。"""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(
        "index", justify="right", width=max(2, len(str(len(notes))) + 1), no_wrap=True
    )
    table.add_column("content", ratio=1, overflow="fold")

    for i, note in enumerate(notes, 1):
        table.add_row(Text(f"{i}.", style=number_style), Text(note, style="white"))

    return table


def show_today_notes(date: datetime, notes: list[str]) -> None:
    """使用 rich 打印当天的笔记"""
    date_str = format_date(date)
    weekday = date.strftime("%A")  # 星期几

    # 创建标题
    title = Text(f"📓 Life Note - {date_str} ({weekday})", style="bold cyan")

    # 创建内容
    if not notes:
        content: Text | Table = Text("(还没有笔记，添加一条吧！)", style="dim italic")
    else:
        content = build_numbered_notes(notes, number_style="bold cyan")

    # 创建面板
    panel = Panel(content, title=title, border_style="bright_blue", padding=(1, 2))

    console.print()
    console.print(panel)
    console.print()


def show_all_notes(sections: list[tuple[str, list[str]]]) -> None:
    """使用 rich 打印全部日期的笔记。"""
    if not sections:
        console.print("\n[dim](README 里还没有任何日期笔记)</dim>\n")
        return

    console.print()
    console.print(
        Rule(
            Text(f"Life Note / {len(sections)} days", style="bold cyan"),
            style="bright_blue",
        )
    )
    console.print()

    for index, (date_str, notes) in enumerate(sections):
        console.print(Rule(Text(date_str, style="bold cyan"), style="bright_blue"))
        if not notes:
            content = Padding(
                Text("(当天还没有笔记)", style="dim italic"), (0, 0, 0, 2)
            )
        else:
            content = Padding(build_numbered_notes(notes), (0, 0, 0, 2))

        console.print(content)
        if index != len(sections) - 1:
            console.print()


def add_note_to_date(content: str, date: datetime, note: str) -> str:
    """添加一条笔记到指定日期"""
    date_str = format_date(date)
    note_with_timestamp = format_note_with_timestamp(note, date)
    lines = content.split("\n")
    new_lines: list[str] = []
    in_target_date = False
    inserted = False

    def append_note_with_clean_spacing(target: list[str]) -> None:
        """在追加笔记前移除段尾空行，避免空行累计。"""
        while target and target[-1].strip() == "":
            target.pop()
        if target and parse_date_line(target[-1].strip()) is not None:
            target.append("")
        target.append(f"- {note_with_timestamp}")

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 检查是否是日期行
        parsed_date = parse_date_line(stripped)
        if parsed_date is not None:
            if in_target_date:
                # 已经找到目标日期，现在遇到新日期，把笔记插入到这里之前
                if not inserted:
                    append_note_with_clean_spacing(new_lines)
                    inserted = True
                in_target_date = False
            elif stripped == date_str:
                in_target_date = True
            new_lines.append(line)
            continue

        # 如果在目标日期范围内，检查是否是空的笔记行
        if in_target_date and not inserted:
            if stripped == "-":
                # 替换空的笔记行
                new_lines.append(f"- {note_with_timestamp}")
                inserted = True
                continue
            elif stripped == "" and i + 1 < len(lines):
                # 检查下一行是否是空笔记行或新日期
                next_line = lines[i + 1].strip()
                next_is_date = parse_date_line(next_line) is not None
                if next_is_date or i == len(lines) - 1:
                    # 在空行前插入
                    new_lines.append(f"- {note_with_timestamp}")
                    inserted = True
                    new_lines.append(line)
                    continue

        new_lines.append(line)

    # 如果到最后还没插入（文件末尾）
    if in_target_date and not inserted:
        append_note_with_clean_spacing(new_lines)

    return "\n".join(new_lines)


def launch_textual_editor(
    *,
    initial_text: str,
    title: str,
    subtitle: str,
    save_callback: Callable[[str], SaveOutcome],
    note_mode: bool,
) -> None:
    """启动 Textual 编辑器。"""
    try:
        from textual import events
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.widgets import Footer, Header, Input, Static, TextArea
    except ImportError as error:
        console.print(
            "[red]错误: `--edit` 需要安装 `textual`。请在仓库根目录重新执行 "
            "`uv sync` 或 `uv tool install . --reinstall`。[/red]"
        )
        console.print(f"[dim]{error}[/dim]")
        sys.exit(1)

    class VimTextArea(TextArea):
        """在 normal 模式下拦截常见 vim 风格按键。"""

        async def _on_key(self, event: events.Key) -> None:
            app: LifeNoteEditor = self.app  # type: ignore[assignment]
            mode = getattr(app, "mode", "normal")

            if mode == "insert" and event.key == "escape":
                event.prevent_default()
                event.stop()
                app.action_normal_mode()
                return

            if mode != "normal":
                await super()._on_key(event)
                return

            if app.handle_normal_key(event.key, event.character):
                event.prevent_default()
                event.stop()
                return

            await super()._on_key(event)

    class LifeNoteEditor(App[None]):
        CSS = """
        Screen {
            layout: vertical;
        }

        #status {
            height: auto;
            padding: 0 1;
            color: $text-muted;
        }

        #editor {
            height: 1fr;
            border: round $accent;
        }

        #command_line {
            dock: bottom;
            margin: 0 1 1 1;
        }

        .hidden {
            display: none;
        }
        """

        BINDINGS = [
            Binding("ctrl+s", "save", "Save"),
            Binding("ctrl+q", "request_quit", "Quit"),
            Binding("ctrl+r", "redo", "Redo", show=False),
            Binding("escape", "normal_mode", "Normal", show=False),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.mode = "normal"
            self.saved_text = initial_text
            self.dirty = False
            self.pending_quit = False
            self.pending_normal_key: str | None = None

        @property
        def editor(self) -> VimTextArea:
            return self.query_one("#editor", VimTextArea)

        @property
        def status_bar(self) -> Static:
            return self.query_one("#status", Static)

        @property
        def command_line(self) -> Input:
            return self.query_one("#command_line", Input)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Static("", id="status")
            yield VimTextArea.code_editor(
                initial_text,
                id="editor",
                show_line_numbers=True,
            )
            yield Input(
                placeholder=":w | :q | :q! | :wq", id="command_line", classes="hidden"
            )
            yield Footer()

        def on_mount(self) -> None:
            self.title = title
            self.sub_title = subtitle
            self.editor.read_only = True
            self.editor.focus()
            self.refresh_status()

        def on_text_area_changed(self, event: TextArea.Changed) -> None:
            if event.text_area.id != "editor":
                return

            self.dirty = self.editor.text != self.saved_text
            self.pending_quit = False
            self.refresh_status()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id != "command_line":
                return

            self.handle_command(event.value)

        def refresh_status(self) -> None:
            dirty_text = "[+] 未保存" if self.dirty else "[=] 已保存"
            mode_help = {
                "normal": "NORMAL  i/a/o/O/I/A  h/j/k/l/w/b/0/$  gg/G  dd/dw/db/D/x  : 命令",
                "insert": "INSERT  Esc 返回 normal  Ctrl+S 保存  Ctrl+Q 退出",
                "command": "COMMAND  :w 保存  :q 退出  :q! 强退  :wq 保存退出",
            }
            extra = ""
            if self.pending_quit:
                extra = "  再按 Ctrl+Q 强制退出"
            elif self.pending_normal_key:
                extra = f"  等待组合键: {self.pending_normal_key}"
            if note_mode:
                extra += "  每行一条笔记"
            self.status_bar.update(f"{dirty_text}  {mode_help[self.mode]}{extra}")

        def action_enter_insert(self) -> None:
            self.mode = "insert"
            self.pending_quit = False
            self.pending_normal_key = None
            self.command_line.add_class("hidden")
            self.editor.read_only = False
            self.editor.focus()
            self.refresh_status()

        def action_normal_mode(self) -> None:
            previous_mode = self.mode
            self.mode = "normal"
            self.pending_quit = False
            self.pending_normal_key = None
            self.command_line.value = ""
            self.command_line.add_class("hidden")
            self.editor.read_only = True
            if previous_mode == "insert":
                _line_index, column = self.editor.selection.end
                if column > 0:
                    self.editor.move_cursor_relative(columns=-1, record_width=False)
            self.editor.focus()
            self.refresh_status()

        def action_command_mode(self) -> None:
            self.mode = "command"
            self.pending_quit = False
            self.pending_normal_key = None
            self.editor.read_only = True
            self.command_line.remove_class("hidden")
            self.command_line.value = ":"
            self.command_line.focus()
            self.refresh_status()

        def action_append(self) -> None:
            self.editor.action_cursor_right()
            self.action_enter_insert()

        def action_open_below(self) -> None:
            self.editor.action_cursor_line_end()
            self.editor.insert("\n")
            self.action_enter_insert()

        def action_open_above(self) -> None:
            line_index, _column = self.editor.selection.end
            self.editor.move_cursor((line_index, 0))
            self.editor.insert("\n")
            self.editor.move_cursor((line_index, 0))
            self.action_enter_insert()

        def run_mutating_action(self, action: Callable[[], None]) -> None:
            was_read_only = self.editor.read_only
            self.editor.read_only = False
            try:
                action()
            finally:
                self.editor.read_only = was_read_only

        def handle_normal_key(self, key: str, character: str | None) -> bool:
            if key == "escape":
                self.pending_normal_key = None
                self.refresh_status()
                return True

            if self.pending_normal_key is not None:
                if self.handle_pending_normal_key(key, character):
                    self.pending_normal_key = None
                    self.refresh_status()
                    return True

                self.pending_normal_key = None
                self.refresh_status()
                return self.handle_normal_key(key, character)

            if character == ":":
                self.action_command_mode()
                return True

            if character == "h":
                self.editor.action_cursor_left()
                return True
            if character == "j":
                self.editor.action_cursor_down()
                return True
            if character == "k":
                self.editor.action_cursor_up()
                return True
            if character == "l":
                self.editor.action_cursor_right()
                return True
            if character == "w":
                self.editor.action_cursor_word_right()
                return True
            if character == "b":
                self.editor.action_cursor_word_left()
                return True
            if character == "0":
                self.editor.action_cursor_line_start()
                return True
            if character == "$":
                self.editor.action_cursor_line_end()
                return True
            if character == "g":
                self.pending_normal_key = "g"
                self.refresh_status()
                return True
            if character == "d":
                self.pending_normal_key = "d"
                self.refresh_status()
                return True
            if character == "x":
                self.run_mutating_action(self.editor.action_delete_right)
                return True
            if character == "u":
                self.action_undo()
                return True
            if character == "i":
                self.action_enter_insert()
                return True
            if character == "a":
                self.action_append()
                return True
            if character == "o":
                self.action_open_below()
                return True
            if character == "I":
                self.editor.action_cursor_line_start()
                self.action_enter_insert()
                return True
            if character == "A":
                self.editor.action_cursor_line_end()
                self.action_enter_insert()
                return True
            if character == "O":
                self.action_open_above()
                return True
            if character == "G":
                self.editor.move_cursor(self.editor.document.end, center=True)
                return True
            if character == "D":
                self.run_mutating_action(self.editor.action_delete_to_end_of_line)
                return True

            return False

        def handle_pending_normal_key(self, key: str, character: str | None) -> bool:
            pending = self.pending_normal_key
            if pending == "g":
                if character == "g":
                    self.editor.move_cursor((0, 0), center=True)
                    return True
                if character == "G":
                    self.editor.move_cursor(self.editor.document.end, center=True)
                    return True
                return False

            if pending == "d":
                if character == "d":
                    self.run_mutating_action(self.editor.action_delete_line)
                    return True
                if character == "w":
                    self.run_mutating_action(self.editor.action_delete_word_right)
                    return True
                if character == "b":
                    self.run_mutating_action(self.editor.action_delete_word_left)
                    return True
                if character == "0":
                    self.run_mutating_action(self.editor.action_delete_to_start_of_line)
                    return True
                if character in {"$", "D"}:
                    self.run_mutating_action(self.editor.action_delete_to_end_of_line)
                    return True
                return False

            return False

        def action_save(self) -> None:
            self.save_current_text(notify_if_unchanged=True)

        def save_current_text(self, *, notify_if_unchanged: bool) -> bool:
            current_text = self.editor.text
            if current_text == self.saved_text:
                if notify_if_unchanged:
                    self.notify("没有内容变化")
                return True

            try:
                outcome = save_callback(current_text)
            except Exception as error:  # noqa: BLE001
                self.notify(f"保存失败: {error}", severity="error")
                return False

            self.saved_text = self.editor.text
            self.dirty = False
            self.pending_quit = False
            self.notify(outcome.message, severity=outcome.severity)  # type: ignore[arg-type]
            self.refresh_status()
            return True

        def action_request_quit(self) -> None:
            if self.dirty and not self.pending_quit:
                self.pending_quit = True
                self.refresh_status()
                self.notify(
                    "有未保存修改，再按 Ctrl+Q 强制退出，或先保存", severity="warning"
                )
                return
            self.exit()

        def action_undo(self) -> None:
            self.editor.action_undo()

        def action_redo(self) -> None:
            self.editor.action_redo()

        def handle_command(self, raw_command: str) -> None:
            command = raw_command.strip()
            if command.startswith(":"):
                command = command[1:]

            if command in {"w", "write"}:
                self.save_current_text(notify_if_unchanged=True)
                self.action_normal_mode()
                return

            if command in {"q", "quit"}:
                if self.dirty:
                    self.notify(
                        "有未保存修改，请先 `:w` 或使用 `:q!`", severity="warning"
                    )
                    self.action_normal_mode()
                    return
                self.exit()
                return

            if command in {"q!", "quit!"}:
                self.exit()
                return

            if command in {"wq", "x"}:
                if self.save_current_text(notify_if_unchanged=False):
                    self.exit()
                return

            self.notify(f"未知命令: {raw_command}", severity="warning")
            self.action_normal_mode()

    LifeNoteEditor().run()


def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="Life Note CLI - 管理每日笔记",
        usage=(
            "lfn [笔记内容] | lfn all | lfn --week | lfn --edit | "
            "lfn all --edit | lfn [-a/--add 笔记内容] | lfn [-s/--show]"
        ),
    )
    parser.add_argument("note", nargs="*", help="要添加的笔记内容")
    parser.add_argument("-a", "--add", dest="add_note", help="添加一条笔记")
    parser.add_argument(
        "-s", "--show", action="store_true", help="只显示笔记，不添加条目"
    )
    parser.add_argument("--all", action="store_true", help="显示全部日期的笔记")
    parser.add_argument(
        "--week", action="store_true", help="用 Markdown 打印上周的全部笔记"
    )
    parser.add_argument("-e", "--edit", action="store_true", help="打开 Textual 编辑器")
    parser.add_argument("--no-update", action="store_true", help="不运行 update 脚本")

    args = parser.parse_args()

    positional_all = (
        len(args.note) == 1
        and args.note[0].lower() == "all"
        and not args.add_note
        and not args.show
    )
    invalid_edit_usage = args.edit and (
        args.add_note or args.show or (args.note and not positional_all)
    )
    if invalid_edit_usage:
        parser.error("--edit 不能和 `--add`、`--show` 或普通笔记内容一起使用")

    invalid_week_usage = args.week and (
        args.add_note or args.show or args.all or args.edit or bool(args.note)
    )
    if invalid_week_usage:
        parser.error("--week 只能单独使用")

    should_pull_first = args.edit or (
        not args.all and not positional_all and not args.show and not args.week
    )
    if should_pull_first:
        run_git_pull_or_exit()

    content = read_readme()

    if args.edit:
        now = get_utc8_now()
        if args.all or positional_all:
            launch_textual_editor(
                initial_text=content,
                title="lfn all --edit",
                subtitle=str(README_PATH),
                save_callback=build_all_save_callback(no_update=args.no_update),
                note_mode=False,
            )
        else:
            launch_textual_editor(
                initial_text=build_today_editor_text(content, now),
                title="lfn --edit",
                subtitle=f"{format_date(now)} / {README_PATH}",
                save_callback=build_today_save_callback(now, no_update=args.no_update),
                note_mode=True,
            )
        return

    if args.all or positional_all:
        sections = get_all_notes(content)
        show_all_notes(sections)
        return

    if args.week:
        now = get_utc8_now()
        start_date, end_date = get_last_week_range(now)
        sections = filter_sections_by_date_range(
            get_all_notes(content), start_date, end_date
        )
        sys.stdout.write(render_week_notes_markdown(sections, start_date, end_date))
        return

    # 获取 UTC+8 当前时间
    now = get_utc8_now()
    today_str = format_date(now)

    if args.show:
        notes = get_today_notes(content, now)
        show_today_notes(now, notes)
        return

    console.print(f"[dim]当前时间 (UTC+8): {now.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")

    # 检查今天是否已有条目
    if not check_date_exists(content, now):
        console.print(f"[yellow]未找到今天的条目，正在添加 {today_str}...[/yellow]")
        content = add_new_date(content, now)
        write_readme(content)
        console.print(f"[green]✓ 已添加 {today_str}[/green]")

        # 运行 update
        if not args.no_update:
            run_update()
    else:
        if not args.show:
            console.print(f"[dim]今天 ({today_str}) 的条目已存在[/dim]")

    # 处理添加笔记
    note_to_add = None
    if args.add_note:
        note_to_add = args.add_note
    elif args.note and not args.show:
        note_to_add = " ".join(args.note)

    if note_to_add:
        content = add_note_to_date(content, now, note_to_add)
        write_readme(content)
        console.print(f"[green]✓ 已添加笔记: {note_to_add}[/green]")

        # 运行 update
        if not args.no_update:
            run_update()

    # 获取并显示今天的笔记（重新读取以获取最新内容）
    content = read_readme()
    notes = get_today_notes(content, now)
    show_today_notes(now, notes)


if __name__ == "__main__":
    main()
