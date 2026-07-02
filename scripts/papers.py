#!/usr/bin/env python3
"""The Morning Papers — state & configuration manager.

Deterministic backbone for the `the-morning-papers` Hermes skill. Every mutation
the agent or user makes to interests, sources, feedback, dedup tracking, run
history, retry state, and email/digest settings goes through this CLI so the
skill never hand-edits JSON.

Stdlib only. Data lives under the repo (DATA_DIR) so it is version-controlled
and private. Override the root with MORNING_PAPERS_HOME.

Run `papers.py --help` or `papers.py <group> --help` for usage.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("MORNING_PAPERS_HOME", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
DIGEST_DIR = ROOT / "digests"

CONFIG_FILE = CONFIG_DIR / "config.json"
INTERESTS_FILE = CONFIG_DIR / "interests.json"
SOURCES_FILE = CONFIG_DIR / "sources.json"
SEEN_FILE = STATE_DIR / "seen_papers.json"
RUNS_FILE = STATE_DIR / "runs.jsonl"
FEEDBACK_FILE = STATE_DIR / "feedback.jsonl"
RETRY_FILE = STATE_DIR / "retry_state.json"

NOW = lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
TODAY = lambda: dt.date.today().isoformat()


# ---------------------------------------------------------------------------
# defaults / seed data
# ---------------------------------------------------------------------------
def default_config() -> dict:
    return {
        "email": {
            "to": "",
            "from": "",
            "subject_template": "The Morning Papers — {date}",
            "style_instructions": (
                "TL;DR style. Lead with a one-line takeaway per paper, then 1-2 "
                "sentences on why it matters and what is novel. Group into clearly "
                "titled sections. Keep it skimmable; link every paper."
            ),
            "transport": "auto",  # auto | himalaya | smtp
        },
        "smtp": {
            "host": "",
            "port": 587,
            "username": "",
            "use_tls": True,
            "password_env": "MORNING_PAPERS_SMTP_PASSWORD",
        },
        "digest": {
            "target_sections": 5,
            "target_paper_count": 12,
            "verbosity": "medium",  # terse | medium | detailed
        },
        "evaluation": {
            "novelty_criteria": (
                "Prefer genuinely new ideas: new problem framings, architectures, "
                "training objectives, theoretical results, or surprising empirical "
                "findings. Down-rank minor tweaks to training protocols, incremental "
                "benchmark bumps, routine scaling reports, and dataset/leaderboard "
                "papers with no new idea."
            ),
            "usefulness_criteria": (
                "A paper is useful if it changes how the reader would think or build: "
                "actionable methods, strong evidence, or ideas that transfer."
            ),
            "organization": (
                "Cluster by theme, not by source. Put the most novel/important items "
                "first within each section."
            ),
        },
        "schedule": {"time": "10:00", "tz": "America/New_York"},
        "retry": {"max_attempts": 3, "wait_minutes": 20},
    }


def default_interests() -> dict:
    return {
        "topics": [],
        "keywords": [],
        "authors_prioritize": [],
        "authors_exclude": [],
        "labs_prioritize": [],
        "labs_exclude": [],
        "extra_instructions": "",
    }


# Seed sources: big-lab blogs + trending feeds. `feed` left blank means the
# agent should auto-discover it (blogwatcher / RSS) at run time.
SEED_SOURCES = [
    ("Hugging Face Papers", "https://huggingface.co/papers", "trending", ""),
    ("arXiv cs.LG (new)", "https://arxiv.org/list/cs.LG/recent", "arxiv", ""),
    ("arXiv cs.CL (new)", "https://arxiv.org/list/cs.CL/recent", "arxiv", ""),
    ("arXiv cs.AI (new)", "https://arxiv.org/list/cs.AI/recent", "arxiv", ""),
    ("OpenAI Blog", "https://openai.com/news/", "blog", ""),
    ("Anthropic Research", "https://www.anthropic.com/research", "blog", ""),
    ("Google DeepMind Blog", "https://deepmind.google/discover/blog/", "blog", ""),
    ("Google Research Blog", "https://research.google/blog/", "blog", ""),
    ("Meta AI Blog", "https://ai.meta.com/blog/", "blog", ""),
    ("Microsoft Research Blog", "https://www.microsoft.com/en-us/research/blog/", "blog", ""),
    ("BAIR Blog", "https://bair.berkeley.edu/blog/", "blog", "https://bair.berkeley.edu/blog/feed.xml"),
    ("Stanford AI Lab (SAIL)", "https://ai.stanford.edu/blog/", "blog", ""),
    ("Mistral AI News", "https://mistral.ai/news/", "blog", ""),
    ("Cohere Blog", "https://cohere.com/blog", "blog", ""),
    ("AI2 (Allen Institute) Blog", "https://allenai.org/blog", "blog", ""),
    ("Sebastian Raschka (Ahead of AI)", "https://magazine.sebastianraschka.com/", "blog", ""),
    ("Lilian Weng (Lil'Log)", "https://lilianweng.github.io/", "blog", "https://lilianweng.github.io/index.xml"),
]


def default_sources() -> dict:
    srcs = []
    for name, url, typ, feed in SEED_SOURCES:
        srcs.append(
            {
                "id": _slug(name),
                "name": name,
                "url": url,
                "type": typ,  # blog | arxiv | trending | other
                "feed": feed,
                "priority": 1,
                "usefulness": 0,  # net signal from run outcomes / feedback
                "active": True,
                "notes": "",
                "added": TODAY(),
            }
        )
    return {"sources": srcs}


def default_seen() -> dict:
    return {"papers": {}}


def default_retry() -> dict:
    return {"date": None, "attempts": 0, "last_error": None, "next_attempt_after": None}


# ---------------------------------------------------------------------------
# io helpers
# ---------------------------------------------------------------------------
def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:48] or hashlib.sha1(s.encode()).hexdigest()[:8]


def _load(path: Path, default):
    if not path.exists():
        return default() if callable(default) else default
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"WARN: could not parse {path}: {e}; using default", file=sys.stderr)
        return default() if callable(default) else default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list:
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


def _out(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _canonical_paper_id(raw: str) -> str:
    """Normalize a paper identifier for dedup.

    Accepts arxiv ids/urls, hf paper urls, or arbitrary urls. Returns a stable
    key like 'arxiv:2401.01234' or 'url:<sha1>'.
    """
    s = raw.strip()
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5})", s)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.match(r"^([0-9]{4}\.[0-9]{4,5})(v\d+)?$", s)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.match(r"^arxiv:([0-9]{4}\.[0-9]{4,5})", s, re.I)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.search(r"huggingface\.co/papers/([0-9]{4}\.[0-9]{4,5})", s)
    if m:
        return f"arxiv:{m.group(1)}"
    if s.startswith("http"):
        return "url:" + hashlib.sha1(s.encode()).hexdigest()[:16]
    return "id:" + _slug(s)


# ---------------------------------------------------------------------------
# commands: init / status
# ---------------------------------------------------------------------------
def cmd_init(args):
    created = []
    for path, default in [
        (CONFIG_FILE, default_config),
        (INTERESTS_FILE, default_interests),
        (SOURCES_FILE, default_sources),
        (SEEN_FILE, default_seen),
        (RETRY_FILE, default_retry),
    ]:
        if path.exists() and not args.force:
            continue
        _save(path, default())
        created.append(str(path.relative_to(ROOT)))
    for d in (DIGEST_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    RUNS_FILE.touch(exist_ok=True)
    FEEDBACK_FILE.touch(exist_ok=True)
    _out({"initialized": True, "created": created, "root": str(ROOT), "forced": args.force})


def cmd_status(args):
    cfg = _load(CONFIG_FILE, default_config)
    interests = _load(INTERESTS_FILE, default_interests)
    sources = _load(SOURCES_FILE, default_sources)["sources"]
    seen = _load(SEEN_FILE, default_seen)["papers"]
    runs = _read_jsonl(RUNS_FILE)
    retry = _load(RETRY_FILE, default_retry)
    last_success = next((r for r in reversed(runs) if r.get("status") == "success"), None)
    _out(
        {
            "root": str(ROOT),
            "configured": bool(cfg.get("email", {}).get("to")),
            "email_to": cfg.get("email", {}).get("to", ""),
            "digest": cfg.get("digest", {}),
            "counts": {
                "topics": len(interests.get("topics", [])),
                "keywords": len(interests.get("keywords", [])),
                "sources_active": sum(1 for s in sources if s.get("active")),
                "sources_total": len(sources),
                "seen_papers": len(seen),
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


def cmd_config(args):
    cfg = _load(CONFIG_FILE, default_config)
    if args.config_action == "show":
        _out(cfg)
    elif args.config_action == "get":
        _out({args.key: _dotget(cfg, args.key)})
    elif args.config_action == "set":
        _dotset(cfg, args.key, args.value)
        _save(CONFIG_FILE, cfg)
        _out({"set": args.key, "value": _dotget(cfg, args.key)})


# ---------------------------------------------------------------------------
# commands: interests
# ---------------------------------------------------------------------------
LIST_FIELDS = {
    "topics",
    "keywords",
    "authors_prioritize",
    "authors_exclude",
    "labs_prioritize",
    "labs_exclude",
}


def cmd_interests(args):
    data = _load(INTERESTS_FILE, default_interests)
    a = args.interests_action
    if a == "show":
        _out(data)
        return
    if a == "set-instructions":
        data["extra_instructions"] = args.text
        _save(INTERESTS_FILE, data)
        _out({"extra_instructions": data["extra_instructions"]})
        return
    field = args.field
    if field not in LIST_FIELDS:
        print(f"ERROR: unknown field '{field}'. Choices: {sorted(LIST_FIELDS)}", file=sys.stderr)
        sys.exit(2)
    items = data.setdefault(field, [])
    values = [v.strip() for v in args.values if v.strip()]
    if a == "add":
        for v in values:
            if v not in items:
                items.append(v)
    elif a == "remove":
        data[field] = [x for x in items if x not in values]
    _save(INTERESTS_FILE, data)
    _out({field: data[field]})


# ---------------------------------------------------------------------------
# commands: sources
# ---------------------------------------------------------------------------
def cmd_sources(args):
    data = _load(SOURCES_FILE, default_sources)
    srcs = data["sources"]
    a = args.sources_action
    if a == "list":
        rows = srcs if args.all else [s for s in srcs if s.get("active")]
        _out({"sources": rows})
    elif a == "add":
        sid = _slug(args.name)
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
            "added": TODAY(),
        }
        if existing:
            existing.update({k: rec[k] for k in ("url", "type", "feed", "priority", "notes")})
            existing["active"] = True
            result = existing
        else:
            srcs.append(rec)
            result = rec
        _save(SOURCES_FILE, data)
        _out({"added": result})
    elif a in ("remove", "disable"):
        target = _match_source(srcs, args.query)
        if not target:
            print(f"ERROR: no source matching '{args.query}'", file=sys.stderr)
            sys.exit(2)
        if a == "remove" and args.hard:
            data["sources"] = [s for s in srcs if s["id"] != target["id"]]
        else:
            target["active"] = False
        _save(SOURCES_FILE, data)
        _out({"removed": target["id"], "hard": bool(getattr(args, "hard", False))})
    elif a == "note":
        target = _match_source(srcs, args.query)
        if not target:
            print(f"ERROR: no source matching '{args.query}'", file=sys.stderr)
            sys.exit(2)
        target["notes"] = args.text
        _save(SOURCES_FILE, data)
        _out({"id": target["id"], "notes": target["notes"]})
    elif a == "bump":
        target = _match_source(srcs, args.query)
        if not target:
            print(f"ERROR: no source matching '{args.query}'", file=sys.stderr)
            sys.exit(2)
        target["usefulness"] = target.get("usefulness", 0) + args.delta
        _save(SOURCES_FILE, data)
        _out({"id": target["id"], "usefulness": target["usefulness"]})


def _match_source(srcs, query):
    q = query.lower()
    for s in srcs:
        if s["id"] == query:
            return s
    for s in srcs:
        if q in s["name"].lower() or q in s["id"] or q in s.get("url", "").lower():
            return s
    return None


# ---------------------------------------------------------------------------
# commands: seen (dedup)
# ---------------------------------------------------------------------------
def cmd_seen(args):
    data = _load(SEEN_FILE, default_seen)
    papers = data["papers"]
    a = args.seen_action
    if a == "has":
        key = _canonical_paper_id(args.paper)
        _out({"paper": args.paper, "key": key, "seen": key in papers,
              "record": papers.get(key)})
    elif a == "add":
        key = _canonical_paper_id(args.paper)
        if getattr(args, "dry_run", False):
            _out({
                "dry_run": True,
                "would_record": {
                    "key": key,
                    "title": args.title or "",
                    "source": args.source or "",
                    "run_id": args.run_id or "",
                },
            })
            return
        if key not in papers:
            papers[key] = {
                "first_raised": TODAY(),
                "title": args.title or "",
                "source": args.source or "",
                "run_id": args.run_id or "",
            }
            _save(SEEN_FILE, data)
        _out({"key": key, "record": papers[key]})
    elif a == "filter":
        # stdin: newline- or json-list of ids; prints only unseen canonical keys
        raw = sys.stdin.read().strip()
        if raw.startswith("["):
            items = json.loads(raw)
        else:
            items = [x for x in raw.splitlines() if x.strip()]
        unseen = []
        for it in items:
            key = _canonical_paper_id(it)
            if key not in papers:
                unseen.append({"input": it, "key": key})
        _out({"unseen": unseen, "count": len(unseen)})
    elif a == "list":
        _out({"count": len(papers), "papers": papers})


# ---------------------------------------------------------------------------
# commands: feedback
# ---------------------------------------------------------------------------
def cmd_feedback(args):
    a = args.feedback_action
    if a == "add":
        key = _canonical_paper_id(args.paper)
        rec = {
            "ts": NOW(),
            "paper": args.paper,
            "key": key,
            "verdict": args.verdict,  # useful | not-useful
            "note": args.note or "",
        }
        _append_jsonl(FEEDBACK_FILE, rec)
        # propagate signal to the source if provided
        if args.source:
            data = _load(SOURCES_FILE, default_sources)
            tgt = _match_source(data["sources"], args.source)
            if tgt:
                tgt["usefulness"] = tgt.get("usefulness", 0) + (1 if args.verdict == "useful" else -1)
                _save(SOURCES_FILE, data)
        _out({"recorded": rec})
    elif a == "list":
        rows = _read_jsonl(FEEDBACK_FILE)
        if args.verdict:
            rows = [r for r in rows if r.get("verdict") == args.verdict]
        _out({"count": len(rows), "feedback": rows[-args.limit:]})
    elif a == "summary":
        rows = _read_jsonl(FEEDBACK_FILE)
        useful = [r for r in rows if r.get("verdict") == "useful"]
        not_useful = [r for r in rows if r.get("verdict") == "not-useful"]
        _out(
            {
                "total": len(rows),
                "useful": len(useful),
                "not_useful": len(not_useful),
                "recent_useful": [r.get("note") or r.get("paper") for r in useful[-10:]],
                "recent_not_useful": [r.get("note") or r.get("paper") for r in not_useful[-10:]],
            }
        )


# ---------------------------------------------------------------------------
# commands: runs + retry
# ---------------------------------------------------------------------------
def cmd_run(args):
    a = args.run_action
    if a == "start":
        if getattr(args, "dry_run", False):
            run_id = f"dry-run-{TODAY()}"
            _out({
                "run_id": run_id,
                "date": TODAY(),
                "attempt": 0,
                "max_attempts": 0,
                "wait_minutes": 0,
                "dry_run": True,
            })
            return
        cfg = _load(CONFIG_FILE, default_config)
        retry = _load(RETRY_FILE, default_retry)
        today = TODAY()
        if retry.get("date") != today:
            retry = {"date": today, "attempts": 0, "last_error": None, "next_attempt_after": None}
        retry["attempts"] += 1
        _save(RETRY_FILE, retry)
        run_id = uuid.uuid4().hex[:12]
        _out(
            {
                "run_id": run_id,
                "date": today,
                "attempt": retry["attempts"],
                "max_attempts": cfg.get("retry", {}).get("max_attempts", 3),
                "wait_minutes": cfg.get("retry", {}).get("wait_minutes", 20),
            }
        )
    elif a == "finish":
        rec = {
            "run_id": args.run_id,
            "date": TODAY(),
            "ts": NOW(),
            "status": args.status,  # success | failed
            "attempt": args.attempt,
            "papers_raised": args.papers or [],
            "sections": args.sections,
            "error": args.error or "",
        }
        if getattr(args, "dry_run", False):
            _out({"dry_run": True, "would_record": rec})
            return
        _append_jsonl(RUNS_FILE, rec)
        retry = _load(RETRY_FILE, default_retry)
        if args.status == "success":
            retry = {"date": TODAY(), "attempts": 0, "last_error": None, "next_attempt_after": None}
        else:
            retry["last_error"] = args.error or ""
            wait = int(args.wait_minutes) if args.wait_minutes else 20
            nxt = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=wait)
            retry["next_attempt_after"] = nxt.isoformat(timespec="seconds")
        _save(RETRY_FILE, retry)
        _out({"recorded": rec, "retry_state": retry})
    elif a == "log":
        rows = _read_jsonl(RUNS_FILE)
        _out({"count": len(rows), "runs": rows[-args.limit:]})
    elif a == "retry-state":
        _out(_load(RETRY_FILE, default_retry))
    elif a == "should-retry":
        cfg = _load(CONFIG_FILE, default_config)
        retry = _load(RETRY_FILE, default_retry)
        maxa = cfg.get("retry", {}).get("max_attempts", 3)
        today = TODAY()
        attempts = retry["attempts"] if retry.get("date") == today else 0
        _out(
            {
                "date": today,
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
def build_parser():
    p = argparse.ArgumentParser(prog="papers.py", description=__doc__)
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
    s.add_argument("key", help="dotted key, e.g. digest.target_paper_count")
    s.add_argument("value")
    s.set_defaults(func=cmd_config)

    # interests
    it = sub.add_parser("interests", help="topics, keywords, authors, labs, instructions")
    its = it.add_subparsers(dest="interests_action", required=True)
    its.add_parser("show").set_defaults(func=cmd_interests)
    for act in ("add", "remove"):
        a = its.add_parser(act)
        a.add_argument("field", help=f"one of {sorted(LIST_FIELDS)}")
        a.add_argument("values", nargs="+")
        a.set_defaults(func=cmd_interests)
    si = its.add_parser("set-instructions")
    si.add_argument("text")
    si.set_defaults(func=cmd_interests)

    # sources
    so = sub.add_parser("sources", help="watch list of blogs / feeds / trending sources")
    sos = so.add_subparsers(dest="sources_action", required=True)
    ls = sos.add_parser("list")
    ls.add_argument("--all", action="store_true", help="include disabled")
    ls.set_defaults(func=cmd_sources)
    ad = sos.add_parser("add")
    ad.add_argument("name")
    ad.add_argument("url")
    ad.add_argument("--type", default="blog", choices=["blog", "arxiv", "trending", "other"])
    ad.add_argument("--feed", default="")
    ad.add_argument("--priority", type=int, default=1)
    ad.add_argument("--notes", default="")
    ad.set_defaults(func=cmd_sources)
    for act in ("remove", "disable"):
        r = sos.add_parser(act)
        r.add_argument("query", help="id, name substring, or url")
        if act == "remove":
            r.add_argument("--hard", action="store_true", help="delete instead of disable")
        r.set_defaults(func=cmd_sources)
    nt = sos.add_parser("note")
    nt.add_argument("query")
    nt.add_argument("text")
    nt.set_defaults(func=cmd_sources)
    bp = sos.add_parser("bump", help="adjust usefulness score")
    bp.add_argument("query")
    bp.add_argument("delta", type=int)
    bp.set_defaults(func=cmd_sources)

    # seen
    se = sub.add_parser("seen", help="dedup tracking of already-raised papers")
    ses = se.add_subparsers(dest="seen_action", required=True)
    h = ses.add_parser("has")
    h.add_argument("paper")
    h.set_defaults(func=cmd_seen)
    a = ses.add_parser("add")
    a.add_argument("paper")
    a.add_argument("--title", default="")
    a.add_argument("--source", default="")
    a.add_argument("--run-id", default="")
    a.add_argument("--dry-run", action="store_true", help="print what would be recorded, don't write state")
    a.set_defaults(func=cmd_seen)
    ses.add_parser("filter", help="stdin ids -> only-unseen").set_defaults(func=cmd_seen)
    ses.add_parser("list").set_defaults(func=cmd_seen)

    # feedback
    fb = sub.add_parser("feedback", help="mark papers useful / not-useful")
    fbs = fb.add_subparsers(dest="feedback_action", required=True)
    fa = fbs.add_parser("add")
    fa.add_argument("paper")
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
    fi.add_argument("--papers", nargs="*", default=[])
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


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
