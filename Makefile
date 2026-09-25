.PHONY: test init status dry-run setup-email

# Run the end-to-end test suite (isolated temp home; never touches repo state).
test:
	python3 tests/test_papers.py

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

# Interactive: install himalaya v2, store a Gmail app password, write the
# himalaya config, verify login, optionally send a test email.
setup-email:
	MORNING_PAPERS_HOME=$(CURDIR) bash scripts/setup_email.sh
