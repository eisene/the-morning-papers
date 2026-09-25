#!/usr/bin/env bash
# Interactive setup for Morning Papers email delivery via himalaya v2 + Gmail.
#
#   make setup-email          (or: bash scripts/setup_email.sh)
#
# What it does, asking before each step that changes anything:
#   1. Installs himalaya v2 to ~/.local/bin if it is missing (or is v1).
#   2. Asks where to keep the Gmail app password: a mode-600 file (works
#      anywhere, incl. headless), macOS Keychain, or the Linux Secret Service
#      keyring (secret-tool). Never echoed, never in history or this repo.
#   3. Writes the himalaya account config (~/.config/himalaya/config.toml).
#   4. Verifies the IMAP + SMTP login with `himalaya account check`.
#   5. Sets email.from / email.to / email.transport=himalaya in config.json.
#   6. Optionally sends a one-line test email.
#
# Run it yourself in a terminal: it is interactive, and the password prompt
# must never go through an agent/chat.
set -euo pipefail

ROOT="${MORNING_PAPERS_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
HIMALAYA_VERSION="v2.1.0"
HCFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/himalaya"
HCFG="$HCFG_DIR/config.toml"
PWFILE="$HCFG_DIR/gmail-app-password"
BIN_DIR="$HOME/.local/bin"
ACCOUNT="gmail"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
ask()  { local q=$1 def=${2:-} a; read -rp "    $q${def:+ [$def]}: " a; printf '%s' "${a:-$def}"; }
yes()  { local a; read -rp "    $1 [Y/n]: " a; [[ -z $a || $a =~ ^[Yy] ]]; }
cfg()  { MORNING_PAPERS_HOME="$ROOT" python3 "$ROOT/scripts/papers.py" config "$@"; }
cfg_get() { cfg get "$1" | sed -n 's/.*": "\(.*\)".*/\1/p'; }

[[ -t 0 ]] || die "run this in an interactive terminal (it prompts for a password)."

# --- 1. himalaya v2 ---------------------------------------------------------
say "1/7  himalaya CLI"
need_install=1
if command -v himalaya >/dev/null; then
  ver=$(himalaya --version | head -1)
  if [[ $ver =~ himalaya\ v2\. ]]; then need_install=0; info "found: $ver"
  else info "found $ver, but this project needs himalaya v2."; fi
fi
if (( need_install )); then
  case "$(uname -s)-$(uname -m)" in
    Linux-aarch64|Linux-arm64) asset=aarch64-linux ;;
    Linux-x86_64)  asset=x86_64-linux ;;
    Linux-armv7l)  asset=armv7l-linux ;;
    Linux-armv6l)  asset=armv6l-linux ;;
    Darwin-arm64)  asset=aarch64-darwin ;;
    Darwin-x86_64) asset=x86_64-darwin ;;
    *) die "no prebuilt himalaya for $(uname -sm); see https://github.com/pimalaya/himalaya" ;;
  esac
  url="https://github.com/pimalaya/himalaya/releases/download/$HIMALAYA_VERSION/himalaya.$asset.tgz"
  yes "Install himalaya $HIMALAYA_VERSION to $BIN_DIR?" || die "himalaya v2 is required."
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "$url" -o "$tmp/h.tgz" || die "download failed: $url"
  tar xzf "$tmp/h.tgz" -C "$tmp" himalaya
  mkdir -p "$BIN_DIR"; install -m 755 "$tmp/himalaya" "$BIN_DIR/himalaya"
  export PATH="$BIN_DIR:$PATH"
  info "installed: $(himalaya --version | head -1)"
  command -v himalaya | grep -q "^$BIN_DIR" || info "note: add $BIN_DIR to your PATH."
fi

# --- 2. account details + app password --------------------------------------
say "2/7  Gmail account"
EMAIL=$(ask "Gmail address to send from" "$(cfg_get email.from || true)")
[[ $EMAIL == *@* ]] || die "that doesn't look like an email address."
NAME=$(ask "Display name on outgoing mail" "$(git config --global user.name 2>/dev/null || true)")
TO=$(ask "Deliver digests to" "$(cfg_get email.to || true)")
TO=${TO:-$EMAIL}

mkdir -p "$HCFG_DIR"; chmod 700 "$HCFG_DIR"

# --- 3. where the app password lives ----------------------------------------
say "3/7  Where to store the Gmail app password"
OS=$(uname -s)
HEADLESS=1; [[ -n ${DISPLAY:-}${WAYLAND_DISPLAY:-} ]] && HEADLESS=0
SVC="morning-papers-gmail"
if [[ $OS == Darwin ]]; then ALT=keychain; REC=keychain
else ALT=keyring; REC=file
  (( HEADLESS == 0 )) && command -v secret-tool >/dev/null && REC=keyring
fi
cat <<'EOT'
    The daily job runs unattended, so it has to read the password with nobody
    at the keyboard. Anything that can do that can also be read by other
    programs running as you, whichever option you pick. The differences are
    encryption at rest and whether it keeps working after a reboot.
    (Details: docs/email-setup.md)

      file      A file only your user can read
                (~/.config/himalaya/gmail-app-password, mode 600). Works
                everywhere, including headless servers and after reboots.
                Not encrypted at rest.
EOT
if [[ $OS == Darwin ]]; then cat <<'EOT'
      keychain  macOS Keychain. Encrypted at rest and unlocked while you are
                logged in to the Mac. The best choice on macOS.
EOT
else cat <<'EOT'
      keyring   Linux Secret Service (GNOME Keyring / KWallet) via secret-tool.
                Encrypted at rest, but locked until you log in to a desktop
                session. On a headless machine the morning job fails after a
                reboot until someone logs in. Good on a Linux desktop/laptop.
EOT
fi
cat <<'EOT'

    Either way, a Gmail app password only grants mail access and can be
    revoked on its own at https://myaccount.google.com/apppasswords.
EOT
while :; do
  STORE=$(ask "Store it in (file/$ALT)" "$REC")
  [[ $STORE == file || $STORE == "$ALT" ]] && break
  info "please type 'file' or '$ALT'."
done

if [[ $STORE == keyring ]]; then
  if ! command -v secret-tool >/dev/null; then
    info "secret-tool is not installed. Install it plus a keyring daemon, e.g.:"
    info "  Debian/Ubuntu/Raspberry Pi OS: sudo apt install libsecret-tools gnome-keyring"
    info "  Fedora: sudo dnf install libsecret gnome-keyring"
    info "then rerun this script."
    yes "Use the file option for now instead?" && STORE=file || exit 1
  else
    probe=$(secret-tool lookup service "$SVC-probe" 2>&1 >/dev/null || true)
    if [[ -n $probe ]]; then
      info "secret-tool can't reach an unlocked keyring: $probe"
      info "Log in to a desktop session (or start/unlock gnome-keyring) and rerun."
      yes "Use the file option for now instead?" && STORE=file || exit 1
    elif (( HEADLESS )); then
      info "warning: no desktop session detected. After a reboot the keyring stays"
      info "locked until you log in, and the morning job will fail until then."
      yes "Use the keyring anyway?" || STORE=file
    fi
  fi
fi

case $STORE in
  file)     PW_CMD="cat $PWFILE" ;;
  keychain) PW_CMD="security find-generic-password -a $EMAIL -s $SVC -w" ;;
  keyring)  PW_CMD="secret-tool lookup service $SVC user $EMAIL" ;;
esac

if [[ -n $(bash -c "$PW_CMD" 2>/dev/null) ]] && yes "An app password is already stored ($STORE). Keep it?"; then
  info "keeping the stored password"
else
  info "Gmail needs an *app password* (not your normal password). It requires"
  info "2-Step Verification. Create one (name it e.g. \"morning-papers\") at:"
  info "    https://myaccount.google.com/apppasswords"
  if [[ $STORE == keychain ]]; then
    # Let `security` prompt itself so the password never appears in argv (ps).
    info "macOS will prompt twice. Paste the 16 characters WITHOUT spaces."
    security add-generic-password -U -a "$EMAIL" -s "$SVC" \
      -l "Morning Papers Gmail app password" -w
  else
    info "Paste the 16-character code below; spaces are fine. Nothing is echoed."
    read -rsp "    App password: " pw; echo
    pw=${pw//[[:space:]]/}
    [[ ${#pw} -eq 16 ]] || info "warning: expected 16 characters, got ${#pw}."
    if [[ $STORE == file ]]; then
      ( umask 077; printf '%s' "$pw" > "$PWFILE" )
    else
      printf '%s' "$pw" | secret-tool store --label="Morning Papers Gmail app password" \
        service "$SVC" user "$EMAIL"
    fi
    unset pw
  fi
  [[ -n $(bash -c "$PW_CMD" 2>/dev/null) ]] || die "could not read the password back from $STORE."
  info "stored in $STORE"
fi
if [[ $STORE != file && -e $PWFILE ]] && yes "Delete the old password file $PWFILE?"; then
  rm -f "$PWFILE"
fi

# --- 3. himalaya config -----------------------------------------------------
say "4/7  himalaya config ($HCFG)"
write_cfg=1
if [[ -e $HCFG ]]; then
  if grep -q "^\[accounts\.$ACCOUNT\]" "$HCFG"; then
    yes "$HCFG already has an [accounts.$ACCOUNT] section. Replace the whole file (backup kept)?" || write_cfg=0
  else
    yes "$HCFG exists. Replace it (backup kept)?" || write_cfg=0
  fi
  (( write_cfg )) && cp -p "$HCFG" "$HCFG.bak.$(date +%Y%m%d%H%M%S)" && info "backed up old config"
fi
if (( write_cfg )); then
  ( umask 077; cat > "$HCFG" <<EOF
# Written by the-morning-papers scripts/setup_email.sh (himalaya v2 syntax).
# The password is fetched by the command below ($STORE); it is never stored here.

[accounts.$ACCOUNT]
default = true
email = "$EMAIL"
display-name = "$NAME"

# IMAP (reading): bare host = imaps:// on 993 with implicit TLS.
imap.server = "imap.gmail.com"
imap.sasl.plain.username = "$EMAIL"
imap.sasl.plain.password.command = "$PW_CMD"

# SMTP (sending): implicit TLS on 465.
smtp.server = "smtps://smtp.gmail.com:465"
smtp.sasl.plain.username = "$EMAIL"
smtp.sasl.plain.password.command = "$PW_CMD"

# Gmail's special folders. v2 syntax is mailbox.alias.* (v1 used folder.aliases.*).
mailbox.alias.inbox = "INBOX"
mailbox.alias.sent = "[Gmail]/Sent Mail"
mailbox.alias.drafts = "[Gmail]/Drafts"
mailbox.alias.trash = "[Gmail]/Trash"
EOF
  )
  info "wrote $HCFG"
fi

# --- 4. verify login --------------------------------------------------------
say "5/7  Checking IMAP + SMTP login"
# `himalaya account check` exits 0 even when a backend fails, so parse it.
check_out=$(himalaya account check 2>&1) || true
printf '%s\n' "$check_out" | sed 's/^/    /'
if grep -q ': OK' <<<"$check_out" && ! grep -q 'FAIL' <<<"$check_out"; then
  info "login OK"
else
  info "Login failed. Common causes: wrong/revoked app password (rerun this"
  info "script and choose not to keep it), 2-Step Verification off, or IMAP"
  info "disabled in Gmail settings. Debug: RUST_LOG=debug himalaya account check"
  exit 1
fi

# --- 5. project config ------------------------------------------------------
say "6/7  Updating config/config.json"
cfg set email.from "$EMAIL" >/dev/null
cfg set email.to "$TO" >/dev/null
cfg set email.transport himalaya >/dev/null
info "email.from=$EMAIL  email.to=$TO  email.transport=himalaya"

# --- 6. test email ----------------------------------------------------------
say "7/7  Test email"
if yes "Send a one-line test email to $TO now?"; then
  printf 'From: %s <%s>\nTo: %s\nSubject: The Morning Papers: test email\nDate: %s\n\nIf you can read this, himalaya delivery works.\n' \
    "$NAME" "$EMAIL" "$TO" "$(date -R)" | himalaya message send
  info "sent. Check $TO (and spam)."
fi

say "Done. Preview a digest without sending:  make dry-run"
