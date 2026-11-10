#!/usr/bin/env python3
"""Render a Morning digest (Markdown) for posting to Discord.

Stdlib only. Thin wrapper over digestkit.discord (see there for the rules):
masked links -> [t](<url>), bare URLs -> <url>, drops ---, #### -> bold,
collapses blank runs, and flags output over the length budget (Hermes posts at
most 8 Discord messages per response).

Over budget: condense the Discord text (shorter TL;DRs, trim the near-miss /
also-notable list); the full digest stays on disk.

--digest papers|headlines or --home only changes where relative --body-file /
--out paths are looked up: under that digest's home first (e.g. headlines/),
then the cwd. Without either flag paths are cwd-relative, as before. Rendering
is the same for both digests.

Usage:
  render_discord.py --body-file digests/2026-07-01.md                # print to stdout
  render_discord.py --body-file d.md --out digests/2026-07-01.discord.md   # write file, print JSON
  render_discord.py --digest headlines --body-file digests/D.md --out digests/D.discord.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digestkit.discord import DEFAULT_BUDGET, render, summary  # noqa: E402,F401
from digestkit import specs  # noqa: E402


def _resolve(p: str, home: Path | None, parent_only: bool = False) -> Path:
    """Relative paths try the digest home first, then the cwd."""
    path = Path(p)
    if home is None or path.is_absolute():
        return path
    alt = home / path
    return alt if (alt.parent if parent_only else alt).exists() else path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--body-file", required=True, help="digest Markdown")
    ap.add_argument("--out", help="write the Discord text here and print a JSON summary")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="max chars before flagging")
    ap.add_argument("--digest", choices=specs.names(), default=None,
                    help="which digest (default papers); resolves relative paths under its home")
    ap.add_argument("--home", default=None, help="digest home (overrides --digest's default)")
    args = ap.parse_args(argv)

    home = None
    if args.home or args.digest:
        home = specs.get(args.digest or "papers").home(args.home)
    src = _resolve(args.body_file, home)
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        return 2
    text = render(src.read_text())
    if not args.out:
        sys.stdout.write(text)
        return 0
    out = _resolve(args.out, home, parent_only=True)
    out.write_text(text)
    print(json.dumps(summary(text, str(out), args.budget), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
