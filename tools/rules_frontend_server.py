from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List

from flask import Flask, jsonify, request, send_from_directory
from jsonschema import Draft202012Validator

BASE_DIR = Path(__file__).resolve().parents[1]
RULES_PATH = BASE_DIR / "rules" / "company.json"
SCHEMA_PATH = BASE_DIR / "rules" / "company.schema.json"
FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="/static")
validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def load_rules() -> List[dict[str, Any]]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def save_rules(data: List[dict[str, Any]]) -> None:
    RULES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check_duplicates(rules: List[dict[str, Any]]) -> List[str]:
    seen: dict[str, int] = {}
    errors: List[str] = []
    for idx, entry in enumerate(rules):
        company_id = str(entry.get("company_id") or "").strip().upper()
        if not company_id:
            continue
        if company_id in seen:
            errors.append(
                f"索引 {idx} 的 company_id 与索引 {seen[company_id]} 重复: {company_id}"
            )
        else:
            seen[company_id] = idx
    return errors


@app.get("/")
def index() -> Any:
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/api/rules")
def api_rules() -> Any:
    return jsonify(load_rules())


@app.get("/api/schema")
def api_schema() -> Any:
    return jsonify(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


@app.post("/api/rules")
def api_save_rules() -> Any:
    try:
        payload = request.get_json(force=True)
    except Exception as exc:  # pragma: no cover - flask handles parse errors
        return jsonify({"success": False, "errors": [f"请求体解析失败: {exc}"]}), 400
    if not isinstance(payload, list):
        return jsonify({"success": False, "errors": ["请求体必须是规则数组"]}), 400
    schema_errors = [f"{list(err.path)}: {err.message}" for err in validator.iter_errors(payload)]
    schema_errors.extend(check_duplicates(payload))
    if schema_errors:
        return jsonify({"success": False, "errors": schema_errors}), 400
    save_rules(payload)
    return jsonify({"success": True})


@app.get("/static/<path:filename>")
def static_files(filename: str) -> Any:
    return send_from_directory(FRONTEND_DIR, filename)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="规则前端编辑服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听 IP，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument("--debug", action="store_true", help="开启 Flask 调试模式")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

