# infra-job-tracker

Tracks jobs straight from company career boards and multi-employer job boards, merged into one list of
unique roles. Each search is a profile:

- `infra` — Bay Area / US-remote platform, SRE, AI-infra, and ML training & inference roles.
- `salesforce` — Salesforce developer, admin, and architect roles anywhere in the US, remote or hybrid.

Twice a day GitHub Actions runs every profile, emails the new roles, and redeploys a dashboard on Vercel.

## Sources

| | Sites | How |
|---|---|---|
| Company boards | Greenhouse, Lever, Ashby, Workable, Gem, Rippling, SmartRecruiters, Recruitee, Breezy, Workday, Oracle Recruiting Cloud, Eightfold, Amazon, YC company pages | each company's own public jobs API (`companies/tech.toml`, `companies/salesforce.toml`, `companies/found/`) |
| Job boards | Himalayas, Remotive, Remote OK, Jobicy, We Work Remotely, Working Nomads, Hacker News "Who is hiring" | public APIs / feeds, shared by every profile (`companies/boards.toml`) |
| Linked, not ingested | LinkedIn, Indeed, Glassdoor, Dice, Wellfound, Built In, Google Jobs, hiring.cafe, ainfra.dev, Work at a Startup | no public jobs feed and scraping is against their terms; the dashboard's "Search elsewhere" menu opens the profile's saved searches there (`[elsewhere]` in the profile) |

Those sites mostly re-list roles from the company boards above, so tracking the companies directly covers
them; new companies are found weekly (see below). Not covered at all: Google, Meta, Apple, Microsoft,
Tesla, Uber (no public jobs API); their roles sometimes show up via the job boards.

A role is one company + title, however many places it's posted: company names are normalized ("Acme AI,
Inc." = "acme"), titles too ("Sr. SWE, Infra - San Francisco, CA" = "senior software engineer infrastructure"),
postings of the same role in several cities or on several boards collapse into one row, a reposted role is
not alerted again, a job board's copy of a role is dropped when the company's own board is tracked, and a
board listed in two company files is fetched once. Workday boards are listed in full within the profile's
location facet (keyword search past Workday's 2,000-result cap or when the facet is nationwide), and
Amazon lists every posting in the profile's state.

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
4. Company discovery (optional) — an API key from https://platform.parallel.ai (without it the weekly
   run still checks the YC directory and rechecks earlier finds):
   ```sh
   gh secret set PARALLEL_API_KEY
   gh workflow run find-companies
   ```

## Finding new companies

Every Monday `find-companies` runs a [Parallel FindAll](https://docs.parallel.ai/findall-api/findall-quickstart)
search per profile (the `[discovery]` section: a plain-English objective plus match conditions), excluding
every company already tracked or seen before. It also checks, for free, every YC company the YC directory
marks as hiring whose tags match the profile's `yc_tags`. For each company it finds the job board — from the
careers URL, a careers page that links to one, the company's YC jobs page, or a guessed Greenhouse / Lever /
Ashby / Workable / Gem / Rippling / SmartRecruiters / Recruitee / Breezy slug — and keeps it only if the board has roles passing the profile's filters. New
companies are committed straight to main as `companies/found/<profile>-<date>.toml` (after a TOML validity
check), tracked from the next run, and emailed to you. To drop one, delete its entry from that file.

`state/<profile>/discovery.json` logs every company checked, so none is paid for twice; ones with no
supported board or no matching roles yet are rechecked for free (every 2–4 weeks). Locally:
`python find_companies.py --profile infra --preview` (cheap 10-candidate preview, writes nothing) to tune the
objective, `--recheck-only` to skip Parallel, and `--names "Nscale" "IREN=https://iren.com/careers"` to add
specific companies (e.g. ones another job site lists that we don't) without a Parallel call.

## Tuning

- `profiles/<id>.toml` — one per search: title include / require / exclude regexes, locations
  (a Bay Area list, or `mode = "us"` plus allowed `workplaces`), search terms for big boards,
  and the dashboard's role-type and region buckets. Add a file to add a search; the workflow
  and dashboard pick it up.
- `companies/*.toml` — tracked companies; a profile lists which files (or globs) it uses. Find a new
  company's board with `python discover.py "Company Name"` or `python discover.py <careers URL>` (the
  only way to find a Workday or Oracle board) and paste the printed entry.
- `python tracker.py --profile salesforce --dry-run [--only "Himalayas (remote board)"]` — preview matches.
- `python -m unittest test_filters` — filter, location, and salary-parsing checks.