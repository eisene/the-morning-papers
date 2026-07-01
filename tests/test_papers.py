#!/usr/bin/env python3
"""End-to-end tests for the-morning-papers scripts.

Runs papers.py + send_email.py against an ISOLATED temp MORNING_PAPERS_HOME so
the repo's own config/state is never touched. Stdlib only — no pytest needed:

    python3 tests/test_papers.py        # or: make test

Exit 0 = all pass. Each check prints PASS/FAIL; a final line summarizes.
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
PAPERS = REPO / "scripts" / "papers.py"
EMAIL = REPO / "scripts" / "send_email.py"

_fails: list[str] = []
_home: Path
_env: dict


def setup() -> None:
    global _home, _env
    _home = Path(tempfile.mkdtemp(prefix="hermes-verify-mp-"))
    _env = {**os.environ, "MORNING_PAPERS_HOME": str(_home)}


def teardown() -> None:
    shutil.rmtree(_home, ignore_errors=True)


def papers(*args: str, stdin: str | None = None, expect_ok: bool = True) -> dict:
    r = subprocess.run(
        [sys.executable, str(PAPERS), *args],
        env=_env, input=stdin, capture_output=True, text=True,
    )
    if expect_ok:
        assert r.returncode == 0, f"{args} exited {r.returncode}: {r.stderr}"
    return json.loads(r.stdout) if r.stdout.strip() else {"_rc": r.returncode, "_err": r.stderr}


def check(name: str, cond: bool) -> None:
    print(("PASS " if cond else "FAIL "), name)
    if not cond:
        _fails.append(name)


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_init_status():
    d = papers("init")
    check("init creates 5 files", len(d["created"]) == 5)
    check("init not forced is idempotent", papers("init")["created"] == [])
    check("status starts unconfigured", papers("status")["configured"] is False)
    check("seed sources present", papers("status")["counts"]["sources_total"] == 17)


def test_interests():
    papers("interests", "add", "topics", "interp", "rl")
    papers("interests", "add", "authors_exclude", "Spammer")
    check("topics added in order", papers("interests", "show")["topics"] == ["interp", "rl"])
    check("dupes ignored", papers("interests", "add", "topics", "interp")["topics"] == ["interp", "rl"])
    papers("interests", "remove", "topics", "rl")
    check("remove works", papers("interests", "show")["topics"] == ["interp"])
    papers("interests", "set-instructions", "focus on theory")
    check("instructions set", papers("interests", "show")["extra_instructions"] == "focus on theory")
    bad = papers("interests", "add", "nonsense", "x", expect_ok=False)
    check("unknown field rejected", bad.get("_rc") == 2)


def test_config():
    papers("config", "set", "email.to", "me@x.com")
    papers("config", "set", "digest.target_paper_count", "9")
    papers("config", "set", "smtp.use_tls", "false")
    check("str set", papers("config", "get", "email.to")["email.to"] == "me@x.com")
    check("int coercion", papers("config", "get", "digest.target_paper_count")["digest.target_paper_count"] == 9)
    check("bool coercion", papers("config", "get", "smtp.use_tls")["smtp.use_tls"] is False)
    check("nested get on missing key is None", papers("config", "get", "email.nope")["email.nope"] is None)
    check("status configured after email.to", papers("status")["configured"] is True)


def test_sources():
    n0 = len(papers("sources", "list")["sources"])
    papers("sources", "add", "Test Blog", "https://t.example/blog", "--type", "blog")
    check("source added", len(papers("sources", "list")["sources"]) == n0 + 1)
    # re-add updates instead of duplicating
    papers("sources", "add", "Test Blog", "https://t.example/v2", "--type", "blog")
    check("re-add dedupes by slug", len(papers("sources", "list")["sources"]) == n0 + 1)
    papers("sources", "disable", "Test Blog")
    check("disable hides from active", len(papers("sources", "list")["sources"]) == n0)
    check("disabled kept in --all", any(s["name"] == "Test Blog"
          for s in papers("sources", "list", "--all")["sources"]))
    papers("sources", "bump", "Hugging Face", "3")
    hf = next(s for s in papers("sources", "list")["sources"] if "Hugging Face" in s["name"])
    check("bump adjusts usefulness", hf["usefulness"] == 3)
    miss = papers("sources", "disable", "does-not-exist", expect_ok=False)
    check("missing source errors", miss.get("_rc") == 2)


def test_seen_dedup():
    check("unseen before add", papers("seen", "has", "https://arxiv.org/abs/2401.01234")["seen"] is False)
    papers("seen", "add", "2401.01234", "--title", "T")
    check("pdf+version url matches abs", papers("seen", "has", "https://arxiv.org/pdf/2401.01234v3")["seen"] is True)
    check("hf url matches abs", papers("seen", "has", "https://huggingface.co/papers/2401.01234")["seen"] is True)
    check("bare arxiv:id matches", papers("seen", "has", "arxiv:2401.01234")["seen"] is True)
    filt = papers("seen", "filter", stdin="2401.01234\n2405.99999\n")
    check("filter keeps only unseen", filt["count"] == 1 and filt["unseen"][0]["key"] == "arxiv:2405.99999")
    jfilt = papers("seen", "filter", stdin='["2401.01234", "2406.00001"]')
    check("filter accepts json list", jfilt["count"] == 1 and jfilt["unseen"][0]["key"] == "arxiv:2406.00001")
    # non-arxiv url dedups by hashed url key
    papers("seen", "add", "https://blog.example/post-1")
    check("url dedup stable", papers("seen", "has", "https://blog.example/post-1")["seen"] is True)


def test_feedback():
    papers("feedback", "add", "2401.01234", "useful", "--note", "good", "--source", "Hugging Face")
    papers("feedback", "add", "2405.00000", "not-useful")
    fs = papers("feedback", "summary")
    check("feedback tallies", fs["useful"] == 1 and fs["not_useful"] == 1)
    # useful verdict credited the source
    hf = next(s for s in papers("sources", "list")["sources"] if "Hugging Face" in s["name"])
    check("useful feedback credits source", hf["usefulness"] >= 1)
    only = papers("feedback", "list", "--verdict", "useful")
    check("feedback list filters by verdict", only["count"] == 1)


def test_run_and_retry():
    r1 = papers("run", "start")
    check("attempt 1", r1["attempt"] == 1)
    fin = papers("run", "finish", r1["run_id"], "failed", "--attempt", "1",
                 "--error", "boom", "--wait-minutes", "20")
    check("failed sets next_attempt_after", fin["retry_state"]["next_attempt_after"] is not None)
    check("failed records last_error", fin["retry_state"]["last_error"] == "boom")
    papers("run", "start")                    # attempt 2
    r3 = papers("run", "start")               # attempt 3
    check("attempts persist across starts", r3["attempt"] == 3)
    sr = papers("run", "should-retry")
    check("should-retry false at max", sr["should_retry"] is False and sr["attempts_so_far"] == 3)
    fin2 = papers("run", "finish", r3["run_id"], "success", "--attempt", "3",
                  "--sections", "4", "--papers", "2401.01234")
    check("success resets retry to 0", fin2["retry_state"]["attempts"] == 0)
    check("should-retry true after reset", papers("run", "should-retry")["should_retry"] is True)
    check("run log has both finishes", papers("run", "log")["count"] == 2)


def test_email_render():
    dg = _home / "digests"
    dg.mkdir(exist_ok=True)
    body = "# Digest\n\n## Sec\n- **[Paper](https://arxiv.org/abs/2401.01234)** — TL;DR *novel* `code`.\n"
    (dg / "test.md").write_text(body)
    r = subprocess.run(
        [sys.executable, str(EMAIL), "--body-file", str(dg / "test.md"),
         "--transport", "smtp", "--dry-run"],
        env=_env, capture_output=True, text=True,
    )
    check("email dry-run exits 0", r.returncode == 0)
    check("email dry-run addresses recipient", "me@x.com" in r.stdout)
    # subject is MIME-encoded (em-dash) but the {date} substitution survives literally
    import datetime as _dt  # noqa: E402
    check("email dry-run subject templated with date", _dt.date.today().isoformat() in r.stdout)
    sys.path.insert(0, str(REPO / "scripts"))
    import send_email  # noqa: E402
    # md_to_html uses the `markdown` package when available, else the stdlib
    # fallback. Assert on renderer-agnostic essentials plus the styled shell.
    html = send_email.md_to_html(body)
    check("md->html heading", "<h1>" in html and "Digest" in html)
    check("md->html list+link", "<li>" in html and '<a href="https://arxiv.org/abs/2401.01234">' in html)
    check("md->html bold+em+code", "<strong>" in html and "<em>" in html and "<code>" in html)
    check("md->html styled shell", "<html>" in html and "max-width:720px" in html)
    # stdlib fallback path stands alone (headings, list, inline)
    basic = send_email._md_to_html_basic(body)
    check("fallback renders heading+list+bold", "<h1>Digest</h1>" in basic
          and "<li>" in basic and "<strong>" in basic)
    # rich constructs only the package handles: tables + fenced code
    rich = "| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\nx=1\n```\n"
    rhtml = send_email.md_to_html(rich)
    try:
        import markdown  # noqa: F401
        check("md->html table (pkg)", "<table>" in rhtml and "<td>1</td>" in rhtml)
        check("md->html fenced code (pkg)", "<pre>" in rhtml and "x=1" in rhtml)
    except ImportError:
        check("md package absent -> fallback still returns html", "<html>" in rhtml)
    # recipient/host required errors (non-dry, no config)
    r2 = subprocess.run(
        [sys.executable, str(EMAIL), "--body-file", str(dg / "test.md"),
         "--to", "", "--transport", "smtp"],
        env={**os.environ, "MORNING_PAPERS_HOME": str(tempfile.mkdtemp(prefix="hermes-verify-mp-empty-"))},
        capture_output=True, text=True,
    )
    check("email without recipient errors", r2.returncode == 2)
    # himalaya path must emit MML (not raw MIME), else himalaya wraps the body
    # as a "noname" attachment. Assert the dry-run template is MML-shaped.
    rh = subprocess.run(
        [sys.executable, str(EMAIL), "--body-file", str(dg / "test.md"),
         "--to", "a@b.com", "--transport", "himalaya", "--dry-run"],
        env=_env, capture_output=True, text=True,
    )
    out = rh.stdout
    check("himalaya emits MML multipart", "<#multipart type=alternative>" in out and "<#/multipart>" in out)
    check("himalaya MML has html part", "<#part type=text/html>" in out)
    check("himalaya MML not raw MIME", "Content-Transfer-Encoding: base64" not in out)
    check("himalaya MML headers plain", out.lstrip().startswith("[dry-run]") and "To: a@b.com" in out)


TESTS = [
    test_init_status, test_interests, test_config, test_sources,
    test_seen_dedup, test_feedback, test_run_and_retry, test_email_render,
]


def main() -> int:
    setup()
    try:
        for t in TESTS:
            print(f"\n# {t.__name__}")
            t()
    finally:
        teardown()
    print("\n" + ("ALL PASS" if not _fails else f"{len(_fails)} FAILED: {_fails}"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
