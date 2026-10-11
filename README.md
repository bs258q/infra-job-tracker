# infra-job-tracker

Tracks Bay Area / US-remote platform, SRE, AI-infra, and ML training & inference roles
straight from company career boards (Greenhouse, Lever, Ashby, Workday, Amazon, Eightfold).
Twice a day GitHub Actions fetches roles, emails the new ones, and redeploys a dashboard on Vercel.

## Dashboard (`web/`)

Search and filter by role type, location, level, salary, company, and posted window (24h / 7d / 30d);
"new since last visit" highlighting; a personal pipeline (saved → applied → interviewing → offer)
with notes, stored in the browser with export/import; hiring-trend charts.

Local preview: `python tracker.py --no-email` (writes `web/public/data`), then `cd web && npm run dev`.

## Setup

1. Email — create a Gmail app password at https://myaccount.google.com/apppasswords, then:
   ```sh
   gh secret set SMTP_USER       # your Gmail address
   gh secret set SMTP_PASSWORD   # the 16-letter app password
   gh workflow run job-tracker -f mode=test-email
   ```
2. Dashboard — one-time Vercel link from `web/`:
   ```sh
   npx vercel login && npx vercel link --yes
   gh secret set VERCEL_TOKEN        # https://vercel.com/account/tokens
   gh secret set VERCEL_ORG_ID      --body "$(jq -r .orgId .vercel/project.json)"
   gh secret set VERCEL_PROJECT_ID  --body "$(jq -r .projectId .vercel/project.json)"
   gh variable set DASHBOARD_URL     # e.g. https://infra-roles.vercel.app (linked from emails)
   ```
3. `gh workflow run job-tracker`

## Tuning

- `config.toml` — title include/exclude regexes, locations, search terms for big-company boards.
- `companies.toml` — tracked companies. Find a new company's board with
  `python discover.py "Company Name"` and paste the printed entry.
- `dashboard.py` — role-type, level, and area buckets used by the dashboard filters.
- `python tracker.py --dry-run [--only "OpenAI,NVIDIA"]` — preview matches.
- `python -m unittest test_filters` — filter and salary-parsing checks.

Not covered (no public jobs API): Google, Meta, Apple, Microsoft, Tesla, Uber.
