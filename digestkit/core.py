"""Spec-driven state & configuration CLI shared by every digest.

`main(spec)` builds the argparse CLI for one digest (see digestkit.specs). The
verbs, flags, JSON output and on-disk layout of the papers digest are exactly
those of scripts/papers.py at 2583d84; headlines uses the same verbs with its
own ledger and defaults. New verbs for both: `items group`, `decisions check`,
`snapshot save|diff`, `sources sync-blogwatcher`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from . import items as items_mod
from . import specs as specs_mod
from .specs import DigestSpec
from .store import append_jsonl, load_json, now_iso, out, read_jsonl, save_json, slug, today
from .urls import is_url, item_key, legacy_key, match_keys, normalize_tag, record_match_keys

DELIVERY_METHODS = ("email", "discord", "both")
DECISIONS = ("main", "near-miss", "dropped")


def default_retry() -> dict:
    return {"date": None, "attempts": 0, "last_error": None, "next_attempt_after": None}


def delivery_method(cfg: dict) -> str:
    return (cfg.get("delivery") or {}).get("method") or "email"


class Ctx:
    """Paths for one digest home."""

    def __init__(self, spec: DigestSpec, home: Path):
        self.spec = spec
        self.root = home
        self.config_dir = home / "config"
        self.state_dir = home / "state"
        self.digest_dir = home / "digests"
        self.config_file = self.config_dir / "config.json"
        self.interests_file = self.config_dir / "interests.json"
        self.sources_file = self.config_dir / "sources.json"
        self.seen_file = self.state_dir / spec.ledger_file
        self.runs_file = self.state_dir / "runs.jsonl"
        self.feedback_file = self.state_dir / "feedback.jsonl"
        self.retry_file = self.state_dir / "retry_state.json"
        self.blogwatcher_db = self.state_dir / "blogwatcher.db"
        self.snapshot_dir = self.state_dir / "snapshots"

    def default_seen(self) -> dict:
        return {self.spec.ledger_key: {}}

    def ledger(self) -> dict:
        data = load_json(self.seen_file, self.default_seen)
        data.setdefault(self.spec.ledger_key, {})
        return data

    def resolve(self, p: str) -> Path:
        """A path argument: relative paths try the digest home first, then the cwd.

        (Home first: from the repo root, `digests/D.md` must mean the headlines
        file for headlines.py even when papers has a file of the same name.)"""
        path = Path(p)
        if path.is_absolute():
            return path
        alt = self.root / path
        return alt if alt.exists() else path


def peer_ctxs(ctx: Ctx) -> list[Ctx]:
    res = []
    for name in ctx.spec.peers:
        ps = specs_mod.get(name)
        home = ps.home()
        if home.resolve() == ctx.root.resolve():
            continue
        res.append(Ctx(ps, home))
    return res


# ---------------------------------------------------------------------------
# ledger matching (own + peers)
# ---------------------------------------------------------------------------
class Index:
    """match key -> (key, record), plus entity tag -> [(key, record)]."""

    def __init__(self, digest: str, records: dict):
        self.digest = digest
        self.records = records
        self.by_key: dict[str, tuple[str, dict]] = {}
        self.by_tag: dict[str, list[tuple[str, dict]]] = {}
        for k, rec in records.items():
            rec = rec if isinstance(rec, dict) else {}
            for mk in record_match_keys(k, rec):
                self.by_key.setdefault(mk, (k, rec))
            for t in rec.get("tags") or []:
                self.by_tag.setdefault(t, []).append((k, rec))

    def find(self, keys) -> tuple[str, dict] | None:
        for k in sorted(keys):
            if k in self.by_key:
                return self.by_key[k]
        return None

    def find_tags(self, tags) -> list[tuple[str, str, dict]]:
        res = []
        for t in tags:
            for k, rec in self.by_tag.get(t, []):
                res.append((t, k, rec))
        return res


def load_peer_indexes(ctx: Ctx) -> list[Index]:
    res = []
    for pc in peer_ctxs(ctx):
        if not pc.seen_file.exists():
            continue  # a missing peer ledger is not an error
        try:
            data = json.loads(pc.seen_file.read_text())
            recs = data.get(pc.spec.ledger_key) or {}
        except Exception as e:
            print(f"WARN: could not read peer ledger {pc.seen_file}: {e}", file=sys.stderr)
            continue
        res.append(Index(pc.spec.name, recs))
    return res


def own_seen(ctx: Ctx, records: dict, own_index: Index | None, raw: str, key: str):
    """(seen?, record) against this digest's own ledger."""
    if key in records:
        return True, records[key]
    if ctx.spec.own_match_index and own_index is not None:
        hit = own_index.find(match_keys(raw) | {key})
        if hit:
            return True, hit[1]
    return False, None


def peer_lookup(peers: list[Index], raw: str, key: str):
    q = match_keys(raw) | {key}
    for idx in peers:
        hit = idx.find(q)
        if hit:
            return idx.digest, hit[0], hit[1]
    return None


def _input_str(it) -> str:
    if isinstance(it, dict):
        return str(it.get("url") or it.get("id") or "")
    return str(it)


# ---------------------------------------------------------------------------
# commands: init / status
# ---------------------------------------------------------------------------
def cmd_init(ctx: Ctx, args):
    sp = ctx.spec
    created = []
    for path, default in [
        (ctx.config_file, sp.default_config),
        (ctx.interests_file, sp.default_interests),
        (ctx.sources_file, sp.default_sources),
        (ctx.seen_file, ctx.default_seen),
        (ctx.retry_file, default_retry),
    ]:
        if path.exists() and not args.force:
            continue
        save_json(path, default())
        created.append(str(path.relative_to(ctx.root)))
    for d in (ctx.digest_dir, ctx.state_dir):
        d.mkdir(parents=True, exist_ok=True)
    ctx.runs_file.touch(exist_ok=True)
    ctx.feedback_file.touch(exist_ok=True)
    out({"initialized": True, "created": created, "root": str(ctx.root), "forced": args.force})


def cmd_status(ctx: Ctx, args):
    sp = ctx.spec
    cfg = load_json(ctx.config_file, sp.default_config)
    interests = load_json(ctx.interests_file, sp.default_interests)
    sources = load_json(ctx.sources_file, sp.default_sources)["sources"]
    seen = ctx.ledger()[sp.ledger_key]
    runs = read_jsonl(ctx.runs_file)
    retry = load_json(ctx.retry_file, default_retry)
    last_success = next((r for r in reversed(runs) if r.get("status") == "success"), None)
    method = delivery_method(cfg)
    email_ok = bool(cfg.get("email", {}).get("to"))
    out(
        {
            "root": str(ctx.root),
            # discord needs nothing in config (the cron job owns the target);
            # email / both need a recipient.
            "configured": method in DELIVERY_METHODS and (method == "discord" or email_ok),
            "delivery_method": method,
            "email_to": cfg.get("email", {}).get("to", ""),
            "digest": cfg.get("digest", {}),
            "counts": {
                "topics": len(interests.get("topics", [])),
                "keywords": len(interests.get("keywords", [])),
                "sources_active": sum(1 for s in sources if s.get("active")),
                "sources_total": len(sources),
                f"seen_{sp.ledger_key}": len(seen),
                "runs": len(runs),
            },
            "last_run": runs[-1] if runs else None,
            "last_success": last_success,
            "retry_state": retry,
        }
    )


# ---------------------------------------------------------------------------
# commands: config
# ---------------------------------------------------------------------------
def _dotget(d, path):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _dotset(d, path, value):
    keys = path.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    # coerce simple types
    if isinstance(value, str):
        low = value.lower()
        if low in ("true", "false"):
            value = low == "true"
        elif re.match(r"^-?\d+$", value):
            value = int(value)
    cur[keys[-1]] = value


def cmd_config(ctx: Ctx, args):
    cfg = load_json(ctx.config_file, ctx.spec.default_config)
    if args.config_action == "show":
        out(cfg)
    elif args.config_action == "get":
        out({args.key: _dotget(cfg, args.key)})
    elif args.config_action == "set":
        if args.key == "delivery.method" and args.value not in DELIVERY_METHODS:
            print(f"ERROR: delivery.method must be one of {list(DELIVERY_METHODS)}", file=sys.stderr)
            sys.exit(2)
        _dotset(cfg, args.key, args.value)
        save_json(ctx.config_file, cfg)
        out({"set": args.key, "value": _dotget(cfg, args.key)})


# ---------------------------------------------------------------------------
# commands: interests
# ---------------------------------------------------------------------------
def cmd_interests(ctx: Ctx, args):
    fields = ctx.spec.interest_fields
    data = load_json(ctx.interests_file, ctx.spec.default_interests)
    a = args.interests_action
    if a == "show":
        out(data)
        return
    if a == "set-instructions":
        data["extra_instructions"] = args.text
        save_json(ctx.interests_file, data)
        out({"extra_instructions": data["extra_instructions"]})
        return
    field = args.field
    if field not in fields:
        print(f"ERROR: unknown field '{field}'. Choices: {sorted(fields)}", file=sys.stderr)
        sys.exit(2)
    items = data.setdefault(field, [])
    values = [v.strip() for v in args.values if v.strip()]
    if a == "add":
        for v in values:
            if v not in items:
                items.append(v)
    elif a == "remove":
        data[field] = [x for x in items if x not in values]
    save_json(ctx.interests_file, data)
    out({field: data[field]})


# ---------------------------------------------------------------------------
# commands: sources
# ---------------------------------------------------------------------------
def match_source(srcs, query):
    q = query.lower()
    for s in srcs:
        if s["id"] == query:
            return s
    for s in srcs:
        if q in s["name"].lower() or q in s["id"] or q in s.get("url", "").lower():
            return s
    return None


def _need_source(srcs, query):
    target = match_source(srcs, query)
    if not target:
        print(f"ERROR: no source matching '{query}'", file=sys.stderr)
        sys.exit(2)
    return target


def cmd_sources(ctx: Ctx, args):
    sp = ctx.spec
    data = load_json(ctx.sources_file, sp.default_sources)
    srcs = data["sources"]
    a = args.sources_action
    if a == "list":
        rows = srcs if args.all else [s for s in srcs if s.get("active")]
        out({"sources": rows})
    elif a == "add":
        sid = slug(args.name)
        existing = next((s for s in srcs if s["id"] == sid), None)
        rec = {
            "id": sid,
            "name": args.name,
            "url": args.url,
            "type": args.type,
            "feed": args.feed or "",
            "priority": args.priority,
            "usefulness": 0,
            "active": True,
            "notes": args.notes or "",
            "added": today(),
        }
        upd = ["url", "type", "feed", "priority", "notes"]
        for f in sp.source_extra_fields:
            rec[f] = getattr(args, f"src_{f}", "") or ""
            upd.append(f)
        if existing:
            existing.update({k: rec[k] for k in upd})
            existing["active"] = True
            result = existing
        else:
            srcs.append(rec)
            result = rec
        save_json(ctx.sources_file, data)
        out({"added": result})
    elif a in ("remove", "disable"):
        target = _need_source(srcs, args.query)
        if a == "remove" and args.hard:
            data["sources"] = [s for s in srcs if s["id"] != target["id"]]
        else:
            target["active"] = False
        save_json(ctx.sources_file, data)
        out({"removed": target["id"], "hard": bool(getattr(args, "hard", False))})
    elif a == "enable":
        target = _need_source(srcs, args.query)
        target["active"] = True
        save_json(ctx.sources_file, data)
        out({"enabled": target["id"]})
    elif a == "note":
        target = _need_source(srcs, args.query)
        target["notes"] = args.text
        save_json(ctx.sources_file, data)
        out({"id": target["id"], "notes": target["notes"]})
    elif a == "bump":
        target = _need_source(srcs, args.query)
        target["usefulness"] = target.get("usefulness", 0) + args.delta
        save_json(ctx.sources_file, data)
        out({"id": target["id"], "usefulness": target["usefulness"]})
    elif a == "sync-blogwatcher":
        cmd_sync_blogwatcher(ctx, args, srcs)


def _blogwatcher_tracked(bw: str, db: Path) -> set[str] | None:
    """Names, URLs and feeds already tracked in `db` (None if it can't be read)."""
    try:
        r = subprocess.run([bw, "--db", str(db), "blogs"], capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    tracked = set()
    for line in r.stdout.splitlines():
        s = line.strip()
        if not s or s.startswith("Tracked blogs"):
            continue
        m = re.match(r"^(URL|Feed):\s*(\S+)", s)
        if m:
            tracked.add(m.group(2).rstrip("/"))
        elif ":" not in s:
            tracked.add(s)
    return tracked


def cmd_sync_blogwatcher(ctx: Ctx, args, srcs):
    bw = shutil.which(args.blogwatcher)
    db = ctx.blogwatcher_db
    wanted = [s for s in srcs if s.get("active") and s.get("feed")]
    tracked = _blogwatcher_tracked(bw, db) if (bw and db.exists()) else (set() if bw else None)
    todo, already = [], []
    for s in wanted:
        if tracked is not None and (s["id"] in tracked or s["feed"].rstrip("/") in tracked):
            already.append(s["id"])
            continue
        todo.append({
            "id": s["id"],
            "command": [args.blogwatcher, "--db", str(db), "add", s["id"], s["url"], "--feed-url", s["feed"]],
        })
    res = {
        "db": str(db),
        "blogwatcher": bw or None,
        "tracked_known": tracked is not None,
        "already_tracked": already,
        "to_add": todo,
        "dry_run": bool(args.dry_run),
    }
    if args.dry_run:
        if tracked is None:
            res["note"] = "blogwatcher-cli not found: listing every feed-backed active source"
        out(res)
        return
    if not bw:
        print("ERROR: blogwatcher-cli not found on PATH (use --dry-run to print the commands)",
              file=sys.stderr)
        sys.exit(3)
    db.parent.mkdir(parents=True, exist_ok=True)
    results = []
    failed = False
    for t in todo:
        cmd = [bw] + t["command"][1:]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        results.append({"id": t["id"], "returncode": r.returncode,
                        "output": (r.stdout + r.stderr).strip()[-300:]})
        failed |= r.returncode != 0
    res["results"] = results
    out(res)
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------------------
# commands: seen (dedup)
# ---------------------------------------------------------------------------
def cmd_seen(ctx: Ctx, args):
    sp = ctx.spec
    data = ctx.ledger()
    records = data[sp.ledger_key]
    a = args.seen_action
    if a == "has":
        raw = args.item
        key = sp.key_fn(raw)
        own_idx = Index(sp.name, records) if sp.own_match_index else None
        seen, rec = own_seen(ctx, records, own_idx, raw, key)
        res = {sp.noun: raw, "key": key, "seen": seen, "record": rec}
        hit = peer_lookup(load_peer_indexes(ctx), raw, key)
        res["peer_seen"] = bool(hit)
        res["peer_digest"] = hit[0] if hit else None
        res["peer_key"] = hit[1] if hit else None
        res["peer_record"] = hit[2] if hit else None
        out(res)
    elif a == "add":
        raw = args.item
        key = sp.key_fn(raw)
        tags = sorted({normalize_tag(t) for t in (args.tag or []) if t.strip()})
        aliases = sorted({item_key(x) for x in (args.alias or []) if x.strip()} - {key})
        if args.dry_run:
            would = {
                "key": key,
                "title": args.title or "",
                "source": args.source or "",
                "run_id": args.run_id or "",
            }
            if tags:
                would["tags"] = tags
            if aliases:
                would["aliases"] = aliases
            if args.section:
                would["section"] = args.section
            out({"dry_run": True, "would_record": would})
            return
        changed = False
        if key not in records:
            rec = {
                "first_raised": today(),
                "title": args.title or "",
                "source": args.source or "",
                "run_id": args.run_id or "",
            }
            if is_url(raw):
                rec["url"] = raw.strip()
            records[key] = rec
            changed = True
        rec = records[key]
        if args.section and not rec.get("section"):
            rec["section"] = args.section
            changed = True
        for field, new in (("tags", tags), ("aliases", aliases)):
            if new:
                merged = sorted(set(rec.get(field) or []) | set(new))
                if merged != rec.get(field):
                    rec[field] = merged
                    changed = True
        if changed:
            save_json(ctx.seen_file, data)
        out({"key": key, "record": rec})
    elif a == "filter":
        # stdin: newline- or json-list of ids; prints only unseen canonical keys
        raw_in = sys.stdin.read().strip()
        if raw_in.startswith("["):
            items = json.loads(raw_in)
        else:
            items = [x for x in raw_in.splitlines() if x.strip()]
        own_idx = Index(sp.name, records) if sp.own_match_index else None
        peers = load_peer_indexes(ctx)
        unseen, peer_seen = [], []
        for it in items:
            s = _input_str(it)
            key = sp.key_fn(s)
            seen, _ = own_seen(ctx, records, own_idx, s, key)
            if seen:
                continue
            hit = peer_lookup(peers, s, key)
            if hit:
                peer_seen.append({"input": it, "key": key, "digest": hit[0],
                                  "peer_key": hit[1], "record": hit[2]})
                continue
            unseen.append({"input": it, "key": key})
        out({"unseen": unseen, "count": len(unseen), "peer_seen": peer_seen})
    elif a == "list":
        out({"count": len(records), sp.ledger_key: records})


# ---------------------------------------------------------------------------
# commands: items group
# ---------------------------------------------------------------------------
def cmd_items(ctx: Ctx, args):
    sp = ctx.spec
    raw_in = (Path(args.file).read_text() if args.file else sys.stdin.read()).strip()
    if raw_in.startswith("["):
        cands = json.loads(raw_in)
    elif raw_in.startswith("{"):
        cands = json.loads(raw_in).get("items", [])
    else:
        cands = [{"url": x.strip()} for x in raw_in.splitlines() if x.strip()]
    records = ctx.ledger()[sp.ledger_key]
    own = Index(sp.name, records)
    peers = load_peer_indexes(ctx)
    srcs = load_json(ctx.sources_file, sp.default_sources).get("sources", [])
    table = sp.domain_classes or specs_mod.get("headlines").domain_classes

    def lookup(keys, tags):
        hits, seen_pairs = [], set()
        for idx, is_own in [(own, True)] + [(p, False) for p in peers]:
            for k in sorted(keys):
                if k in idx.by_key:
                    rk, rec = idx.by_key[k]
                    if (idx.digest, rk) not in seen_pairs:
                        seen_pairs.add((idx.digest, rk))
                        hits.append({"digest": idx.digest, "key": rk, "record": rec,
                                     "via": f"key:{k}", "own": is_own})
            for t, rk, rec in idx.find_tags(tags):
                if (idx.digest, rk) not in seen_pairs:
                    seen_pairs.add((idx.digest, rk))
                    hits.append({"digest": idx.digest, "key": rk, "record": rec,
                                 "via": f"tag:{t}", "own": is_own})
        return hits

    groups = items_mod.group(cands, table, srcs, lookup)
    out({
        "input_count": len(cands),
        "count": len(groups),
        "covered_count": sum(1 for g in groups if g["covered"]),
        "groups": groups,
    })


# ---------------------------------------------------------------------------
# commands: decisions check
# ---------------------------------------------------------------------------
_LINK = re.compile(r"\[[^\]]*\]\(<?(https?://[^\s)>]+)>?\)")
_BARE_URL = re.compile(r"(?<![(<])(https?://[^\s)>\]]+)")


def digest_main_links(md: str, near_miss_headings) -> list[dict]:
    """The first link of each list entry outside near-miss/also-notable sections."""
    links, section, in_fence, skip = [], "", False, False
    for n, line in enumerate(md.splitlines(), 1):
        if line.strip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = re.match(r"^#{1,6}\s+(.*)$", line)
        if h:
            section = h.group(1).strip()
            low = section.lower().replace("’", "'")
            skip = any(x in low for x in near_miss_headings)
            continue
        if skip or not re.match(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", line):
            continue
        m = _LINK.search(line) or _BARE_URL.search(line)
        if m:
            links.append({"line": n, "section": section, "url": m.group(1)})
    return links


def cmd_decisions(ctx: Ctx, args):
    path = ctx.resolve(args.file)
    errors, entries = [], []
    if not path.exists():
        out({"ok": False, "file": str(path), "errors": [{"line": 0, "error": "file not found"}]})
        sys.exit(1)
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception as e:
            errors.append({"line": n, "error": f"invalid JSON: {e}"})
            continue
        if not isinstance(obj, dict):
            errors.append({"line": n, "error": "not a JSON object"})
            continue
        for f, typ in (("id", str), ("title", str), ("source", str), ("reason", str)):
            if f not in obj:
                errors.append({"line": n, "error": f"missing '{f}'"})
            elif not isinstance(obj[f], typ):
                errors.append({"line": n, "error": f"'{f}' must be a string"})
            elif f == "id" and not obj[f].strip():
                errors.append({"line": n, "error": "'id' is empty"})
        if "opened" not in obj:
            errors.append({"line": n, "error": "missing 'opened'"})
        elif not isinstance(obj["opened"], bool):
            errors.append({"line": n, "error": "'opened' must be true/false"})
        if obj.get("decision") not in DECISIONS:
            errors.append({"line": n, "error": f"'decision' must be one of {list(DECISIONS)}"})
        if "section" in obj and not isinstance(obj["section"], (str, type(None))):
            errors.append({"line": n, "error": "'section' must be a string"})
        if "merged_into" in obj and not isinstance(obj["merged_into"], (str, type(None))):
            errors.append({"line": n, "error": "'merged_into' must be a string or null"})
        if obj.get("merged_into") and obj.get("decision") == "main":
            errors.append({"line": n, "error": "a merged entry can't be 'main'; use 'dropped'"})
        obj["_line"] = n
        entries.append(obj)
    counts = {d: sum(1 for e in entries if e.get("decision") == d) for d in DECISIONS}
    res = {"ok": not errors, "file": str(path), "entries": len(entries), "counts": counts,
           "errors": errors}
    if args.digest_file:
        dpath = ctx.resolve(args.digest_file)
        if not dpath.exists():
            res["ok"] = False
            res["errors"].append({"line": 0, "error": f"digest file not found: {dpath}"})
        else:
            links = digest_main_links(dpath.read_text(), ctx.spec.near_miss_headings)

            def keys_of(e):
                ks = set()
                for f in ("id", "url"):
                    v = e.get(f)
                    if isinstance(v, str) and v.strip():
                        ks |= match_keys(v) | {legacy_key(v), item_key(v)}
                return ks

            main = [e for e in entries if e.get("decision") == "main"]
            all_keys = set()
            for e in entries:
                all_keys |= keys_of(e)
            main_keys = set()
            for e in main:
                main_keys |= keys_of(e)
            link_keys = []
            missing_from_log = []
            for ln in links:
                lk = match_keys(ln["url"])
                link_keys.append(lk)
                if not (lk & main_keys):
                    entry = dict(ln)
                    entry["in_log_as"] = next(
                        (e.get("decision") for e in entries if keys_of(e) & lk), None)
                    missing_from_log.append(entry)
            all_link_keys = set().union(*link_keys) if link_keys else set()
            main_missing = [{"line": e["_line"], "id": e["id"], "title": e.get("title", "")}
                            for e in main if not (keys_of(e) & all_link_keys)]
            res["digest"] = {
                "file": str(dpath),
                "main_links": len(links),
                "missing_from_log": missing_from_log,
                "main_missing_from_digest": main_missing,
            }
            if missing_from_log or main_missing:
                res["ok"] = False
    out(res)
    if not res["ok"]:
        sys.exit(1)


# ---------------------------------------------------------------------------
# commands: snapshot
# ---------------------------------------------------------------------------
def cmd_snapshot(ctx: Ctx, args):
    srcs = load_json(ctx.sources_file, ctx.spec.default_sources).get("sources", [])
    src = match_source(srcs, args.source)
    sid = src["id"] if src else slug(args.source)
    snap = ctx.snapshot_dir / f"{sid}.txt"
    new_path = ctx.resolve(args.file)
    if not new_path.exists():
        print(f"ERROR: {new_path} not found", file=sys.stderr)
        sys.exit(2)
    new = new_path.read_text()
    if args.snapshot_action == "save":
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(new)
        out({"source": sid, "saved": str(snap), "lines": len(new.splitlines())})
        return
    old = snap.read_text() if snap.exists() else ""
    old_l = [x.rstrip() for x in old.splitlines() if x.strip()]
    new_l = [x.rstrip() for x in new.splitlines() if x.strip()]
    added, removed = [], []
    for op in difflib.ndiff(old_l, new_l):
        if op.startswith("+ "):
            added.append(op[2:])
        elif op.startswith("- "):
            removed.append(op[2:])
    res = {"source": sid, "snapshot": str(snap), "has_previous": snap.exists(),
           "added": added, "removed": removed, "changed": bool(added or removed)}
    if args.save:
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(new)
        res["saved"] = True
    out(res)


# ---------------------------------------------------------------------------
# commands: feedback
# ---------------------------------------------------------------------------
def cmd_feedback(ctx: Ctx, args):
    sp = ctx.spec
    noun = sp.noun
    a = args.feedback_action
    if a == "add":
        key = sp.key_fn(args.item)
        rec = {
            "ts": now_iso(),
            noun: args.item,
            "key": key,
            "verdict": args.verdict,  # useful | not-useful
            "note": args.note or "",
        }
        append_jsonl(ctx.feedback_file, rec)
        # propagate signal to the source if provided
        if args.source:
            data = load_json(ctx.sources_file, sp.default_sources)
            tgt = match_source(data["sources"], args.source)
            if tgt:
                tgt["usefulness"] = tgt.get("usefulness", 0) + (1 if args.verdict == "useful" else -1)
                save_json(ctx.sources_file, data)
        out({"recorded": rec})
    elif a == "list":
        rows = read_jsonl(ctx.feedback_file)
        if args.verdict:
            rows = [r for r in rows if r.get("verdict") == args.verdict]
        out({"count": len(rows), "feedback": rows[-args.limit:]})
    elif a == "summary":
        rows = read_jsonl(ctx.feedback_file)
        useful = [r for r in rows if r.get("verdict") == "useful"]
        not_useful = [r for r in rows if r.get("verdict") == "not-useful"]
        out(
            {
                "total": len(rows),
                "useful": len(useful),
                "not_useful": len(not_useful),
                "recent_useful": [r.get("note") or r.get(noun) for r in useful[-10:]],
                "recent_not_useful": [r.get("note") or r.get(noun) for r in not_useful[-10:]],
            }
        )


# ---------------------------------------------------------------------------
# commands: runs + retry
# ---------------------------------------------------------------------------
def cmd_run(ctx: Ctx, args):
    sp = ctx.spec
    a = args.run_action
    if a == "start":
        if args.dry_run:
            run_id = f"dry-run-{today()}"
            out({
                "run_id": run_id,
                "date": today(),
                "attempt": 0,
                "max_attempts": 0,
                "wait_minutes": 0,
                "dry_run": True,
            })
            return
        cfg = load_json(ctx.config_file, sp.default_config)
        retry = load_json(ctx.retry_file, default_retry)
        day = today()
        if retry.get("date") != day:
            retry = {"date": day, "attempts": 0, "last_error": None, "next_attempt_after": None}
        retry["attempts"] += 1
        save_json(ctx.retry_file, retry)
        run_id = uuid.uuid4().hex[:12]
        out(
            {
                "run_id": run_id,
                "date": day,
                "attempt": retry["attempts"],
                "max_attempts": cfg.get("retry", {}).get("max_attempts", 3),
                "wait_minutes": cfg.get("retry", {}).get("wait_minutes", 20),
            }
        )
    elif a == "finish":
        rec = {
            "run_id": args.run_id,
            "date": today(),
            "ts": now_iso(),
            "status": args.status,  # success | failed
            "attempt": args.attempt,
            f"{sp.noun}s_raised": args.raised or [],
            "sections": args.sections,
            "error": args.error or "",
        }
        if args.dry_run:
            out({"dry_run": True, "would_record": rec})
            return
        append_jsonl(ctx.runs_file, rec)
        retry = load_json(ctx.retry_file, default_retry)
        if args.status == "success":
            retry = {"date": today(), "attempts": 0, "last_error": None, "next_attempt_after": None}
        else:
            retry["last_error"] = args.error or ""
            wait = int(args.wait_minutes) if args.wait_minutes else 20
            nxt = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=wait)
            retry["next_attempt_after"] = nxt.isoformat(timespec="seconds")
        save_json(ctx.retry_file, retry)
        out({"recorded": rec, "retry_state": retry})
    elif a == "log":
        rows = read_jsonl(ctx.runs_file)
        out({"count": len(rows), "runs": rows[-args.limit:]})
    elif a == "retry-state":
        out(load_json(ctx.retry_file, default_retry))
    elif a == "should-retry":
        cfg = load_json(ctx.config_file, sp.default_config)
        retry = load_json(ctx.retry_file, default_retry)
        maxa = cfg.get("retry", {}).get("max_attempts", 3)
        day = today()
        attempts = retry["attempts"] if retry.get("date") == day else 0
        out(
            {
                "date": day,
                "attempts_so_far": attempts,
                "max_attempts": maxa,
                "should_retry": attempts < maxa,
                "next_attempt_after": retry.get("next_attempt_after"),
                "wait_minutes": cfg.get("retry", {}).get("wait_minutes", 20),
            }
        )


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------
def build_parser(spec: DigestSpec) -> argparse.ArgumentParser:
    noun = spec.noun
    p = argparse.ArgumentParser(prog=spec.prog, description=spec.description,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", default=None,
                   help=f"digest home (default: ${spec.home_env}, else {spec.default_home()})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="scaffold config + state files")
    sp.add_argument("--force", action="store_true", help="overwrite existing files")
    sp.set_defaults(func=cmd_init)

    sub.add_parser("status", help="one-glance summary").set_defaults(func=cmd_status)

    # config
    c = sub.add_parser("config", help="email / digest / evaluation settings")
    cs = c.add_subparsers(dest="config_action", required=True)
    cs.add_parser("show").set_defaults(func=cmd_config)
    g = cs.add_parser("get")
    g.add_argument("key", help="dotted key, e.g. email.to")
    g.set_defaults(func=cmd_config)
    s = cs.add_parser("set")
    s.add_argument("key", help="dotted key, e.g. digest.verbosity")
    s.add_argument("value")
    s.set_defaults(func=cmd_config)

    # interests
    it = sub.add_parser("interests", help="topics, keywords, labs, ... and instructions")
    its = it.add_subparsers(dest="interests_action", required=True)
    its.add_parser("show").set_defaults(func=cmd_interests)
    for act in ("add", "remove"):
        a = its.add_parser(act)
        a.add_argument("field", help=f"one of {sorted(spec.interest_fields)}")
        a.add_argument("values", nargs="+")
        a.set_defaults(func=cmd_interests)
    si = its.add_parser("set-instructions")
    si.add_argument("text")
    si.set_defaults(func=cmd_interests)

    # sources
    so = sub.add_parser("sources", help="watch list of blogs / feeds / pages")
    sos = so.add_subparsers(dest="sources_action", required=True)
    ls = sos.add_parser("list")
    ls.add_argument("--all", action="store_true", help="include disabled")
    ls.set_defaults(func=cmd_sources)
    ad = sos.add_parser("add")
    ad.add_argument("name")
    ad.add_argument("url")
    ad.add_argument("--type", default=spec.default_source_type, choices=list(spec.source_types))
    ad.add_argument("--feed", default="")
    ad.add_argument("--priority", type=int, default=1)
    ad.add_argument("--notes", default="")
    for f in spec.source_extra_fields:
        ad.add_argument(f"--{f}", dest=f"src_{f}", default="",
                        help={"filter": "what to keep, e.g. 'AI only'",
                              "class": "primary|docs|press|other|aggregator (primary-link ranking)"}.get(f))
    ad.set_defaults(func=cmd_sources)
    for act in ("remove", "disable"):
        r = sos.add_parser(act)
        r.add_argument("query", help="id, name substring, or url")
        if act == "remove":
            r.add_argument("--hard", action="store_true", help="delete instead of disable")
        r.set_defaults(func=cmd_sources)
    en = sos.add_parser("enable", help="re-enable a disabled source")
    en.add_argument("query")
    en.set_defaults(func=cmd_sources)
    nt = sos.add_parser("note")
    nt.add_argument("query")
    nt.add_argument("text")
    nt.set_defaults(func=cmd_sources)
    bp = sos.add_parser("bump", help="adjust usefulness score")
    bp.add_argument("query")
    bp.add_argument("delta", type=int)
    bp.set_defaults(func=cmd_sources)
    sb = sos.add_parser("sync-blogwatcher",
                        help="add feed-backed active sources to this digest's blogwatcher DB")
    sb.add_argument("--dry-run", action="store_true", help="print the blogwatcher-cli adds only")
    sb.add_argument("--blogwatcher", default="blogwatcher-cli", help=argparse.SUPPRESS)
    sb.set_defaults(func=cmd_sources)

    # seen
    se = sub.add_parser("seen", help=f"dedup tracking of already-raised {noun}s (+ peer digests)")
    ses = se.add_subparsers(dest="seen_action", required=True)
    h = ses.add_parser("has")
    h.add_argument("item", metavar=noun)
    h.set_defaults(func=cmd_seen)
    a = ses.add_parser("add")
    a.add_argument("item", metavar=noun)
    a.add_argument("--title", default="")
    a.add_argument("--source", default="")
    a.add_argument("--run-id", default="")
    a.add_argument("--tag", action="append", default=[],
                   help="entity tag, repeatable: lab:openai, model:gpt-6.1, product:codex")
    a.add_argument("--alias", action="append", default=[],
                   help="extra key/URL this record also covers, e.g. arxiv:2611.05417 (repeatable)")
    a.add_argument("--section", default="", help="digest section it ran in")
    a.add_argument("--dry-run", action="store_true", help="print what would be recorded, don't write state")
    a.set_defaults(func=cmd_seen)
    ses.add_parser("filter", help="stdin ids -> only-unseen").set_defaults(func=cmd_seen)
    ses.add_parser("list").set_defaults(func=cmd_seen)

    # items
    im = sub.add_parser("items", help="group candidates that report the same story")
    ims = im.add_subparsers(dest="items_action", required=True)
    gr = ims.add_parser("group", help='stdin JSON [{"url","title","source","tags":[..]}] -> groups')
    gr.add_argument("--file", default="", help="read candidates from this file instead of stdin")
    gr.set_defaults(func=cmd_items)

    # decisions
    de = sub.add_parser("decisions", help="decision log checks")
    des = de.add_subparsers(dest="decisions_action", required=True)
    dc = des.add_parser("check", help="validate digests/D.decisions.jsonl (exit 0 ok / 1 problems)")
    dc.add_argument("file")
    dc.add_argument("--digest-file", default="", help="also cross-check main-section links in this digest")
    dc.set_defaults(func=cmd_decisions)

    # snapshot
    sn = sub.add_parser("snapshot", help="page snapshots for diffing (e.g. leaderboards)")
    sns = sn.add_subparsers(dest="snapshot_action", required=True)
    for act in ("save", "diff"):
        x = sns.add_parser(act)
        x.add_argument("source", help="source id/name")
        x.add_argument("--file", required=True, help="text of the page as fetched now")
        if act == "diff":
            x.add_argument("--save", action="store_true", help="store the new text after diffing")
        x.set_defaults(func=cmd_snapshot)

    # feedback
    fb = sub.add_parser("feedback", help=f"mark {noun}s useful / not-useful")
    fbs = fb.add_subparsers(dest="feedback_action", required=True)
    fa = fbs.add_parser("add")
    fa.add_argument("item", metavar=noun)
    fa.add_argument("verdict", choices=["useful", "not-useful"])
    fa.add_argument("--note", default="")
    fa.add_argument("--source", default="", help="source id/name to credit/penalize")
    fa.set_defaults(func=cmd_feedback)
    fl = fbs.add_parser("list")
    fl.add_argument("--verdict", choices=["useful", "not-useful"])
    fl.add_argument("--limit", type=int, default=50)
    fl.set_defaults(func=cmd_feedback)
    fbs.add_parser("summary").set_defaults(func=cmd_feedback)

    # run / retry
    rn = sub.add_parser("run", help="run history + retry state")
    rns = rn.add_subparsers(dest="run_action", required=True)
    st = rns.add_parser("start", help="allocate run_id, increment today's attempt")
    st.add_argument("--dry-run", action="store_true", help="no state mutation; returns fake run_id")
    st.set_defaults(func=cmd_run)
    fi = rns.add_parser("finish")
    fi.add_argument("run_id")
    fi.add_argument("status", choices=["success", "failed"])
    fi.add_argument("--attempt", type=int, default=1)
    flags = ["--papers"] if spec.noun == "paper" else [f"--{spec.noun}s", "--papers"]
    fi.add_argument(*flags, dest="raised", nargs="*", default=[])
    fi.add_argument("--sections", type=int, default=0)
    fi.add_argument("--error", default="")
    fi.add_argument("--wait-minutes", default="")
    fi.add_argument("--dry-run", action="store_true", help="print what would be recorded, don't write state")
    fi.set_defaults(func=cmd_run)
    lg = rns.add_parser("log")
    lg.add_argument("--limit", type=int, default=20)
    lg.set_defaults(func=cmd_run)
    rns.add_parser("retry-state").set_defaults(func=cmd_run)
    rns.add_parser("should-retry", help="can we still retry today?").set_defaults(func=cmd_run)

    return p


def main(spec: DigestSpec | str, argv=None) -> int:
    if isinstance(spec, str):
        spec = specs_mod.get(spec)
    args = build_parser(spec).parse_args(argv)
    ctx = Ctx(spec, spec.home(args.home))
    args.func(ctx, args)
    return 0
