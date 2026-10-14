#!/usr/bin/env python3
"""Render a Morning Papers digest (Markdown) for posting to Discord.

Stdlib only. Discord renders a subset of Markdown, so this rewrites the digest:
  - [text](url)  -> [text](<url>)   masked link, no preview embed
  - bare https:// -> <https://...>  no preview embed
  - ---, ***, ___ horizontal rules dropped (Discord shows them literally)
  - #### and deeper headings -> **bold line** (Discord has only #, ##, ###)
  - runs of blank lines collapsed

Pipe tables are left alone; the Hermes Discord adapter turns them into bullets.

The output is what the Hermes cron job returns as its final response; the
gateway posts it, split into <=2000-char messages, into a fresh thread. The
Hermes Discord adapter caps one response at 8 messages and replaces the rest
with a truncation notice. Splits land on line boundaries (~1600 chars per
message in practice) and the cron header/footer take a few hundred more, so the
script flags anything over --budget (default 10500 chars, about 7 messages).
Over budget: condense the Discord text (shorter TL;DRs, trim the near-miss
list); the full digest stays on disk.

Usage:
  render_discord.py --body-file digests/2026-07-01.md                # print to stdout
  render_discord.py --body-file d.md --out digests/2026-07-01.discord.md   # write file, print JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_BUDGET = 10500

_FENCE = re.compile(r"^\s*(```|~~~)")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_DEEP_HEADING = re.compile(r"^(#{4,6})\s+(.*?)\s*#*\s*$")
# [text](url) or [text](url "title") whose url is not already <wrapped>
_MASKED = re.compile(r"\[([^\]]+)\]\((?!<)(https?://[^\s)]+)(?:\s+\"[^\"]*\")?\)")
# bare URL not already inside <...>, (...) or [...]
_BARE = re.compile(r"(?<![<(\[])\b(https?://[^\s<>()\[\]]+[^\s<>()\[\].,;:!?'\"*_])")


def _inline(line: str) -> str:
    # Shield inline code spans so URLs inside them stay untouched.
    parts = re.split(r"(`[^`]*`)", line)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) >= 2:
            out.append(p)
            continue
        p = _MASKED.sub(lambda m: f"[{m.group(1)}](<{m.group(2)}>)", p)
        # wrap remaining bare URLs (masked ones are now inside <...>)
        p = _BARE.sub(lambda m: f"<{m.group(1)}>", p)
        out.append(p)
    return "".join(out)


def render(md: str) -> str:
    lines_out: list[str] = []
    in_fence = False
    for line in md.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            lines_out.append(line)
            continue
        if in_fence:
            lines_out.append(line)
            continue
        if _HR.match(line):
            lines_out.append("")
            continue
        m = _DEEP_HEADING.match(line)
        if m:
            line = f"**{m.group(2)}**"
        lines_out.append(_inline(line.rstrip()))
    text = "\n".join(lines_out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--body-file", required=True, help="digest Markdown")
    ap.add_argument("--out", help="write the Discord text here and print a JSON summary")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="max chars before flagging")
    args = ap.parse_args(argv)

    src = Path(args.body_file)
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        return 2
    text = render(src.read_text())
    if not args.out:
        sys.stdout.write(text)
        return 0
    out = Path(args.out)
    out.write_text(text)
    print(json.dumps({
        "out": str(out),
        "chars": len(text),
        "budget": args.budget,
        "over_budget": len(text) > args.budget,
        "approx_messages": -(-len(text) // 1600),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
