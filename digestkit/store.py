"""JSON / JSONL persistence helpers shared by every digest."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return dt.date.today().isoformat()


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:48] or hashlib.sha1(s.encode()).hexdigest()[:8]


def load_json(path: Path, default):
    if not path.exists():
        return default() if callable(default) else default
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"WARN: could not parse {path}: {e}; using default", file=sys.stderr)
        return default() if callable(default) else default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def out(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)
