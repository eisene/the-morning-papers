#!/usr/bin/env python3
"""URL canonicalization, item keys and `items group` merging.

Stdlib only, temp homes only:  python3 tests/test_urls.py
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
sys.path.insert(0, str(REPO))

from digestkit.urls import canonical_url, item_key, legacy_key, match_keys, normalize_tag  # noqa: E402

HEADLINES = REPO / "scripts" / "headlines.py"
_fails: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("PASS " if cond else "FAIL "), name)
    if not cond:
        _fails.append(name)


CANON = [
    ("https://example.com/post?utm_source=x&utm_medium=y&id=3", "https://example.com/post?id=3"),
    ("http://www.Example.com/a/", "https://example.com/a"),
    ("https://m.example.com/a#section-2", "https://example.com/a"),
    ("https://amp.example.com/story/amp", "https://example.com/story"),
    ("https://example.com/story/amp/", "https://example.com/story"),
    ("https://example.com/story?output=amp", "https://example.com/story"),
    ("https://example.com/story?output=json", "https://example.com/story?output=json"),
    ("https://example.com/", "https://example.com/"),
    ("https://example.com", "https://example.com/"),
    ("https://example.com//a//b/", "https://example.com/a/b"),
    ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
    ("https://example.com/p?ref=hn&fbclid=1&gclid=2&mc_cid=3&mc_eid=4&igshid=5&si=6&s=7&smid=8"
     "&cmpid=9&_hsenc=a&_hsmi=b&mkt_tok=c&spm=d&share=e&ref_src=f&source=g", "https://example.com/p"),
    ("https://news.google.com/rss/articles/abc?url=https%3A%2F%2Fwww.reuters.com%2Ftech%2Fx%2F%3Futm_source%3Dg",
     "https://reuters.com/tech/x"),
    ("https://www.google.com/url?q=https://openai.com/index/x/&sa=D", "https://openai.com/index/x"),
    ("https://t.co/AbC123", "https://t.co/AbC123"),
    ("HTTPS://OpenAI.com/Index/GPT", "https://openai.com/Index/GPT"),
]

KEYS = [
    ("https://arxiv.org/abs/2611.05417", "arxiv:2611.05417"),
    ("https://arxiv.org/abs/2611.05417v2", "arxiv:2611.05417"),
    ("https://arxiv.org/pdf/2611.05417v1", "arxiv:2611.05417"),
    ("https://arxiv.org/pdf/2611.05417.pdf", "arxiv:2611.05417"),
    ("https://arxiv.org/html/2611.05417v3", "arxiv:2611.05417"),
    ("https://huggingface.co/papers/2611.05417", "arxiv:2611.05417"),
    ("https://www.alphaxiv.org/abs/2611.05417", "arxiv:2611.05417"),
    ("https://www.alphaxiv.org/overview/2611.05417v1", "arxiv:2611.05417"),
    ("2611.05417v4", "arxiv:2611.05417"),
    ("arXiv:2611.05417", "arxiv:2611.05417"),
    ("https://huggingface.co/OpenOrg/Model-7B", "hf:openorg/model-7b"),
    ("https://huggingface.co/OpenOrg/Model-7B/tree/main", "hf:openorg/model-7b"),
    ("https://huggingface.co/blog/some-post", "url:https://huggingface.co/blog/some-post"),
    ("https://huggingface.co/spaces/org/demo", "hfspace:org/demo"),
    ("https://huggingface.co/datasets/org/data", "hfdata:org/data"),
    ("https://github.com/Owner/Repo", "gh:owner/repo"),
    ("https://github.com/owner/repo/", "gh:owner/repo"),
    ("https://github.com/owner/repo.git", "gh:owner/repo"),
    ("https://github.com/owner/repo/tree/main/src", "gh:owner/repo"),
    ("https://github.com/owner/repo/issues/12", "url:https://github.com/owner/repo/issues/12"),
    ("https://github.com/orgs/x/teams", "url:https://github.com/orgs/x/teams"),
    ("https://www.techcrunch.com/2026/11/08/x/?utm_source=rss", "url:https://techcrunch.com/2026/11/08/x"),
    ("hf:OpenOrg/Model-7B", "hf:openorg/model-7b"),
    ("url:https://www.example.com/a/", "url:https://example.com/a"),
]


def test_canonical():
    for raw, want in CANON:
        got = canonical_url(raw)
        check(f"canonical {raw[:60]}", got == want or print("   got", got) or False)


def test_keys():
    for raw, want in KEYS:
        got = item_key(raw)
        check(f"item_key {raw[:60]}", got == want or print("   got", got) or False)
    import hashlib
    raw = "https://blog.example/post-1"
    check("legacy key = sha1 of the raw string",
          legacy_key(raw) == "url:" + hashlib.sha1(raw.encode()).hexdigest()[:16]
          and legacy_key(raw) != legacy_key(raw + "/"))
    check("legacy arxiv keys unchanged", legacy_key("https://arxiv.org/pdf/2401.01234v3") == "arxiv:2401.01234"
          and legacy_key("2401.01234") == "arxiv:2401.01234")
    mk = match_keys("https://www.Example.com/a/?utm_source=x")
    check("match keys: canonical + legacy hash",
          "url:https://example.com/a" in mk and legacy_key("https://www.Example.com/a/?utm_source=x") in mk)
    check("tag normalization", normalize_tag(" Model: GPT 6.1 ") == "model:gpt-6.1"
          and normalize_tag("LAB:OpenAI") == "lab:openai")


# ---------------------------------------------------------------------------
# items group (CLI)
# ---------------------------------------------------------------------------
def hl(home, *args, stdin=None, expect_ok=True):
    env = {**os.environ, "MORNING_HEADLINES_HOME": str(home),
           "MORNING_PAPERS_HOME": str(home.parent / "papers-none")}
    r = subprocess.run([sys.executable, str(HEADLINES), *args], env=env, input=stdin,
                       capture_output=True, text=True)
    if expect_ok:
        assert r.returncode == 0, f"{args} exited {r.returncode}: {r.stderr}"
    return json.loads(r.stdout) if r.stdout.strip() else {"_rc": r.returncode, "_err": r.stderr}


LAUNCH = [
    {"url": "https://techcrunch.com/2026/11/08/acme-launches-widget-5/?utm_source=rss",
     "title": "Acme launches Widget 5", "source": "TechCrunch AI", "tags": ["model:widget-5"]},
    {"url": "https://www.techmeme.com/261108/p12#a261108p12", "title": "Acme Widget 5",
     "source": "Techmeme", "tags": ["model:Widget 5"]},
    {"url": "https://news.smol.ai/issues/26-11-08-widget", "title": "AINews: Widget 5",
     "source": "smol.ai AI News", "tags": ["model:widget-5", "lab:acme"]},
    {"url": "https://openai.com/index/widget-5/", "title": "Introducing Widget 5",
     "source": "OpenAI News", "tags": ["model:widget-5"]},
    {"url": "https://openai.com/index/widget-5?utm_campaign=x", "title": "dupe link", "source": "HN"},
    {"url": "https://www.theverge.com/news/unrelated", "title": "Something else", "source": "The Verge AI"},
]


def test_group():
    home = Path(tempfile.mkdtemp(prefix="hermes-verify-hl-")) / "hl"
    try:
        hl(home, "init")
        g = hl(home, "items", "group", stdin=json.dumps(LAUNCH))
        check("6 candidates -> 2 groups", g["input_count"] == 6 and g["count"] == 2)
        launch = g["groups"][0]
        check("primary = lab post", launch["primary"]["url"].startswith("https://openai.com/index/widget-5")
              and launch["primary"]["class"] == "primary")
        check("3 also links (TechCrunch, Techmeme, smol.ai)", len(launch["also"]) == 3
              and {a["source"] for a in launch["also"]} == {"TechCrunch AI", "Techmeme", "smol.ai AI News"})
        check("press ranked before aggregators in also", launch["also"][0]["source"] == "TechCrunch AI")
        check("group has every member key", "url:https://openai.com/index/widget-5" in launch["member_keys"]
              and len(launch["member_keys"]) == 4)
        check("tags merged + normalized", "model:widget-5" in launch["tags"] and "lab:acme" in launch["tags"])
        check("not covered yet", launch["covered"] is False and launch["covered_on"] is None)
        # tag-only merge: different URLs, same model tag
        tag_only = [
            {"url": "https://example-lab.ai/blog/nova-2", "title": "Nova 2", "source": "x", "tags": ["model:nova-2"]},
            {"url": "https://reuters.com/tech/nova-2-launch", "title": "Lab ships Nova 2", "source": "y",
             "tags": ["model:Nova-2"]},
            {"url": "https://huggingface.co/example-lab/Nova-2-7B", "title": "model card", "source": "HF",
             "tags": ["model:nova-2"]},
        ]
        g2 = hl(home, "items", "group", stdin=json.dumps(tag_only))
        check("tag-based merge with different URLs", g2["count"] == 1 and g2["groups"][0]["size"] == 3)
        check("model card wins primary over unknown lab domain and press",
              g2["groups"][0]["primary"]["key"] == "hf:example-lab/nova-2-7b")
        # covered_on: a tag raised before
        hl(home, "seen", "add", "https://openai.com/index/widget-5/", "--title", "Widget 5",
           "--tag", "model:widget-5", "--tag", "lab:openai")
        follow = [{"url": "https://www.axios.com/2026/11/09/widget-5-pricing", "title": "Widget 5 pricing",
                   "source": "Axios", "tags": ["model:widget-5"]}]
        g3 = hl(home, "items", "group", stdin=json.dumps(follow))
        grp = g3["groups"][0]
        check("previously seen tag -> covered_on", grp["covered"] is True and grp["covered_on"] is not None
              and grp["covered_by"][0]["via"] == "tag:model:widget-5")
        check("own coverage marks seen", grp["seen"] is True and grp["peer_seen"] == [])
        g4 = hl(home, "items", "group", stdin="https://openai.com/index/widget-5\nhttps://example.com/x\n")
        check("newline input accepted; seen by key", g4["count"] == 2 and g4["groups"][0]["seen"] is True
              and g4["groups"][1]["seen"] is False)
    finally:
        shutil.rmtree(home.parent, ignore_errors=True)


TESTS = [test_canonical, test_keys, test_group]


def main() -> int:
    for t in TESTS:
        print(f"\n# {t.__name__}")
        t()
    print("\n" + ("ALL PASS" if not _fails else f"{len(_fails)} FAILED: {_fails}"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
