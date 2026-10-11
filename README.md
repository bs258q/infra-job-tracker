# infra-job-tracker

Tracks jobs straight from company career boards (Greenhouse, Lever, Ashby, Workday, Amazon, Eightfold)
and remote job boards (Himalayas, Remotive). Each search is a profile:

- `infra` — Bay Area / US-remote platform, SRE, AI-infra, and ML training & inference roles.
- `salesforce` — Salesforce developer, admin, and architect roles anywhere in the US, remote or hybrid.

Twice a day GitHub Actions runs every profile, emails the new roles, and redeploys a dashboard on Vercel.

## Dashboard (`web/`)

Switch between profiles in the header (`?p=salesforce` links straight to one). Search and filter by
role type, workplace (remote / hybrid), location, level, salary, company, and posted window
(24h / 7d / 30d); "new since last visit" highlighting; a personal pipeline (saved → applied →
interviewing → offer) with notes, stored in the browser per profile with export/import; hiring-trend charts.

Local preview: `python tracker.py --profile salesforce --no-email` (writes `web/public/data/salesforce`),
then `cd web && npm run dev`.

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
3. `gh workflow run job-tracker` (add `-f profile=salesforce` to run one profile)

## Tuning

- `profiles/<id>.toml` — one per search: title include / require / exclude regexes, locations
  (a Bay Area list, or `mode = "us"` plus allowed `workplaces`), search terms for big boards,
  and the dashboard's role-type and region buckets. Add a file to add a search; the workflow
  and dashboard pick it up.
- `companies/*.toml` — tracked companies; a profile lists which files it uses. Find a new company's
  board with `python discover.py "Company Name"` and paste the printed entry.
- `python tracker.py --profile salesforce --dry-run [--only "Himalayas (remote board)"]` — preview matches.
- `python -m unittest test_filters` — filter, location, and salary-parsing checks.

Not covered (no public jobs API): Google, Meta, Apple, Microsoft, Tesla, Uber, and most large
consultancies (Accenture, Deloitte), though their remote Salesforce roles often show up via Himalayas.
