.PHONY: test test-papers test-headlines init status dry-run discord-preview setup-email \
	init-headlines status-headlines dry-run-headlines discord-preview-headlines

H := $(CURDIR)/headlines

# Run every test suite (isolated temp homes; never touches repo state).
test:
	python3 tests/test_papers.py
	python3 tests/test_core.py
	python3 tests/test_urls.py
	python3 tests/test_crossdedup.py
	python3 tests/test_backcompat.py

test-papers:
	python3 tests/test_papers.py
	python3 tests/test_backcompat.py

test-headlines:
	python3 tests/test_core.py
	python3 tests/test_urls.py
	python3 tests/test_crossdedup.py

# ---- The Morning Papers (home = repo root) --------------------------------

# Scaffold config + state files.
init:
	MORNING_PAPERS_HOME=$(CURDIR) python3 scripts/papers.py init

# One-glance summary.
status:
	MORNING_PAPERS_HOME=$(CURDIR) python3 scripts/papers.py status

# Preview today's digest email without sending.
dry-run:
	MORNING_PAPERS_HOME=$(CURDIR) uv run scripts/send_email.py \
		--body-file digests/$$(date +%F).md --dry-run

# Preview today's digest as it would be posted to Discord.
discord-preview:
	python3 scripts/render_discord.py --body-file digests/$$(date +%F).md

# Interactive: install himalaya v2, store a Gmail app password, write the
# himalaya config, verify login, optionally send a test email.
setup-email:
	MORNING_PAPERS_HOME=$(CURDIR) bash scripts/setup_email.sh

# ---- The Morning Headlines (home = headlines/) ----------------------------

init-headlines:
	MORNING_HEADLINES_HOME=$(H) python3 scripts/headlines.py init

status-headlines:
	MORNING_HEADLINES_HOME=$(H) python3 scripts/headlines.py status

# Preview today's headlines email without sending (same himalaya account).
dry-run-headlines:
	MORNING_HEADLINES_HOME=$(H) uv run scripts/send_email.py --digest headlines \
		--body-file $(H)/digests/$$(date +%F).md --dry-run

# Today's headlines as they would be posted to Discord (falls back to the sample).
discord-preview-headlines:
	@f=$(H)/digests/$$(date +%F).md; [ -f $$f ] || f=$(H)/digests/sample.md; \
	MORNING_HEADLINES_HOME=$(H) python3 scripts/render_discord.py --digest headlines --body-file $$f
