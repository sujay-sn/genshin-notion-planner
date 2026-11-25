#!/usr/bin/env python3
"""Summarize HoYoLAB API calls from a browser HAR export.

Groups requests by endpoint, hides credentials and personal identifiers,
and prints the shape of each JSON response so endpoints can be studied
and shared without exposing account data.

Usage:
    python tools/har_summary.py capture.har
    python tools/har_summary.py capture.har --out docs/endpoints.md
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

HOST_HINTS = ("hoyolab", "hoyoverse", "mihoyo")
MAX_DEPTH = 8
MAX_KEYS = 40
MAX_STR = 60

ID_KEY = re.compile(r"(^|_)(uid|ltuid|ltmid|role_id|account_id|aid|mid)(_v2)?$")
SECRET_PARTS = (
    "token",
    "cookie",
    "authkey",
    "ticket",
    "session",
    "nickname",
    "email",
    "phone",
    "device",
)
LONG_DIGITS = re.compile(r"\d{7,}")
SECRET_HEADERS = {
    "authorization",
    "ds",
    "x-rpc-device_id",
    "x-rpc-device_fp",
    "x-rpc-device_name",
}


@dataclass
class Endpoint:
    method: str
    host: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    count: int = 0
    statuses: set[int] = field(default_factory=set)
    query: dict[str, str] = field(default_factory=dict)
    request_shape: Any = None
    response_shape: Any = None


def is_sensitive(key: str) -> bool:
    k = key.lower()
    compact = k.replace("_", "").replace("-", "")
    return bool(ID_KEY.search(k)) or any(part in compact for part in SECRET_PARTS)


def strip_query(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def clean_path(path: str) -> str:
    return re.sub(r"/\d{7,}(?=/|$)", "/<id>", path)


def hide_param(key: str, value: str) -> str:
    if is_sensitive(key) or LONG_DIGITS.fullmatch(value):
        return "<hidden>"
    return value


def describe_leaf(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return f"bool = {value}"
    text = str(value)
    if isinstance(value, (int, float)):
        if LONG_DIGITS.fullmatch(text):
            return f"int ({len(text)} digits, hidden)"
        return f"{type(value).__name__} = {text}"
    if LONG_DIGITS.fullmatch(text):
        return f"str ({len(text)} digits, hidden)"
    if "@" in text:
        return "str (hidden)"
    if text.startswith(("http://", "https://")):
        return f"url = {strip_query(text)}"
    if len(text) > MAX_STR:
        return f"str (len {len(text)})"
    return f"str = {text!r}"


def shape(value: Any, key: str = "", depth: int = 0) -> Any:
    """Describe JSON structure with one sample per list and hidden secrets."""
    if key and is_sensitive(key):
        return "<hidden>"
    if depth >= MAX_DEPTH:
        return "..."
    if isinstance(value, dict):
        items = list(value.items())
        out: dict[str, Any] = {}
        for k, v in items[:MAX_KEYS]:
            label = "<id>" if LONG_DIGITS.fullmatch(k) else k
            out[label] = shape(v, k, depth + 1)
        if len(items) > MAX_KEYS:
            out["..."] = f"{len(items) - MAX_KEYS} more keys"
        return out
    if isinstance(value, list):
        if not value:
            return []
        return [f"{len(value)} items, first:", shape(value[0], key, depth + 1)]
    return describe_leaf(value)


def load_json(text: str | None, encoding: str | None = None) -> Any | None:
    if not text:
        return None
    if encoding == "base64":
        text = base64.b64decode(text).decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return None


def summarize_headers(headers: list[dict[str, str]]) -> dict[str, str]:
    """Keep headers needed to replay a call; cookies are reduced to their names."""
    out: dict[str, str] = {}
    for header in headers:
        name = header.get("name", "").lower()
        value = header.get("value", "")
        if name == "cookie":
            names = {p.split("=", 1)[0].strip() for p in value.split(";") if p.strip()}
            out[name] = "names only: " + ", ".join(sorted(names))
        elif name in SECRET_HEADERS:
            out[name] = "<hidden>"
        elif name.startswith("x-rpc-") or name == "content-type":
            out[name] = value
        elif name in ("origin", "referer"):
            out[name] = strip_query(value)
    return out


def is_api_call(entry: dict[str, Any], hints: tuple[str, ...]) -> bool:
    request = entry.get("request", {})
    if request.get("method") == "OPTIONS":
        return False
    host = urlsplit(request.get("url", "")).netloc.lower()
    if not any(hint in host for hint in hints):
        return False
    kind = entry.get("_resourceType")
    if kind:
        return kind in ("xhr", "fetch")
    mime = entry.get("response", {}).get("content", {}).get("mimeType", "")
    return "json" in mime


def collect(entries: list[dict[str, Any]], hints: tuple[str, ...]) -> tuple[list[Endpoint], int]:
    endpoints: dict[tuple[str, str, str], Endpoint] = {}
    total = 0
    for entry in entries:
        if not is_api_call(entry, hints):
            continue
        total += 1
        request = entry["request"]
        parts = urlsplit(request["url"])
        key = (request["method"], parts.netloc, clean_path(parts.path))

        ep = endpoints.get(key)
        if ep is None:
            ep = Endpoint(*key, headers=summarize_headers(request.get("headers", [])))
            endpoints[key] = ep

        ep.count += 1
        ep.statuses.add(entry.get("response", {}).get("status", 0))
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            ep.query.setdefault(k, hide_param(k, v))

        if ep.request_shape is None:
            data = load_json(request.get("postData", {}).get("text"))
            if data is not None:
                ep.request_shape = shape(data)

        if ep.response_shape is None:
            content = entry.get("response", {}).get("content", {})
            data = load_json(content.get("text"), content.get("encoding"))
            if data is not None:
                ep.response_shape = shape(data)

    ordered = sorted(endpoints.values(), key=lambda e: (e.host, e.path, e.method))
    return ordered, total


def render(endpoints: list[Endpoint], total: int) -> str:
    lines = [
        "# HoYoLAB endpoints",
        "",
        f"{total} matching requests, {len(endpoints)} unique endpoints.",
        "",
    ]
    for ep in endpoints:
        lines += [f"## {ep.method} {ep.host}{ep.path}", ""]
        statuses = ", ".join(str(s) for s in sorted(ep.statuses))
        lines.append(f"- calls: {ep.count}, status: {statuses}")
        if ep.query:
            params = ", ".join(f"{k}={v}" for k, v in sorted(ep.query.items()))
            lines.append(f"- query: {params}")
        if ep.headers:
            headers = ", ".join(f"{k}: {v}" for k, v in sorted(ep.headers.items()))
            lines.append(f"- headers: {headers}")
        for label, data in (("Request body", ep.request_shape), ("Response", ep.response_shape)):
            if data is not None:
                body = json.dumps(data, indent=2, ensure_ascii=False)
                lines += ["", f"{label}:", "```json", body, "```"]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize HoYoLAB API calls from a HAR file.")
    parser.add_argument("har", type=Path, help="HAR file exported from browser DevTools")
    parser.add_argument("--out", type=Path, help="write the summary here instead of stdout")
    parser.add_argument(
        "--host",
        action="append",
        dest="hosts",
        help="host substring to keep (repeatable, default: hoyolab/hoyoverse/mihoyo)",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    har = json.loads(args.har.read_text(encoding="utf-8-sig"))
    entries = har.get("log", {}).get("entries", [])
    hints = tuple(args.hosts) if args.hosts else HOST_HINTS
    endpoints, total = collect(entries, hints)
    report = render(endpoints, total)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote {len(endpoints)} endpoints to {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
