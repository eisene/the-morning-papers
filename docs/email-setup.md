# Email setup: where the Gmail app password lives

The Morning Papers sends its digest through [himalaya](https://github.com/pimalaya/himalaya)
v2 and Gmail. Run the guided setup yourself in a terminal:

```bash
make setup-email        # = bash scripts/setup_email.sh
```

It installs himalaya v2 if needed, asks for your Gmail details, stores a Gmail
**app password**, writes `~/.config/himalaya/config.toml`, checks the login,
updates `config/config.json`, and offers to send a test email. It asks before
each step that changes anything.

Never paste the app password into a chat with an agent. The script reads it
with hidden input.

## Before you start: a Gmail app password

1. Turn on 2-Step Verification for your Google account (app passwords require it).
2. Go to https://myaccount.google.com/apppasswords and create one named, say,
   "morning-papers". Google shows a 16-character code once.
3. Paste it when the script asks. Spaces are fine.

An app password only grants mail access (it can't change your Google account),
and you can revoke it on its own at the same page without touching your main
password.

## Choosing where to store it

The digest job runs unattended at a fixed time, so it has to read the password
with nobody at the keyboard. That means **any program running as your user can
read it too**, whichever option you pick. The options differ in whether the
password is encrypted at rest, and whether the job keeps working after a reboot.

| Option | Platform | Encrypted at rest | Works unattended after reboot | Install |
|---|---|---|---|---|
| **file** | any | no | yes | nothing |
| **keychain** | macOS | yes | yes, while you're logged in | nothing (built in) |
| **keyring** | Linux desktop | yes | only after you log in to the desktop | `libsecret-tools` + `gnome-keyring` (or KWallet) |

### Which should I pick?

- **macOS:** `keychain`. The login keychain unlocks when you log in, so a job
  running in your session can read it.
- **Linux desktop or laptop** that you log in to: `keyring` is a reasonable
  upgrade over the file.
- **Headless Linux** (Raspberry Pi, server, VPS): `file`. The Secret Service
  keyring is built for desktop sessions: after a reboot it stays locked until
  you log in, so the morning job fails. You can work around that with an
  empty-password keyring, but then it protects no more than the file. This is
  the same approach server tools like msmtp and `~/.netrc` use.

The script recommends one based on your OS and whether a desktop session is
detected. You can override it.

### What each option does

- **file:** writes `~/.config/himalaya/gmail-app-password` with mode 600 inside
  a mode-700 directory. himalaya reads it with `cat`.
- **keychain:** `security add-generic-password -s morning-papers-gmail -a <you>`.
  macOS prompts for the password itself, so it never appears in the process
  list. himalaya reads it with `security find-generic-password ... -w`.
- **keyring:** `secret-tool store service morning-papers-gmail user <you>`.
  himalaya reads it with `secret-tool lookup ...`.

### If you worry about the disk being stolen

On a headless box, a keyring can't really help: the key that unlocks it
unattended has to live on the same disk. The real fix is full-disk encryption,
which needs a passphrase at boot. Otherwise, rely on the app password being
narrow and revocable.

## Changing your mind later

Rerun `make setup-email` and pick a different option. It rewrites the himalaya
config to use the new store and offers to delete the old password file.

To check the setup at any time (read-only):

```bash
himalaya account check
```

Look for `FAIL` in the output. The command exits 0 even when a login fails.

## Troubleshooting

- **`Username and Password not accepted`:** the app password is wrong or was
  revoked, or 2-Step Verification is off. Rerun the setup and don't keep the
  stored password.
- **keyring: `Cannot autolaunch D-Bus` / `No such secret collection`:** no
  unlocked keyring is available (common over SSH). Log in to the desktop, or use
  `file`.
- **More detail:** `RUST_LOG=debug himalaya account check`.
