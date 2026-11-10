#!/usr/bin/env python3
"""Cross-digest dedup: papers <-> headlines ledgers.

Stdlib only, temp homes only:  python3 tests/test_crossdedup.py
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
HEADLINES = REPO / "scripts" / "headlines.py"

_fails: list[str] = []
_tmp: Path
_env: dict


def check(name: str, cond: bool) -> None:
    print(("PASS " if cond else "FAIL "), name)
    if not cond:
        _fails.append(name)


def _run(script, *args, stdin=None, env=None):
    r = subprocess.run([sys.executable, str(script), *args], env=env or _env, input=stdin,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"{script.name} {args} exited {r.returncode}: {r.stderr}"
    return json.loads(r.stdout)


def papers(*a, **k):
    return _run(PAPERS, *a, **k)


def headlines(*a, **k):
    return _run(HEADLINES, *a, **k)


def setup():
    global _tmp, _env
    _tmp = Path(tempfile.mkdtemp(prefix="hermes-verify-xd-"))
    _env = {**os.environ, "MORNING_PAPERS_HOME": str(_tmp / "papers"),
            "MORNING_HEADLINES_HOME": str(_tmp / "headlines")}
    papers("init")
    headlines("init")


def test_headlines_to_papers():
    headlines("seen", "add", "https://www.deepmind-like.example/blog/model-x/?utm_source=x",
              "--title", "Model X", "--tag", "model:model-x", "--alias", "arxiv:2611.07777")
    headlines("seen", "add", "https://institute.example.org/essays/econ-of-intelligence/",
              "--title", "Econ essay", "--alias", "https://arxiv.org/abs/2611.05417")
    f = papers("seen", "filter", stdin="2611.07777v2\nhttps://arxiv.org/abs/2611.05417\n2611.09999\n")
    check("papers: alias'd tech report goes to peer_seen, not unseen",
          [u["key"] for u in f["unseen"]] == ["arxiv:2611.09999"] and f["count"] == 1)
    check("papers: peer_seen names the digest + record",
          len(f["peer_seen"]) == 2 and all(p["digest"] == "headlines" for p in f["peer_seen"])
          and f["peer_seen"][0]["record"]["title"] == "Model X")
    # a lab URL papers would see raw, with different tracking params, still matches
    f2 = papers("seen", "filter",
                stdin='["https://deepmind-like.example/blog/model-x", "https://other.example/post"]')
    check("papers: canonical URL match across key schemes", f2["count"] == 1
          and f2["peer_seen"][0]["input"] == "https://deepmind-like.example/blog/model-x")
    h = papers("seen", "has", "https://arxiv.org/pdf/2611.07777v1")
    check("papers seen has: own seen stays false, peer_seen true",
          h["seen"] is False and h["peer_seen"] is True and h["peer_digest"] == "headlines")
    check("papers stored keys unchanged (legacy scheme)",
          papers("seen", "add", "https://blog.example/p")["key"].startswith("url:")
          and len(papers("seen", "add", "https://blog.example/p")["key"]) == 4 + 16)


def test_papers_to_headlines():
    # new-style papers record: legacy hash key + raw url stored
    rec = papers("seen", "add", "https://www.lab.example/research/finding?utm_source=feed", "--title", "Finding")
    check("papers seen add stores raw url", rec["record"].get("url") ==
          "https://www.lab.example/research/finding?utm_source=feed")
    papers("seen", "add", "2611.04444", "--title", "Some paper")
    f = headlines("seen", "filter", stdin=json.dumps([
        "https://lab.example/research/finding",            # canonical match via stored url
        "https://huggingface.co/papers/2611.04444",        # arxiv match
        "https://news.example/new-thing",
    ]))
    check("headlines: papers records go to peer_seen", f["count"] == 1
          and f["unseen"][0]["key"] == "url:https://news.example/new-thing"
          and {p["digest"] for p in f["peer_seen"]} == {"papers"})
    # an OLD papers record (legacy hash only, no url field) matches only the identical raw URL
    led_path = _tmp / "papers" / "state" / "seen_papers.json"
    led = json.loads(led_path.read_text())
    raw_old = "https://old.example/post-1"
    import hashlib
    led["papers"]["url:" + hashlib.sha1(raw_old.encode()).hexdigest()[:16]] = {
        "first_raised": "2026-10-01", "title": "Old", "source": "", "run_id": ""}
    led_path.write_text(json.dumps(led))
    f2 = headlines("seen", "filter", stdin=raw_old + "\nhttps://old.example/post-1/\n")
    check("headlines: legacy hash record matches identical raw URL", f2["count"] == 1
          and f2["peer_seen"][0]["input"] == raw_old)
    h = headlines("seen", "has", raw_old)
    check("headlines seen has reports peer", h["seen"] is False and h["peer_digest"] == "papers")
    # items group sees peer coverage too
    g = headlines("items", "group", stdin=json.dumps([{"url": "https://arxiv.org/abs/2611.04444v2"}]))
    check("items group: peer_seen + covered_on from papers", g["groups"][0]["peer_seen"][0]["digest"] == "papers"
          and g["groups"][0]["covered_on"] is not None and g["groups"][0]["seen"] is False)


def test_own_alias_dedup():
    headlines("seen", "add", "https://vendor.example/launch", "--alias", "https://press.example/vendor-launch")
    f = headlines("seen", "filter", stdin="https://press.example/vendor-launch?utm_source=tw\n")
    check("headlines: own alias counts as seen", f["count"] == 0 and f["peer_seen"] == [])
    r = headlines("seen", "add", "https://vendor.example/launch", "--tag", "Product: Vendor App")
    check("re-add merges tags", r["record"]["tags"] == ["product:vendor-app"])


def test_missing_peer():
    env = {**os.environ, "MORNING_PAPERS_HOME": str(_tmp / "p2"),
           "MORNING_HEADLINES_HOME": str(_tmp / "does-not-exist")}
    _run(PAPERS, "init", env=env)
    f = _run(PAPERS, "seen", "filter", stdin="2611.00001\n", env=env)
    check("missing peer ledger is not an error", f["count"] == 1 and f["peer_seen"] == [])
    env2 = {**os.environ, "MORNING_HEADLINES_HOME": str(_tmp / "h2"),
            "MORNING_PAPERS_HOME": str(_tmp / "nothing-here")}
    _run(HEADLINES, "init", env=env2)
    h = _run(HEADLINES, "seen", "has", "https://x.example/", env=env2)
    check("headlines without papers ledger", h["seen"] is False and h["peer_seen"] is False)
    (_tmp / "broken" / "state").mkdir(parents=True)
    (_tmp / "broken" / "state" / "seen_items.json").write_text("{not json")
    env3 = {**env, "MORNING_HEADLINES_HOME": str(_tmp / "broken")}
    r = subprocess.run([sys.executable, str(PAPERS), "seen", "filter"], env=env3, input="2611.00002\n",
                       capture_output=True, text=True)
    check("corrupt peer ledger warns, still filters", r.returncode == 0 and json.loads(r.stdout)["count"] == 1
          and "WARN" in r.stderr)


TESTS = [test_headlines_to_papers, test_papers_to_headlines, test_own_alias_dedup, test_missing_peer]


def main() -> int:
    setup()
    try:
        for t in TESTS:
            print(f"\n# {t.__name__}")
            t()
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
    print("\n" + ("ALL PASS" if not _fails else f"{len(_fails)} FAILED: {_fails}"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
