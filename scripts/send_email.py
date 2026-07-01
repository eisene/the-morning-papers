#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["markdown>=3.5"]
# ///
"""Send a Morning Papers digest email.

Two transports:
  himalaya  -> shells out to the `himalaya` CLI (uses its own account config)
  smtp      -> direct SMTP using config/config.json + a password from env

Reads recipient / subject / from from config/config.json unless overridden by
flags. Body is read from --body-file (Markdown). For SMTP a text/plain +
text/html multipart is sent.

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
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import smtplib
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(os.environ.get("MORNING_PAPERS_HOME", Path(__file__).resolve().parent.parent))
CONFIG_FILE = ROOT / "config" / "config.json"

_BODY_STYLE = (
    "font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
    "max-width:720px;margin:auto;line-height:1.5;color:#1a1a1a"
)
_TABLE_CSS = (
    "<style>table{border-collapse:collapse;margin:8px 0}"
    "th,td{border:1px solid #ddd;padding:6px 10px;text-align:left}"
    "th{background:#f5f5f5}code{background:#f2f2f2;padding:1px 4px;border-radius:3px}"
    "pre{background:#f6f8fa;padding:12px;border-radius:6px;overflow:auto}"
    "blockquote{border-left:3px solid #ddd;margin:8px 0;padding:2px 12px;color:#555}</style>"
)


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def md_to_html(md: str) -> str:
    """Markdown -> styled HTML. Uses the `markdown` package when available."""
    try:
        import markdown  # provisioned by uv (PEP 723) or system install
        inner = markdown.markdown(
            md, extensions=["extra", "sane_lists", "admonition"]
        )
    except ImportError:
        inner = _md_to_html_basic(md)
    return (
        f"<html><head>{_TABLE_CSS}</head>"
        f'<body style="{_BODY_STYLE}">{inner}</body></html>'
    )


def _md_to_html_basic(md: str) -> str:
    """Stdlib-only fallback: headings, bold/em/code, links, unordered lists."""
    html_lines, in_ul = [], False
    for line in md.splitlines():
        raw = line.rstrip()
        h = re.match(r"^(#{1,6})\s+(.*)$", raw)
        if h:
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            lvl = len(h.group(1))
            html_lines.append(f"<h{lvl}>{_inline(h.group(2))}</h{lvl}>")
            continue
        li = re.match(r"^\s*[-*]\s+(.*)$", raw)
        if li:
            if not in_ul:
                html_lines.append("<ul>"); in_ul = True
            html_lines.append(f"<li>{_inline(li.group(1))}</li>")
            continue
        if in_ul:
            html_lines.append("</ul>"); in_ul = False
        if raw.strip() == "":
            html_lines.append("<br/>")
        else:
            html_lines.append(f"<p>{_inline(raw)}</p>")
    if in_ul:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def _inline(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def send_himalaya(to: str, sender: str, subject: str, body_md: str, html: str, dry: bool) -> int:
    # himalaya `template send` consumes MML (its own markup), NOT a pre-built
    # MIME message. Feeding raw multipart MIME makes himalaya wrap the whole
    # blob as one opaque "noname" attachment. So emit headers + an MML
    # alternative body; himalaya compiles it to proper MIME on send.
    headers = [f"To: {to}"]
    if sender:
        headers.append(f"From: {sender}")
    headers.append(f"Subject: {subject}")
    template = (
        "\n".join(headers)
        + "\n\n"
        + "<#multipart type=alternative>\n"
        + body_md.rstrip("\n") + "\n"
        + "<#part type=text/html>\n"
        + html + "\n"
        + "<#/multipart>\n"
    )
    if dry:
        print("[dry-run] himalaya template send <<<\n" + template)
        return 0
    proc = subprocess.run(
        ["himalaya", "template", "send"], input=template, text=True,
        capture_output=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


def send_smtp(cfg: dict, to: str, sender: str, subject: str, body_md: str, html: str, dry: bool) -> int:
    s = cfg.get("smtp", {})
    host, port = s.get("host"), int(s.get("port", 587))
    user = s.get("username") or sender
    pw = os.environ.get(s.get("password_env", "MORNING_PAPERS_SMTP_PASSWORD"), "")
    if not host and not dry:
        print("ERROR: smtp.host not configured (config set smtp.host ...)", file=sys.stderr)
        return 3
    msg = MIMEMultipart("alternative")
    msg["From"] = sender or user
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    if dry:
        print(f"[dry-run] SMTP {user}@{host}:{port} tls={s.get('use_tls')} -> {to}")
        print(msg.as_string()[:800] + "\n...")
        return 0
    if not pw:
        print(f"ERROR: no password in ${s.get('password_env')}", file=sys.stderr)
        return 3
    with smtplib.SMTP(host, port, timeout=30) as server:
        if s.get("use_tls", True):
            server.starttls()
        server.login(user, pw)
        server.sendmail(msg["From"], [to], msg.as_string())
    print(f"sent via smtp to {to}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--to", default="")
    ap.add_argument("--from", dest="sender", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--transport", choices=["auto", "himalaya", "smtp"], default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config()
    em = cfg.get("email", {})
    to = args.to or em.get("to", "")
    sender = args.sender or em.get("from", "")
    subject = args.subject or em.get("subject_template", "The Morning Papers — {date}")
    subject = subject.replace("{date}", dt.date.today().isoformat())
    transport = args.transport or em.get("transport", "auto")

    if not to:
        print("ERROR: no recipient (config set email.to ... or --to)", file=sys.stderr)
        return 2
    body_md = Path(args.body_file).read_text()
    html = md_to_html(body_md)

    if transport == "auto":
        has_himalaya = subprocess.run(["which", "himalaya"], capture_output=True).returncode == 0
        transport = "himalaya" if has_himalaya else "smtp"

    if transport == "himalaya":
        return send_himalaya(to, sender, subject, body_md, html, args.dry_run)
    return send_smtp(cfg, to, sender, subject, body_md, html, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
