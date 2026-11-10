#!/usr/bin/env python3
"""Back-compat: the new papers CLI / renderers vs the scripts at 2583d84.

Builds a fixture home with the OLD scripts/papers.py (from git), seeds seen /
feedback / runs, copies it, and asserts the new CLI gives identical JSON for the
read and dry-run commands (apart from the new peer_* fields). Also compares
render_discord.py and send_email.py --dry-run output on digests/sample.md.

Stdlib only, temp homes only:  python3 tests/test_backcompat.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = "2583d84"
NEW = REPO / "scripts"
PEER_FIELDS = {"peer_seen", "peer_digest", "peer_key", "peer_record"}

_fails: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("PASS " if cond else "FAIL "), name)
    if not cond:
        _fails.append(name)


def git_show(path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def strip(o):
    if isinstance(o, dict):
        return {k: (None if k == "root" else strip(v)) for k, v in o.items()
                if k not in PEER_FIELDS and k != "ts"}
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="hermes-verify-bc-"))
    try:
        old_dir = tmp / "old"
        old_dir.mkdir()
        for name in ("papers.py", "render_discord.py", "send_email.py"):
            src = git_show(f"scripts/{name}")
            if src is None:
                print(f"SKIP: git show {BASE}:scripts/{name} failed (shallow clone?)")
                return 0
            (old_dir / name).write_text(src)
        h_old, h_new = tmp / "home-old", tmp / "home-new"
        no_peer = tmp / "no-headlines"

        def run(script, home, *args, stdin=None):
            env = {**os.environ, "MORNING_PAPERS_HOME": str(home), "MORNING_HEADLINES_HOME": str(no_peer)}
            r = subprocess.run([sys.executable, str(script), *args], env=env, input=stdin,
                               capture_output=True, text=True)
            return r.returncode, (json.loads(r.stdout) if r.stdout.strip().startswith(("{", "[")) else r.stdout)

        old = old_dir / "papers.py"
        # build the fixture with the OLD cli
        run(old, h_old, "init")
        run(old, h_old, "interests", "add", "topics", "agents", "rl")
        run(old, h_old, "config", "set", "email.to", "reader@example.com")
        run(old, h_old, "sources", "add", "Lab X", "https://lab.example/blog", "--type", "blog",
            "--feed", "https://lab.example/feed.xml")
        for x in ("2401.01234", "https://arxiv.org/abs/2402.00002v3", "https://blog.example/post-1",
                  "https://huggingface.co/papers/2403.00003"):
            run(old, h_old, "seen", "add", x, "--title", f"T {x}", "--source", "S", "--run-id", "r1")
        run(old, h_old, "feedback", "add", "2401.01234", "useful", "--note", "good", "--source", "Lab X")
        run(old, h_old, "feedback", "add", "2402.00002", "not-useful")
        rs = run(old, h_old, "run", "start")[1]
        run(old, h_old, "run", "finish", rs["run_id"], "failed", "--error", "net", "--wait-minutes", "20")
        rs = run(old, h_old, "run", "start")[1]
        run(old, h_old, "run", "finish", rs["run_id"], "success", "--attempt", "2", "--sections", "3",
            "--papers", "arxiv:2401.01234")
        shutil.copytree(h_old, h_new)

        mix = ["2401.01234", "https://arxiv.org/pdf/2402.00002", "https://blog.example/post-1",
               "https://blog.example/post-1/", "2499.99999", "arxiv:2403.00003", "plain words"]
        cmds = [["status"], ["config", "show"], ["config", "get", "email.to"], ["interests", "show"],
                ["sources", "list"], ["sources", "list", "--all"], ["seen", "list"], ["feedback", "summary"],
                ["feedback", "list"], ["feedback", "list", "--verdict", "useful"], ["run", "log"],
                ["run", "should-retry"], ["run", "retry-state"],
                ["seen", "add", "https://blog.example/new", "--title", "N", "--run-id", "r", "--dry-run"],
                ["run", "start", "--dry-run"],
                ["run", "finish", "dry-run-x", "success", "--sections", "2", "--papers", "a", "b", "--dry-run"]]
        cmds += [["seen", "has", x] for x in mix]
        for c in cmds:
            a = run(old, h_old, *c)
            b = run(NEW / "papers.py", h_new, *c)
            check(f"same JSON: {' '.join(c)[:70]}", a[0] == b[0] and strip(a[1]) == strip(b[1]))
        for stdin in ("\n".join(mix) + "\n", json.dumps(mix)):
            a = run(old, h_old, "seen", "filter", stdin=stdin)
            b = run(NEW / "papers.py", h_new, "seen", "filter", stdin=stdin)
            check("seen filter: unseen/count identical, only peer_seen added",
                  a[1]["unseen"] == b[1]["unseen"] and a[1]["count"] == b[1]["count"]
                  and set(b[1]) - set(a[1]) == {"peer_seen"} and b[1]["peer_seen"] == [])
        # error exit codes
        for c in (["interests", "add", "nope", "x"], ["sources", "disable", "no-such-source"],
                  ["config", "set", "delivery.method", "fax"]):
            a, b = run(old, h_old, *c), run(NEW / "papers.py", h_new, *c)
            check(f"same exit code: {' '.join(c)}", a[0] == b[0] == 2)
        for f in ("state/seen_papers.json", "state/runs.jsonl", "state/retry_state.json",
                  "state/feedback.jsonl", "config/config.json", "config/sources.json"):
            check(f"state identical after read/dry-run commands: {f}",
                  (h_old / f).read_text() == (h_new / f).read_text())
        # identical mutations produce identical ledgers (apart from the stored url)
        for h, s in ((h_old, old), (h_new, NEW / "papers.py")):
            run(s, h, "seen", "add", "2405.55555", "--title", "M", "--source", "S", "--run-id", "r2")
        check("seen add of an arXiv id writes the same record",
              json.loads((h_old / "state/seen_papers.json").read_text())
              == json.loads((h_new / "state/seen_papers.json").read_text()))

        # renderers on the tracked sample
        sample = REPO / "digests" / "sample.md"
        a = subprocess.run([sys.executable, str(old_dir / "render_discord.py"), "--body-file", str(sample)],
                           capture_output=True, text=True)
        b = subprocess.run([sys.executable, str(NEW / "render_discord.py"), "--body-file", str(sample)],
                           capture_output=True, text=True)
        check("render_discord output identical on digests/sample.md", a.returncode == b.returncode == 0
              and a.stdout == b.stdout)
        outs = []
        for d, script in (("o", old_dir / "render_discord.py"), ("n", NEW / "render_discord.py")):
            r = subprocess.run([sys.executable, str(script), "--body-file", str(sample),
                                "--out", str(tmp / f"{d}.discord.md")], capture_output=True, text=True)
            j = json.loads(r.stdout)
            j.pop("out")
            outs.append(j)
        check("render_discord --out JSON identical", outs[0] == outs[1])

        def mask(s):
            # Date / Message-ID / MIME boundary are random; the dry-run dump is cut
            # at 800 chars, so a boundary of different length shifts the last line.
            s = re.sub(r"^(Date|Message-ID): .*$", r"\1: X", s, flags=re.M)
            s = re.sub(r'boundary="[^"]+"|={15}\d+==', "B", s)
            return s.splitlines()[:-3]

        for transport, extra in (("smtp", []), ("himalaya", ["--from", "me@example.com"])):
            res = []
            for script, h in ((old_dir / "send_email.py", h_old), (NEW / "send_email.py", h_new)):
                env = {**os.environ, "MORNING_PAPERS_HOME": str(h)}
                r = subprocess.run([sys.executable, str(script), "--body-file", str(sample),
                                    "--transport", transport, "--dry-run", *extra],
                                   env=env, capture_output=True, text=True)
                res.append((r.returncode, mask(r.stdout)))
            check(f"send_email --dry-run identical ({transport})", res[0] == res[1] and res[0][0] == 0)
        sys.path.insert(0, str(NEW))
        import send_email  # noqa: E402
        sys.path.insert(0, str(old_dir))
        import importlib.util
        spec = importlib.util.spec_from_file_location("old_send_email", old_dir / "send_email.py")
        old_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old_mod)
        md = sample.read_text()
        check("md_to_html identical", send_email.md_to_html(md) == old_mod.md_to_html(md))
        check("_md_to_html_basic identical", send_email._md_to_html_basic(md) == old_mod._md_to_html_basic(md))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("ALL PASS" if not _fails else f"{len(_fails)} FAILED: {_fails}"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
