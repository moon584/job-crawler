from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, List

from jsonschema import Draft202012Validator, exceptions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate rules/company.json against the JSON Schema and extra checks.",
    )
    parser.add_argument(
        "--rules",
        default="rules/company.json",
        help="Path to rules JSON file (default: rules/company.json).",
    )
    parser.add_argument(
        "--schema",
        default="rules/company.schema.json",
        help="Path to JSON Schema file (default: rules/company.schema.json).",
    )
    return parser.parse_args()


def load_json(path: str) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise SystemExit(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def format_path(error: exceptions.ValidationError) -> str:
    if not error.path:
        return "$"
    parts = []
    for segment in error.path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            parts.append(f".{segment}")
    return "$" + "".join(parts)


def validate_schema(rules: Any, schema: Any) -> List[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(rules), key=lambda e: (list(e.path), e.message))
    messages: List[str] = []
    for err in errors:
        messages.append(f"{format_path(err)}: {err.message}")
    return messages


def check_unique_company_ids(rules: Iterable[dict[str, Any]]) -> List[str]:
    seen: dict[str, int] = {}
    duplicates: List[str] = []
    for index, entry in enumerate(rules):
        company_id = str(entry.get("company_id") or "").strip()
        if not company_id:
            continue
        key = company_id.upper()
        if key in seen:
            duplicates.append(
                f"$[{index}].company_id duplicates entry at index {seen[key]} (value: {company_id})"
            )
        else:
            seen[key] = index
    return duplicates


def main() -> int:
    args = parse_args()
    schema = load_json(args.schema)
    rules = load_json(args.rules)
    if not isinstance(rules, list):
        raise SystemExit(f"Rules file must be a JSON array, got {type(rules).__name__}")
    errors = validate_schema(rules, schema)
    errors.extend(check_unique_company_ids(rules))
    if errors:
        print("规则校验失败:")
        for message in errors:
            print(f" - {message}")
        return 1
    print(f"✅ {args.rules} 通过校验，共 {len(rules)} 条配置。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

