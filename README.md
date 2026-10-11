# infra-job-tracker

Emails new Bay Area / US-remote platform, SRE, AI-infra, and ML training & inference roles
straight from company career boards (Greenhouse, Lever, Ashby, Workday, Amazon, Eightfold),
twice a day via GitHub Actions. `latest.md` always lists every currently open match.

## Setup

1. Create a Gmail app password: https://myaccount.google.com/apppasswords (needs 2-Step Verification).
2. Add repo secrets:
   ```sh
   gh secret set SMTP_USER       # your Gmail address
   gh secret set SMTP_PASSWORD   # the 16-char app password
   gh secret set EMAIL_TO        # optional; comma-separated, defaults to SMTP_USER
   ```
3. Check email works: `gh workflow run job-tracker -f mode=test-email`.
4. Trigger the first run: `gh workflow run job-tracker` — it emails a per-company summary.
   Later runs email only roles that weren't seen before.

## Tuning

- `config.toml` — title include/exclude regexes, locations, search terms for big-company boards.
- `companies.toml` — tracked companies. Find a new company's board with
  `python discover.py "Company Name"` and paste the printed entry.
- `python tracker.py --dry-run [--only "OpenAI,NVIDIA"]` — preview matches locally.
- `python -m unittest test_filters` — filter sanity checks.

Not covered (no public jobs API): Google, Meta, Apple, Microsoft, Tesla, Uber.
