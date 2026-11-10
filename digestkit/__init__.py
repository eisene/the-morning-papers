"""digestkit: shared core for the Morning digests.

One package, several daily digests. Each digest is described by a
`DigestSpec` (digestkit.specs) and gets its own home directory with
`config/`, `state/` and `digests/`. The CLI (`digestkit.core`), the Discord
renderer (`digestkit.discord`) and the email sender (`digestkit.mailer`) are
shared; `scripts/papers.py` and `scripts/headlines.py` are thin entry points.

Stdlib only (the email sender optionally uses `markdown`).
"""

__all__ = ["core", "discord", "mailer", "specs", "store", "urls", "items"]
