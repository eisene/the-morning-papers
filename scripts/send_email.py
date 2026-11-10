#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["markdown>=3.5"]
# ///
"""Send a Morning digest email (The Morning Papers by default).

Two transports:
  himalaya  -> pipes the message into `himalaya message send` (himalaya v2;
               uses its own account config, see scripts/setup_email.sh)
  smtp      -> direct SMTP using the digest's config/config.json + a password from env

Reads recipient / subject / from from the digest's config/config.json unless
overridden by flags. Body is read from --body-file (Markdown). Both transports
send the same text/plain + text/html multipart/alternative message.

--digest papers|headlines picks the digest (default papers: config at
$MORNING_PAPERS_HOME or the repo root). --home overrides the digest's home.
With either flag a relative --body-file is looked up under the home first.

Markdown rendering prefers the `markdown` package (tables, fenced code, nested
lists, footnotes) and falls back to a stdlib-only converter when it is absent,
so the script works three ways:
  uv run scripts/send_email.py ...      # uv provisions markdown per PEP 723
  python3 scripts/send_email.py ...     # uses markdown if installed
  python3 scripts/send_email.py ...     # bare stdlib fallback otherwise

Usage:
  send_email.py --body-file digests/2026-07-01.md
  send_email.py --body-file d.md --to a@b.com --subject "..." --transport himalaya
  send_email.py --body-file d.md --dry-run
  send_email.py --digest headlines --body-file digests/2026-07-01.md --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digestkit import specs  # noqa: E402
from digestkit.mailer import (  # noqa: E402,F401  (re-exported for callers/tests)
    _inline,
    _md_to_html_basic,
    build_message,
    load_config,
    md_to_html,
    send_himalaya,
    send_smtp,
    run,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--to", default="")
    ap.add_argument("--from", dest="sender", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--transport", choices=["auto", "himalaya", "smtp"], default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--digest", choices=specs.names(), default=None, help="default: papers")
    ap.add_argument("--home", default=None, help="digest home (overrides the digest's default)")
    args = ap.parse_args(argv)
    args.resolve_home = bool(args.digest or args.home)
    return run(args, specs.get(args.digest or "papers"))


if __name__ == "__main__":
    sys.exit(main())
