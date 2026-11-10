#!/usr/bin/env python3
"""Spec-driven CLI (digestkit.core) for both digests.

Stdlib only, temp homes only:  python3 tests/test_core.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
CLI = {"papers": SCRIPTS / "papers.py", "headlines": SCRIPTS / "headlines.py"}
SEEDS = {"papers": 17, "headlines": None}  # headlines: len(SEED_SOURCES)

_fails: list[str] = []
_tmp: Path


def check(name: str, cond: bool) -> None:
    print(("PASS " if cond else "FAIL "), name)
    if not cond:
        _fails.append(name)


def env_for(digest: str, home: Path | None = None) -> dict:
    e = {**os.environ,
         "MORNING_PAPERS_HOME": str(_tmp / "papers"),
         "MORNING_HEADLINES_HOME": str(_tmp / "headlines")}
    if home is not None:
        e["MORNING_PAPERS_HOME" if digest == "papers" else "MORNING_HEADLINES_HOME"] = str(home)
    return e


def cli(digest, *args, stdin=None, env=None, expect_ok=True, cwd=None):
    r = subprocess.run([sys.executable, str(CLI[digest]), *args], env=env or env_for(digest),
                       input=stdin, capture_output=True, text=True, cwd=cwd)
    if expect_ok:
        assert r.returncode == 0, f"{digest} {args} exited {r.returncode}: {r.stderr}"
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {"_rc": r.returncode, "_err": r.stderr}
    except json.JSONDecodeError:
        return {"_rc": r.returncode, "_out": r.stdout, "_err": r.stderr}


def test_init(d):
    sys.path.insert(0, str(REPO))
    from digestkit.specs import headlines as hs
    SEEDS["headlines"] = len(hs.SEED_SOURCES)
    r = cli(d, "init")
    check(f"{d}: init creates 5 files", len(r["created"]) == 5)
    check(f"{d}: init idempotent", cli(d, "init")["created"] == [])
    st = cli(d, "status")
    check(f"{d}: seed source count", st["counts"]["sources_total"] == SEEDS[d])
    led = "seen_papers" if d == "papers" else "seen_items"
    check(f"{d}: status counts {led}", st["counts"][led] == 0)
    check(f"{d}: unconfigured at start", st["configured"] is False)
    srcs = cli(d, "sources", "list")["sources"]
    check(f"{d}: unique source ids", len({s['id'] for s in srcs}) == len(srcs))
    check(f"{d}: all seed URLs are https", all(s["url"].startswith("https://") and
                                               (not s["feed"] or s["feed"].startswith("https://")) for s in srcs))
    if d == "headlines":
        check("headlines: sources carry filter + class", all("filter" in s and "class" in s for s in srcs))
        types = {s["type"] for s in srcs}
        check("headlines: seed types are valid", types <= set(hs.SPEC.source_types))
        check("headlines: dead/blocked URLs not seeded", not any(
            s["url"] in ("https://lmarena.ai/leaderboard", "https://z.ai/blog") for s in srcs))
        econ = next(s for s in srcs if s["type"] == "arxiv")
        check("headlines: arXiv econ query via export.arxiv.org", econ["url"].startswith(
            "https://export.arxiv.org/api/query?search_query=") and "econ.TH" in econ["url"])
        cfg = cli(d, "config", "show")
        check("headlines: subject + smtp env", cfg["email"]["subject_template"] == "The Morning Headlines — {date}"
              and cfg["smtp"]["password_env"] == "MORNING_HEADLINES_SMTP_PASSWORD")
    else:
        check("papers: no headlines-only source fields", all("class" not in s for s in srcs))


def test_config_interests(d):
    cli(d, "config", "set", "digest.verbosity", "terse")
    check(f"{d}: config set/get", cli(d, "config", "get", "digest.verbosity")["digest.verbosity"] == "terse")
    cli(d, "config", "set", "delivery.method", "discord")
    check(f"{d}: discord-only configured", cli(d, "status")["configured"] is True)
    bad = cli(d, "config", "set", "delivery.method", "fax", expect_ok=False)
    check(f"{d}: bad delivery rejected", bad.get("_rc") == 2)
    field = "labs_prioritize"
    cli(d, "interests", "add", field, "Lab A", "Lab B")
    check(f"{d}: interests add", cli(d, "interests", "show")[field] == ["Lab A", "Lab B"])
    if d == "headlines":
        cli(d, "interests", "add", "models_prioritize", "open-weights")
        check("headlines: models_prioritize field", cli(d, "interests", "show")["models_prioritize"] == ["open-weights"])
    else:
        bad = cli(d, "interests", "add", "models_prioritize", "x", expect_ok=False)
        check("papers: headlines-only interest field rejected", bad.get("_rc") == 2)


def test_sources(d):
    n0 = len(cli(d, "sources", "list")["sources"])
    typ = "blog" if d == "papers" else "leaderboard"
    extra = [] if d == "papers" else ["--class", "primary", "--filter", "AI only"]
    r = cli(d, "sources", "add", "Test Src", "https://t.example/", "--type", typ,
            "--feed", "https://t.example/feed.xml", *extra)
    check(f"{d}: source added", len(cli(d, "sources", "list")["sources"]) == n0 + 1)
    if d == "headlines":
        check("headlines: class/filter stored", r["added"]["class"] == "primary" and r["added"]["filter"] == "AI only")
    bad = cli(d, "sources", "add", "X", "https://x/", "--type", "nonsense", expect_ok=False)
    check(f"{d}: invalid source type rejected", bad.get("_rc") == 2)
    cli(d, "sources", "disable", "Test Src")
    check(f"{d}: disable", len(cli(d, "sources", "list")["sources"]) == n0)
    cli(d, "sources", "enable", "Test Src")
    check(f"{d}: enable", len(cli(d, "sources", "list")["sources"]) == n0 + 1)
    # sync-blogwatcher without blogwatcher installed: printing path only
    sb = cli(d, "sources", "sync-blogwatcher", "--dry-run", "--blogwatcher", "no-such-blogwatcher-binary")
    feeds = [s for s in cli(d, "sources", "list")["sources"] if s["feed"]]
    check(f"{d}: sync-blogwatcher dry-run lists every feed source", sb["dry_run"] is True
          and sb["tracked_known"] is False and len(sb["to_add"]) == len(feeds))
    cmd = next(t["command"] for t in sb["to_add"] if t["id"] == "test-src")
    home = _tmp / d
    check(f"{d}: sync command uses this digest's db", cmd[:4] == ["no-such-blogwatcher-binary", "--db",
          str(home / "state" / "blogwatcher.db"), "add"] and cmd[-2:] == ["--feed-url", "https://t.example/feed.xml"])
    nb = cli(d, "sources", "sync-blogwatcher", "--blogwatcher", "no-such-blogwatcher-binary", expect_ok=False)
    check(f"{d}: sync-blogwatcher without binary exits 3", nb.get("_rc") == 3)


def test_feedback_runs(d):
    cli(d, "feedback", "add", "https://t.example/p1", "useful", "--note", "good", "--source", "Test Src")
    cli(d, "feedback", "add", "https://t.example/p2", "not-useful")
    fs = cli(d, "feedback", "summary")
    check(f"{d}: feedback summary", fs["useful"] == 1 and fs["not_useful"] == 1 and fs["recent_useful"] == ["good"])
    src = next(s for s in cli(d, "sources", "list")["sources"] if s["id"] == "test-src")
    check(f"{d}: feedback credits source", src["usefulness"] == 1)
    noun = "paper" if d == "papers" else "item"
    check(f"{d}: feedback record uses '{noun}'", noun in cli(d, "feedback", "list")["feedback"][0])
    r1 = cli(d, "run", "start")
    check(f"{d}: attempt 1", r1["attempt"] == 1)
    f = cli(d, "run", "finish", r1["run_id"], "failed", "--error", "boom", "--wait-minutes", "20")
    check(f"{d}: failure sets retry", f["retry_state"]["last_error"] == "boom"
          and f["retry_state"]["next_attempt_after"])
    r2 = cli(d, "run", "start")
    check(f"{d}: attempts persist", r2["attempt"] == 2)
    flag = "--papers" if d == "papers" else "--items"
    ok = cli(d, "run", "finish", r2["run_id"], "success", "--attempt", "2", "--sections", "4", flag, "k1", "k2")
    check(f"{d}: success resets", ok["retry_state"]["attempts"] == 0
          and ok["recorded"][f"{noun}s_raised"] == ["k1", "k2"])
    check(f"{d}: should-retry after success", cli(d, "run", "should-retry")["should_retry"] is True)
    # dry-runs mutate nothing
    state = _tmp / d / "state"
    before = {p.name: p.read_text() for p in state.iterdir() if p.is_file()}
    dr = cli(d, "run", "start", "--dry-run")
    cli(d, "seen", "add", "https://t.example/p9", "--run-id", dr["run_id"], "--dry-run")
    cli(d, "run", "finish", dr["run_id"], "success", "--dry-run")
    after = {p.name: p.read_text() for p in state.iterdir() if p.is_file()}
    check(f"{d}: dry-runs leave state untouched", before == after and dr["run_id"].startswith("dry-run-"))


def test_home_precedence():
    a, b = _tmp / "home-a", _tmp / "home-b"
    for d in ("papers", "headlines"):
        env = env_for(d, home=a)
        r = cli(d, "--home", str(b), "init", env=env)
        check(f"{d}: --home beats env", r["root"] == str(b))
        check(f"{d}: env beats default", cli(d, "status", env=env)["root"] == str(a))
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)
    e = {k: v for k, v in os.environ.items() if k not in ("MORNING_PAPERS_HOME", "MORNING_HEADLINES_HOME")}
    sys.path.insert(0, str(REPO))
    from digestkit import specs
    check("headlines default home = <repo>/headlines",
          specs.get("headlines").default_home() == REPO / "headlines")
    check("papers default home = repo root", specs.get("papers").default_home() == REPO)
    # scripts work by absolute path from any cwd
    r = subprocess.run([sys.executable, str(CLI["headlines"]), "--home", str(a), "status"],
                       env=e, capture_output=True, text=True, cwd="/")
    check("absolute-path invocation from another cwd", r.returncode == 0 and json.loads(r.stdout)["root"] == str(a))


GOOD_DIGEST = """# The Morning Headlines — 2026-11-09

## ⭐ Top Stories

1. **[Lab ships Model Z](https://lab.example/model-z)**: first open-weights model at the frontier.

## Model releases

- **[Model Y](https://huggingface.co/org/model-y)** [open-weights]: a 7B model. *Also:* [TechCrunch](https://techcrunch.com/y)

## Also notable

- [Minor thing](https://minor.example/x): not marked seen.
"""


def test_decisions():
    d = "headlines"
    dg = _tmp / d / "digests"
    lines = [
        {"id": "url:https://lab.example/model-z", "title": "Model Z", "source": "Lab", "opened": True,
         "decision": "main", "reason": "frontier", "section": "top-stories"},
        {"id": "https://huggingface.co/org/model-y", "title": "Model Y", "source": "HF", "opened": True,
         "decision": "main", "reason": "open", "section": "model-releases"},
        {"id": "https://techcrunch.com/y", "title": "Y press", "source": "TC", "opened": False,
         "decision": "dropped", "reason": "merged", "merged_into": "hf:org/model-y"},
        {"id": "https://minor.example/x", "title": "Minor", "source": "HN", "opened": False,
         "decision": "near-miss", "reason": "small", "section": "also-notable"},
    ]
    (dg / "2026-11-09.decisions.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    (dg / "2026-11-09.md").write_text(GOOD_DIGEST)
    # relative paths resolve under the digest home first (cwd = repo root, like the cron job)
    ok = cli(d, "decisions", "check", "digests/2026-11-09.decisions.jsonl",
             "--digest-file", "digests/2026-11-09.md", cwd=str(REPO))
    check("decisions check ok", ok["ok"] is True and ok["counts"] == {"main": 2, "near-miss": 1, "dropped": 1}
          and ok["digest"]["main_links"] == 2)
    bad = lines + [{"id": "x", "title": "T", "source": "s", "opened": "yes", "decision": "maybe"},
                   {"id": "https://ghost.example/", "title": "Ghost", "source": "s", "opened": True,
                    "decision": "main", "reason": "r"}]
    (dg / "bad.jsonl").write_text("\n".join(json.dumps(x) for x in bad) + "\nnot json\n")
    r = cli(d, "decisions", "check", str(dg / "bad.jsonl"), "--digest-file", str(dg / "2026-11-09.md"),
            expect_ok=False)
    errs = " ".join(e["error"] for e in r.get("errors", []))
    check("decisions check exit 1 on problems", r.get("ok") is False)
    check("schema errors reported", "opened" in errs and "decision" in errs and "reason" in errs
          and "invalid JSON" in errs)
    check("main entry missing from digest reported",
          [m["id"] for m in r["digest"]["main_missing_from_digest"]] == ["https://ghost.example/"])
    (dg / "partial.jsonl").write_text(json.dumps(lines[0]) + "\n")
    r2 = cli(d, "decisions", "check", str(dg / "partial.jsonl"), "--digest-file", str(dg / "2026-11-09.md"),
             expect_ok=False)
    check("digest link missing from log reported",
          [m["url"] for m in r2["digest"]["missing_from_log"]] == ["https://huggingface.co/org/model-y"])
    # the papers digest gets the same verb
    pd = _tmp / "papers" / "digests"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "d.jsonl").write_text(json.dumps({"id": "arxiv:2611.00001", "title": "P", "source": "arXiv",
                                            "opened": True, "decision": "main", "reason": "novel"}) + "\n")
    (pd / "d.md").write_text("## Sec\n\n- **[P](https://arxiv.org/abs/2611.00001v2)** — x\n\n"
                             "## Didn't quite make the cut\n\n- [Q](https://arxiv.org/abs/2611.00002)\n")
    rp = cli("papers", "decisions", "check", str(pd / "d.jsonl"), "--digest-file", str(pd / "d.md"))
    check("papers: decisions check, near-miss section ignored", rp["ok"] is True)


def test_snapshot():
    d = "headlines"
    f = _tmp / "page.txt"
    f.write_text("1. Model A 1400\n2. Model B 1390\n")
    s = cli(d, "snapshot", "save", "Artificial Analysis", "--file", str(f))
    check("snapshot save", s["source"] == "artificial-analysis" and s["lines"] == 2)
    f.write_text("1. Model C 1410\n2. Model A 1400\n3. Model B 1390\n")
    df = cli(d, "snapshot", "diff", "Artificial Analysis", "--file", str(f), "--save")
    check("snapshot diff added/removed", df["changed"] and "1. Model C 1410" in df["added"]
          and "1. Model A 1400" in df["removed"] and "2. Model A 1400" in df["added"])
    df2 = cli(d, "snapshot", "diff", "Artificial Analysis", "--file", str(f))
    check("snapshot diff after save is empty", df2["changed"] is False and df2["has_previous"] is True)


def test_render_and_email_digest_flag():
    hd = _tmp / "headlines" / "digests"
    (hd / "h.md").write_text(GOOD_DIGEST)
    env = env_for("headlines")
    r = subprocess.run([sys.executable, str(SCRIPTS / "render_discord.py"), "--digest", "headlines",
                        "--body-file", "digests/h.md", "--out", "digests/h.discord.md"],
                       env=env, capture_output=True, text=True, cwd=str(REPO))
    info = json.loads(r.stdout) if r.returncode == 0 else {}
    check("render_discord --digest headlines resolves under its home",
          r.returncode == 0 and info.get("out") == str(hd / "h.discord.md") and (hd / "h.discord.md").exists())
    cli("headlines", "config", "set", "email.to", "reader@example.com")
    e = subprocess.run([sys.executable, str(SCRIPTS / "send_email.py"), "--digest", "headlines",
                        "--body-file", "digests/h.md", "--transport", "smtp", "--dry-run"],
                       env=env, capture_output=True, text=True, cwd=str(REPO))
    from email.header import decode_header, make_header
    subj = next((ln[len("Subject: "):] for ln in e.stdout.splitlines() if ln.startswith("Subject: ")), "")
    subj = str(make_header(decode_header(subj)))
    check("send_email --digest headlines uses headlines config", e.returncode == 0
          and "To: reader@example.com" in e.stdout and subj.startswith("The Morning Headlines — "))


def test_headlines_sample():
    sys.path.insert(0, str(REPO))
    from digestkit.core import digest_main_links
    from digestkit.discord import render
    from digestkit.specs import headlines as hs
    md = (REPO / "headlines" / "digests" / "sample.md").read_text()
    heads = [ln[3:].strip() for ln in md.splitlines() if ln.startswith("## ")]
    check("sample has every section in order", heads == [t for _, t in hs.SECTIONS])
    top = md.split("## ⭐ Top Stories", 1)[1]
    first = next(ln for ln in top.splitlines() if ln.strip())
    check("sample Top Stories starts with a '1.' line", first.startswith("1. **["))
    links = digest_main_links(md, hs.SPEC.near_miss_headings)
    check("sample main links exclude Also notable", len(links) == 16
          and not any(ln["section"] == "Also notable" for ln in links))
    check("sample exercises Also:, open-weights, API, tech-report pointer",
          "*Also:*" in md and "[open-weights]" in md and "[API]" in md and "see The Morning Papers" in md)
    check("sample fits the Discord budget", len(render(md)) < 10500)
    check("sample has no email addresses", "@" not in md)


TESTS = [
    (test_headlines_sample, False),
    (test_init, True), (test_config_interests, True), (test_sources, True), (test_feedback_runs, True),
    (test_home_precedence, False), (test_decisions, False), (test_snapshot, False),
    (test_render_and_email_digest_flag, False),
]


def main() -> int:
    global _tmp
    _tmp = Path(tempfile.mkdtemp(prefix="hermes-verify-core-"))
    try:
        for t, per_digest in TESTS:
            for d in (("papers", "headlines") if per_digest else (None,)):
                print(f"\n# {t.__name__}" + (f" [{d}]" if d else ""))
                t(d) if d else t()
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
    print("\n" + ("ALL PASS" if not _fails else f"{len(_fails)} FAILED: {_fails}"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
