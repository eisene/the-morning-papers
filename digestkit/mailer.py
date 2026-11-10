"""Email delivery for the Morning digests (logic behind scripts/send_email.py).

Two transports:
  himalaya  -> pipes the message into `himalaya message send` (himalaya v2;
               uses its own account config, see scripts/setup_email.sh)
  smtp      -> direct SMTP using the digest's config/config.json + a password from env

Markdown rendering prefers the `markdown` package (tables, fenced code, nested
lists, footnotes) and falls back to a stdlib-only converter when it is absent.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

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


def load_config(config_file: Path) -> dict:
    if config_file.exists():
        return json.loads(config_file.read_text())
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


def build_message(to: str, sender: str, subject: str, body_md: str, html: str) -> MIMEMultipart:
    """RFC 5322 multipart/alternative (plain Markdown + rendered HTML)."""
    msg = MIMEMultipart("alternative")
    if sender:
        msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def send_himalaya(to: str, sender: str, subject: str, body_md: str, html: str, dry: bool) -> int:
    # himalaya v2: `message send` takes a raw RFC 5322 message on stdin and
    # routes it through the account's SMTP config. (v1's `template send` + MML
    # no longer exists.) No `--save`: Gmail files SMTP-sent mail into Sent
    # itself, and a save that fails AFTER delivery would exit non-zero and
    # invite a retry that re-sends the email.
    if not sender:
        print("ERROR: himalaya needs a From address (config set email.from ...)", file=sys.stderr)
        return 2
    raw = build_message(to, sender, subject, body_md, html).as_string()
    if dry:
        print("[dry-run] himalaya message send <<<\n" + raw[:800] + "\n...")
        return 0
    proc = subprocess.run(
        ["himalaya", "message", "send"], input=raw, text=True,
        capture_output=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode == 0:
        print(f"sent via himalaya to {to}")
    return proc.returncode


def send_smtp(cfg: dict, to: str, sender: str, subject: str, body_md: str, html: str, dry: bool,
              default_password_env: str = "MORNING_PAPERS_SMTP_PASSWORD") -> int:
    s = cfg.get("smtp", {})
    host, port = s.get("host"), int(s.get("port", 587))
    user = s.get("username") or sender
    pw = os.environ.get(s.get("password_env", default_password_env), "")
    if not host and not dry:
        print("ERROR: smtp.host not configured (config set smtp.host ...)", file=sys.stderr)
        return 3
    msg = build_message(to, sender or user, subject, body_md, html)
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
        rcpts = [a.strip() for a in to.split(",") if a.strip()]
        server.sendmail(msg["From"], rcpts, msg.as_string())
    print(f"sent via smtp to {to}")
    return 0


def run(args, spec) -> int:
    """Send (or --dry-run) the digest described by parsed CLI args for `spec`."""
    home = spec.home(getattr(args, "home", None))
    cfg = load_config(home / "config" / "config.json")
    em = cfg.get("email", {})
    to = args.to or em.get("to", "")
    sender = args.sender or em.get("from", "")
    subject = args.subject or em.get("subject_template", spec.subject_template)
    subject = subject.replace("{date}", dt.date.today().isoformat())
    transport = args.transport or em.get("transport", "auto")

    if not to:
        print("ERROR: no recipient (config set email.to ... or --to)", file=sys.stderr)
        return 2
    body = Path(args.body_file)
    if getattr(args, "resolve_home", False) and not body.is_absolute() and (home / body).exists():
        body = home / body
    body_md = body.read_text()
    html = md_to_html(body_md)

    if transport == "auto":
        transport = "himalaya" if shutil.which("himalaya") else "smtp"

    if transport == "himalaya":
        return send_himalaya(to, sender, subject, body_md, html, args.dry_run)
    return send_smtp(cfg, to, sender, subject, body_md, html, args.dry_run,
                     default_password_env=spec.smtp_password_env)
