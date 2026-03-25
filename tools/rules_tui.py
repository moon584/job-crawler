from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TabPane,
    TabbedContent,
    TextArea,
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def format_path(path: List[Any]) -> str:
    if not path:
        return "$"
    parts: List[str] = []
    for segment in path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            parts.append(f".{segment}")
    return "$" + "".join(parts)


class RuleEditor(ModalScreen[Dict[str, Any]]):
    class Submitted(Message):
        def __init__(self, sender: "RuleEditor", data: Dict[str, Any]) -> None:
            super().__init__()
            self.sender = sender
            self.data = data

    def __init__(self, rule: Dict[str, Any]) -> None:
        super().__init__()
        self._rule = json.loads(json.dumps(rule, ensure_ascii=False))

    def compose(self) -> ComposeResult:
        extra = self._rule.get("extra", {})
        field_map = extra.get("field_map", {})
        default_values = extra.get("default_values", {})
        with Vertical(id="editor"):
            yield Label("公司名称")
            yield Input(value=self._rule.get("company_name", ""), id="company_name")
            yield Label("List API URL")
            yield Input(value=self._rule.get("list_api", {}).get("url", ""), id="list_url")
            yield Label("Detail API URL")
            yield Input(value=self._rule.get("detail_api", {}).get("url", ""), id="detail_url")
            yield Label("默认数据库分类 ID")
            yield Input(value=str(extra.get("default_category_id") or ""), id="default_category_id")
            yield Label("字段映射 JSON")
            yield TextArea(json.dumps(field_map, ensure_ascii=False, indent=2), id="field_map", height=8)
            yield Label("缺省值 JSON")
            yield TextArea(json.dumps(default_values, ensure_ascii=False, indent=2), id="default_values", height=6)
            with Horizontal():
                yield Button("取消", variant="default", id="cancel")
                yield Button("保存", variant="primary", id="save")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id != "save":
            return
        try:
            field_map = json.loads(self.query_one("#field_map", TextArea).text or "{}")
            default_values = json.loads(self.query_one("#default_values", TextArea).text or "{}")
        except json.JSONDecodeError as exc:
            self.app.bell()
            self.app.notify(f"JSON 解析失败: {exc}", severity="error")
            return
        company_name = self.query_one("#company_name", Input).value.strip()
        list_url = self.query_one("#list_url", Input).value.strip()
        detail_url = self.query_one("#detail_url", Input).value.strip()
        default_category = self.query_one("#default_category_id", Input).value.strip()
        self._rule["company_name"] = company_name
        self._rule.setdefault("list_api", {})["url"] = list_url
        self._rule.setdefault("detail_api", {})["url"] = detail_url
        self._rule.setdefault("extra", {})["default_category_id"] = default_category or None
        self._rule["extra"]["field_map"] = field_map
        self._rule["extra"]["default_values"] = default_values
        self.dismiss(self._rule)


class RulesApp(App):
    CSS = """
    #sidebar {
        width: 32%;
        height: 100%;
    }
    #details {
        width: 68%;
        height: 100%;
        padding: 1;
    }
    #status {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("e", "edit_rule", "编辑"),
        Binding("s", "save_rules", "保存"),
        Binding("r", "reload_rules", "重载"),
    ]

    def __init__(self, rules_path: Path, schema_path: Path) -> None:
        super().__init__()
        self.rules_path = rules_path
        self.schema_path = schema_path
        self.rules: List[Dict[str, Any]] = []
        self.validator: Optional[Draft202012Validator] = None
        self.entry_errors: Dict[int, List[str]] = defaultdict(list)
        self.global_errors: List[str] = []
        self.selected_index: Optional[int] = None
        self.dirty: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()
        with Horizontal():
            self.list_view = ListView(id="sidebar")
            yield self.list_view
            with Vertical(id="details"):
                self.status = Static(id="status")
                yield self.status
                self.tabs = TabbedContent("概览", "字段映射", "请求预览", "校验")
                with self.tabs:
                    yield Static(id="overview")
                    yield Static(id="field_map")
                    yield Static(id="preview")
                    yield Static(id="validation")
                yield self.tabs

    def on_mount(self) -> None:
        self._load_schema()
        self._load_rules()
        self.refresh_sidebar()
        self.update_status()

    def _load_schema(self) -> None:
        schema = load_json(self.schema_path)
        self.validator = Draft202012Validator(schema)

    def _load_rules(self) -> None:
        self.rules = load_json(self.rules_path)
        self._run_validation()

    def _run_validation(self) -> None:
        self.entry_errors = defaultdict(list)
        self.global_errors = []
        if not self.validator:
            return
        for error in self.validator.iter_errors(self.rules):
            path = list(error.path)
            if path and isinstance(path[0], int):
                self.entry_errors[path[0]].append(f"{format_path(path)}: {error.message}")
            else:
                self.global_errors.append(f"{format_path(path)}: {error.message}")
        seen: Dict[str, int] = {}
        for idx, rule in enumerate(self.rules):
            company_id = str(rule.get("company_id") or "").strip().upper()
            if not company_id:
                continue
            if company_id in seen:
                self.entry_errors[idx].append(
                    f"$[{idx}].company_id duplicates entry at index {seen[company_id]}"
                )
            else:
                seen[company_id] = idx

    def refresh_sidebar(self) -> None:
        self.list_view.clear()
        for idx, rule in enumerate(self.rules):
            company_id = rule.get("company_id", "<未设置>")
            name = rule.get("company_name", "")
            marker = " ⚠" if self.entry_errors.get(idx) else ""
            label = f"{company_id} {name}{marker}"
            self.list_view.append(ListItem(Label(label), id=str(idx)))
        if self.rules:
            self.list_view.index = 0
            self.selected_index = 0
            self.update_detail()

    def update_status(self) -> None:
        if self.global_errors:
            text = "全局校验错误:\n" + "\n".join(self.global_errors)
        else:
            text = f"共 {len(self.rules)} 条规则，最近修改:{'已修改' if self.dirty else '已保存'}"
        self.status.update(text)

    def update_detail(self) -> None:
        if self.selected_index is None:
            return
        rule = self.rules[self.selected_index]
        overview = [
            f"公司: {rule.get('company_name', '-')}",
            f"Provider: {rule.get('provider', '-')}",
            f"List URL: {rule.get('list_api', {}).get('url', '-')}",
            f"Detail URL: {rule.get('detail_api', {}).get('url', '-')}",
            f"默认分类: {rule.get('extra', {}).get('default_category_id', '-')}",
        ]
        self.tabs.query_one("#overview", Static).update("\n".join(overview))
        field_map = rule.get("extra", {}).get("field_map", {})
        self.tabs.query_one("#field_map", Static).update(json.dumps(field_map, ensure_ascii=False, indent=2))
        self.tabs.query_one("#preview", Static).update(self._build_preview(rule))
        errors = self.entry_errors.get(self.selected_index)
        if errors:
            text = "校验错误:\n" + "\n".join(errors)
        else:
            text = "当前规则通过校验。"
        self.tabs.query_one("#validation", Static).update(text)

    def _build_preview(self, rule: Dict[str, Any]) -> str:
        list_api = rule.get("list_api", {})
        detail_api = rule.get("detail_api", {})
        list_url = list_api.get("url", "")
        params = list_api.get("default_params") or {}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        list_preview = f"{list_url}?{query}" if query else list_url
        detail_url = detail_api.get("url", "")
        detail_params = detail_api.get("default_params") or {}
        detail_query = "&".join(f"{k}={v}" for k, v in detail_params.items())
        detail_preview = f"{detail_url}?{detail_query}" if detail_query else detail_url
        posts_path = rule.get("extra", {}).get("list", {}).get("posts_path", "Data.Posts")
        detail_path = rule.get("extra", {}).get("detail", {}).get("data_path", "Data")
        return (
            f"列表请求: {list_preview or '-'}\n"
            f"详情请求: {detail_preview or '-'}\n"
            f"列表数据路径: {posts_path}\n详情数据路径: {detail_path}"
        )

    async def action_edit_rule(self) -> None:
        if self.selected_index is None:
            self.notify("请先选择一条规则", severity="warning")
            return
        rule = self.rules[self.selected_index]
        await self.push_screen(RuleEditor(rule), self._after_edit)

    def _after_edit(self, updated: Optional[Dict[str, Any]]) -> None:
        if updated is None or self.selected_index is None:
            return
        self.rules[self.selected_index] = updated
        self.dirty = True
        self._run_validation()
        self.refresh_sidebar()
        self.update_status()

    def action_save_rules(self) -> None:
        self.rules_path.write_text(json.dumps(self.rules, ensure_ascii=False, indent=2), encoding="utf-8")
        self.dirty = False
        self._run_validation()
        self.refresh_sidebar()
        self.update_status()
        self.notify("规则已保存", severity="information")

    def action_reload_rules(self) -> None:
        self._load_rules()
        self.dirty = False
        self.refresh_sidebar()
        self.update_status()
        self.notify("已重新加载规则", severity="information")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        try:
            self.selected_index = int(event.item.id or 0)
        except (TypeError, ValueError):
            self.selected_index = None
        self.update_detail()

    async def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            self.list_view.action_cursor_up()
        elif event.key == "down":
            self.list_view.action_cursor_down()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactively edit and validate rules/company.json")
    parser.add_argument("--rules", default="rules/company.json", help="规则文件路径")
    parser.add_argument("--schema", default="rules/company.schema.json", help="Schema 文件路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = RulesApp(Path(args.rules), Path(args.schema))
    app.run()


if __name__ == "__main__":
    main()

