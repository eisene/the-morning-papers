#!/usr/bin/env python3
"""Send a Morning Papers digest email.

Two transports:
  himalaya  -> shells out to the `himalaya` CLI (uses its own account config)
  smtp      -> direct SMTP using config/config.json + a password from env

Reads recipient / subject / from from config/config.json unless overridden by
flags. Body is read from --body-file (Markdown). For SMTP a text/plain +
text/html (Markdown lightly converted) multipart is sent.

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


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def md_to_html(md: str) -> str:
    """Minimal, dependency-free Markdown -> HTML (headings, bold, links, lists)."""
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
    body = "\n".join(html_lines)
    return (
        "<html><body style=\"font-family:-apple-system,Segoe UI,Helvetica,Arial,"
        "sans-serif;max-width:720px;margin:auto;line-height:1.5;color:#1a1a1a\">"
        f"{body}</body></html>"
    )


def _inline(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def send_himalaya(to: str, sender: str, subject: str, body_md: str, html: str, dry: bool) -> int:
    # Build a MIME message and pipe it to `himalaya template send`.
    msg = MIMEMultipart("alternative")
    msg["To"] = to
    if sender:
        msg["From"] = sender
    msg["Subject"] = subject
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    raw = msg.as_string()
    if dry:
        print("[dry-run] himalaya template send <<<\n" + raw[:800] + "\n...")
        return 0
    proc = subprocess.run(
        ["himalaya", "template", "send"], input=raw, text=True,
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
