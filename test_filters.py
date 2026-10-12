import tomllib
import unittest
from pathlib import Path

from tracker import Filters

PROFILES = Path(__file__).parent / "profiles"
CFG = tomllib.loads((PROFILES / "infra.toml").read_text())
SF_CFG = tomllib.loads((PROFILES / "salesforce.toml").read_text())


class TitleTests(unittest.TestCase):
    f = Filters(CFG)

    def test_keeps_target_roles(self):
        for t in [
            "Site Reliability Engineer, Inference Infrastructure",
            "Software Engineer, GPU Infrastructure - HPC",
            "Member of Technical Staff - Post-Training",
            "Senior Platform Engineer",
            "Staff Software Engineer, ML Platform",
            "Software Engineer, Model Serving",
            "Principal Engineer, Cluster Orchestration",
            "Production Engineer",
        ]:
            self.assertTrue(self.f.title_ok(t), t)

    def test_drops_noise(self):
        for t in [
            "Senior Software Engineer, iOS Platform",
            "Staff Platform Manager, AI Personalization",
            "Software Development Manager, SageMaker Training",
            "Senior ASIC Verification Engineer - GPU",
            "Infrastructure Engineering Intern",
            "Solutions Architect, Inference",
            "Senior Training Specialist",
            "Account Executive, Cloud Infrastructure",
        ]:
            self.assertFalse(self.f.title_ok(t), t)


class LocationTests(unittest.TestCase):
    f = Filters(CFG)

    def test_bay_area_and_us_remote(self):
        for loc in [
            "San Francisco, CA",
            "US, CA, Santa Clara",
            "Mountain View, California (HQ)",
            "Remote",
            "Remote - US",
            "US - Remote; New York City",
            "Remote, Canada; Remote, United States",
            "United States",
            "Los Gatos,California,United States of America",
        ]:
            self.assertTrue(self.f.location_ok(loc), loc)

    def test_rejects_elsewhere(self):
        for loc in ["New York, NY", "Seattle, Washington, USA", "London, UK (Remote)", "Remote - Canada", "Bengaluru, India"]:
            self.assertFalse(self.f.location_ok(loc), loc)


class SalesforceTests(unittest.TestCase):
    f = Filters(SF_CFG)

    def test_keeps_salesforce_roles(self):
        for t in [
            "Salesforce Developer",
            "Senior Salesforce Administrator",
            "Salesforce Technical Architect",
            "Sr. SFDC Engineer",
            "Lead Apex / LWC Developer",
            "Marketing Cloud Developer",
            "Salesforce CPQ Solution Architect",
            "Business Systems Engineer, Salesforce",
            "Salesforce Admin (Service Cloud)",
        ]:
            self.assertTrue(self.f.title_ok(t), t)

    def test_drops_non_platform_roles(self):
        for t in [
            "Account Executive, Salesforce Practice",
            "Software Engineer, Backend",
            "Salesforce QA Tester",
            "Salesforce Business Analyst",
            "Sales Development Representative",
            "Salesforce Developer Intern",
            "Senior Solutions Engineer, Salesforce Industries",
        ]:
            self.assertFalse(self.f.title_ok(t), t)

    def test_us_locations(self):
        for loc in [
            "Austin, TX", "Remote", "Remote - US", "Chicago", "US-NY-New York",
            "Toronto, ON; Atlanta, Georgia", "Albuquerque, New Mexico", "Remote, Texas",
            "Remote (United States, Canada)",
        ]:
            self.assertTrue(self.f.location_ok(loc), loc)
        for loc in ["Toronto, ON", "London, UK", "Remote - Canada", "Hyderabad, India", "Mexico City"]:
            self.assertFalse(self.f.location_ok(loc), loc)

    def test_workplaces(self):
        self.assertTrue(self.f.workplace_ok("remote"))
        self.assertTrue(self.f.workplace_ok("hybrid"))
        self.assertTrue(self.f.workplace_ok(""))
        self.assertFalse(self.f.workplace_ok("onsite"))

    def test_workplace_from_text(self):
        from ats import workplace_from_text

        self.assertEqual(workplace_from_text("Remote - US"), "remote")
        self.assertEqual(workplace_from_text("Austin, TX", "<p>This is a hybrid role, 3 days a week in the office.</p>"), "hybrid")
        self.assertEqual(workplace_from_text("Austin, TX", "We build hybrid cloud infrastructure."), "")
        self.assertEqual(workplace_from_text("Austin, TX", "This role is fully remote."), "remote")
        self.assertEqual(workplace_from_text("Austin, TX", "This is a hybrid technical and commercial role."), "")
        self.assertEqual(workplace_from_text("Austin, TX", "Location-based hybrid policy: in office 25% of the time"), "hybrid")
        self.assertEqual(workplace_from_text("Austin, TX", "This role is expected to be in office 5 days per week"), "onsite")


class WorkdayFacetTests(unittest.TestCase):
    facets = [
        {"facetParameter": "jobFamilyGroup", "values": [{"id": "j1", "descriptor": "Engineering", "count": 900}]},
        {"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locationCountry", "values": [
                {"id": "us", "descriptor": "United States of America", "count": 1100},
                {"id": "in", "descriptor": "India", "count": 700},
            ]},
            {"facetParameter": "locations", "values": [
                {"id": "sc", "descriptor": "US, CA, Santa Clara", "count": 600},
                {"id": "rm", "descriptor": "US, Remote", "count": 200},
                {"id": "au", "descriptor": "US, TX, Austin", "count": 400},
                {"id": "bl", "descriptor": "India, Bengaluru", "count": 700},
            ]},
            {"facetParameter": "locationHierarchy2", "values": [
                {"id": "r", "descriptor": "Remote", "count": 200},
                {"id": "o", "descriptor": "On-site", "count": 1600},
            ]},
        ]},
    ]

    def test_bay_area_uses_city_facet(self):
        from ats import workday_location_facet

        got = workday_location_facet(self.facets, Filters(CFG).location_ok)
        self.assertEqual({k: sorted(v) for k, v in got.items()}, {"locations": ["rm", "sc"]})

    def test_us_wide_uses_city_facet(self):
        from ats import workday_location_facet

        got = workday_location_facet(self.facets, Filters(SF_CFG).location_ok)
        self.assertEqual({k: sorted(v) for k, v in got.items()}, {"locations": ["au", "rm", "sc"]})

    def test_all_or_nothing(self):
        from ats import workday_location_facet

        us_only = [{"facetParameter": "locations", "values": [{"id": "sc", "descriptor": "Santa Clara, CA", "count": 5}]}]
        self.assertEqual(workday_location_facet(us_only, Filters(CFG).location_ok), {})
        self.assertIsNone(workday_location_facet(self.facets[:1], Filters(CFG).location_ok))


class DiscoverTests(unittest.TestCase):
    def test_boards_in_text(self):
        from discover import boards_in_text

        cases = {
            "https://job-boards.greenhouse.io/anthropic/jobs/123": {"ats": "greenhouse", "slug": "anthropic"},
            "https://boards.greenhouse.io/embed/job_board?for=figma": {"ats": "greenhouse", "slug": "figma"},
            "https://jobs.lever.co/zoox/abc-123": {"ats": "lever", "slug": "zoox"},
            "https://jobs.ashbyhq.com/magic.dev": {"ats": "ashby", "slug": "magic.dev"},
            "https://apply.workable.com/runware/": {"ats": "workable", "slug": "runware"},
            "https://jobs.gem.com/deep-infra/am9i": {"ats": "gem", "slug": "deep-infra"},
            "https://jobs.smartrecruiters.com/ServiceNow/744000154789179": {"ats": "smartrecruiters", "slug": "ServiceNow"},
            "https://ats.rippling.com/rippling/jobs/84d388b6": {"ats": "rippling", "slug": "rippling"},
            "https://bunq.recruitee.com/o/website-lead": {"ats": "recruitee", "slug": "bunq"},
            "https://acme.breezy.hr/p/123-engineer": {"ats": "breezy", "slug": "acme"},
            "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210769562": {
                "ats": "oracle", "host": "jpmc.fa.oraclecloud.com", "site": "CX_1001",
            },
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/x": {
                "ats": "workday", "host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia", "site": "NVIDIAExternalCareerSite",
            },
        }
        for url, want in cases.items():
            self.assertEqual(boards_in_text(url), [want], url)
        self.assertEqual(boards_in_text("https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/x/jobs"), [])
        self.assertEqual(boards_in_text("https://acme.com/careers"), [])
        self.assertEqual(boards_in_text("https://apply.workable.com/j/CE2C2FFAC2"), [])
        self.assertEqual(boards_in_text("https://www.recruitee.com/pricing https://www.breezy.hr"), [])

    def test_rippling_merges_locations(self):
        from unittest import mock

        import ats

        job = {"id": "j1", "name": "SRE", "url": "https://ats.rippling.com/acme/jobs/j1"}
        page = {"totalPages": 1, "items": [
            {**job, "locations": [{"name": "San Francisco, CA", "workplaceType": "HYBRID"}]},
            {**job, "locations": [{"name": "Remote (United States)", "workplaceType": "REMOTE"}]},
        ]}
        with mock.patch.object(ats, "_request", return_value=page):
            jobs = list(ats.rippling("Acme", slug="acme"))
        self.assertEqual([(j.location, j.workplace) for j in jobs], [("San Francisco, CA; Remote (United States)", "remote")])

    def test_hackernews_who_is_hiring(self):
        from unittest import mock

        import ats

        stories = {"hits": [{"objectID": "9", "title": "Ask HN: Who wants to be hired? (October 2026)"},
                            {"objectID": "1", "title": "Ask HN: Who is hiring? (October 2026)"}]}
        comments = {"hits": [
            {"objectID": "11", "parent_id": 1, "created_at": "2026-10-02T00:00:00Z",
             "comment_text": "Chronograph (chronograph.pe) | Platform Engineer | Full-Time | Remote (US) | $175,000 - $215,000<p>About us"},
            {"objectID": "12", "parent_id": 1, "created_at": "2026-10-02T00:00:00Z",
             "comment_text": "OneChronos | Engineering Manager, Data Platform (NYC, Hybrid) · SRE (Flexible/U.S. Remote) | Full-Time"},
            {"objectID": "13", "parent_id": 11, "comment_text": "Reply | Engineer | Remote"},
            {"objectID": "14", "parent_id": 1, "comment_text": "Location: Bangalore, India"},
        ]}
        with mock.patch.object(ats, "_request", side_effect=[stories, comments]):
            jobs = list(ats.hackernews("HN"))
        got = [(j.company, j.title, j.location, j.workplace, j.salary) for j in jobs]
        self.assertEqual(got, [
            ("Chronograph", "Platform Engineer", "Remote (US)", "remote", "$175,000 – $215,000"),
            ("OneChronos", "Engineering Manager, Data Platform (NYC, Hybrid)", "NYC, Hybrid", "hybrid", ""),
            ("OneChronos", "SRE (Flexible/U.S. Remote)", "Flexible/U.S. Remote", "remote", ""),
        ])
        self.assertEqual(jobs[0].url, "https://news.ycombinator.com/item?id=11")

    def test_same_board_loaded_once(self):
        import tempfile
        from unittest import mock

        import tracker

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(tracker, "ROOT", Path(tmp)):
            Path(tmp, "a.toml").write_text('[[company]]\nname = "Okta"\nats = "greenhouse"\nslug = "okta"\n')
            Path(tmp, "b.toml").write_text('[[company]]\nname = "Okta Inc"\nats = "greenhouse"\nslug = "okta"\n'
                                           '[[company]]\nname = "Twilio"\nats = "greenhouse"\nslug = "twilio"\n')
            names = [c["name"] for c in tracker.load_companies({"profile": {"companies": ["a.toml", "b.toml"]}})]
        self.assertEqual(names, ["Okta", "Twilio"])

    def test_elsewhere_links(self):
        import dashboard

        links = dashboard.elsewhere({"elsewhere": {
            "searches": [{"query": "salesforce developer", "remote": True},
                         {"query": "site reliability engineer", "location": "San Francisco Bay Area"}],
            "extra": [{"name": "ainfra.dev", "url": "https://ainfra.dev/jobs"}],
        }})
        self.assertEqual([g["label"] for g in links],
                         ["salesforce developer · Remote (US)", "site reliability engineer · San Francisco Bay Area", "More job sites"])
        remote = {l["name"]: l["url"] for l in links[0]["links"]}
        self.assertIn("f_WT=2", remote["LinkedIn"])
        self.assertEqual(remote["Wellfound"], "https://wellfound.com/role/r/salesforce-developer")
        local = {l["name"]: l["url"] for l in links[1]["links"]}
        self.assertIn("location=San+Francisco+Bay+Area", local["LinkedIn"])
        self.assertEqual(local["Wellfound"], "https://wellfound.com/role/l/site-reliability-engineer/san-francisco-bay-area")

    def test_workable_merges_locations(self):
        from unittest import mock

        import ats

        job = {"title": "Infra Engineer", "shortcode": "AB12", "telecommuting": True, "published_on": "2026-10-01"}
        data = {"jobs": [{**job, "locations": [{"city": "", "region": None, "country": "United States"}]},
                         {**job, "locations": [{"city": "Toronto", "region": "Ontario", "country": "Canada"}]}]}
        with mock.patch.object(ats, "_request", return_value=data):
            jobs = list(ats.workable("Acme", slug="acme"))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].location, "United States; Toronto, Ontario, Canada (Remote)")
        self.assertEqual(jobs[0].workplace, "remote")

    def test_toml_entry_escapes(self):
        from discover import toml_entry

        entry = tomllib.loads(toml_entry('Acme "AI"', {"ats": "ashby", "slug": "acme"}))["company"][0]
        self.assertEqual(entry, {"name": 'Acme "AI"', "ats": "ashby", "slug": "acme"})


class FindCompaniesTests(unittest.TestCase):
    def test_exclude_list(self):
        from find_companies import exclude_list

        tracked = [
            {"name": "Anthropic", "ats": "greenhouse", "slug": "anthropic"},
            {"name": "NVIDIA", "ats": "workday", "host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia", "site": "Ext"},
            {"name": "Himalayas (remote board)", "ats": "himalayas"},
        ]
        ledger = {"companies": {"acme": {"name": "Acme", "url": "https://acme.ai", "status": "no_board"}}}
        self.assertEqual(exclude_list(tracked, ledger), [
            {"name": "Anthropic", "url": "https://job-boards.greenhouse.io/anthropic"},
            {"name": "NVIDIA", "url": "https://nvidia.wd5.myworkdayjobs.com/Ext"},
            {"name": "Acme", "url": "https://acme.ai"},
        ])

    def test_record_from_candidate(self):
        from find_companies import record_from_candidate

        cand = {
            "name": " Acme Inference ", "url": "https://acme.ai", "match_status": "matched",
            "output": {
                "hiring_infra_engineers": {"value": "Hiring an SRE", "type": "match_condition", "is_matched": True},
                "careers_url": {"value": "https://jobs.ashbyhq.com/acme", "type": "enrichment"},
                "example_role": {"value": "Staff SRE, San Francisco", "type": "enrichment"},
            },
            "basis": [{"field": "hiring_infra_engineers", "citations": [{"url": "https://jobs.ashbyhq.com/acme/1"}]}],
        }
        rec = record_from_candidate(cand, "findall_1", [{"name": "hiring_infra_engineers"}], "2026-10-12")
        self.assertEqual(rec["name"], "Acme Inference")
        self.assertEqual(rec["careers_url"], "https://jobs.ashbyhq.com/acme")
        self.assertEqual(rec["why"], "Staff SRE, San Francisco")
        self.assertEqual(rec["evidence"], ["https://jobs.ashbyhq.com/acme/1"])

    def test_found_files_load_into_profiles(self):
        import tempfile
        from unittest import mock

        import find_companies
        import tracker

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(find_companies, "ROOT", Path(tmp)), \
                mock.patch.object(tracker, "ROOT", Path(tmp)):
            rec = {"name": "Acme", "board": {"ats": "ashby", "slug": "acme"}, "matching_roles": 2,
                   "why": "Staff SRE", "evidence": ["https://acme.ai/jobs"]}
            find_companies.write_found("infra", [rec], "2026-10-12")
            (Path(tmp) / "companies" / "tech.toml").write_text('[[company]]\nname = "Anthropic"\nats = "greenhouse"\nslug = "anthropic"\n')
            cfg = {"profile": {"companies": ["companies/tech.toml", "companies/found/infra-*.toml"]}}
            self.assertEqual([c["name"] for c in tracker.load_companies(cfg)], ["Anthropic", "Acme"])


class DedupeTests(unittest.TestCase):
    def test_same_company(self):
        from dedupe import company_key

        for a, b in [("Anthropic, PBC", "Anthropic"), ("Thinking Machines Lab", "Thinking Machines"),
                     ("Scale AI", "Scale"), ("Inferact (vLLM)", "Inferact"), ("Crusoe Energy Inc.", "Crusoe Energy")]:
            self.assertEqual(company_key(a), company_key(b), (a, b))
        self.assertNotEqual(company_key("Modal"), company_key("Mode"))

    def test_same_role(self):
        from dedupe import title_key

        same = [
            ("Sr. SWE, Infra (Remote - US)", "Senior Software Engineer - Infrastructure"),
            ("Software Engineer, Infrastructure - San Francisco, CA", "Software Engineer, Infrastructure"),
            ("Member of Technical Staff – Inference (Hybrid/San Francisco area)", "Member of Technical Staff - Inference"),
            ("Staff Engineer II", "Staff Engineer 2"),
            ("Site Reliability Engineer | New York", "SRE"),
            ("ML Infra Engineer, Platform", "Machine Learning Infrastructure Engineer - Platform"),
        ]
        for a, b in same:
            self.assertEqual(title_key(a), title_key(b), (a, b))
        different = [
            ("Software Engineer, Data", "Software Engineer"),
            ("Software Engineer, Inference", "Software Engineer, Training"),
            ("Software Engineer - Payments", "Software Engineer"),
            ("Senior Software Engineer", "Staff Software Engineer"),
        ]
        for a, b in different:
            self.assertNotEqual(title_key(a), title_key(b), (a, b))

    def test_reposts_are_not_new(self):
        from ats import Job
        from tracker import mark_seen

        def job(key, title):
            return Job(key=key, company="Acme", title=title, location="San Francisco", url="")

        seen = {}
        first = {"gh:1": job("gh:1", "Senior Software Engineer, Infrastructure"), "gh:2": job("gh:2", "SRE")}
        self.assertEqual(mark_seen(first, seen, "T1", "2026-10-01"), {"gh:1", "gh:2"})
        repost = {"gh:9": job("gh:9", "Sr. Software Engineer - Infrastructure (Remote - US)"), "gh:2": first["gh:2"]}
        self.assertEqual(mark_seen(repost, seen, "T2", "2026-10-02"), set())
        self.assertEqual(seen["role:acme|senior software engineer infrastructure"]["first_seen"], "T1")

    def test_seen_state_from_before_roles_counts(self):
        from ats import Job
        from tracker import mark_seen

        seen = {"gh:1": {"first_seen": "T0", "last_seen": "2026-09-30"}}
        jobs = {"gh:1": Job(key="gh:1", company="Acme", title="SRE", location="", url=""),
                "gh:5": Job(key="gh:5", company="Acme", title="Site Reliability Engineer (Remote)", location="", url="")}
        self.assertEqual(mark_seen(jobs, seen, "T1", "2026-10-01"), set())
        self.assertEqual(seen["role:acme|site reliability engineer"]["first_seen"], "T0")


class GeoTests(unittest.TestCase):
    def test_states(self):
        from usgeo import states

        self.assertEqual(states("San Jose, CA"), {"CA"})
        self.assertEqual(states("Washington, DC"), {"DC"})
        self.assertEqual(states("Remote or Hybrid in Ohio"), {"OH"})
        self.assertEqual(states("Work in office"), set())


class SalaryTests(unittest.TestCase):
    def test_parse(self):
        from dashboard import parse_salary

        cases = {
            "$180K – $250K • Offers Equity": (180_000, 250_000),
            "$180,000 – $250,000": (180_000, 250_000),
            "USD 180000-250000/per-year-salary": (180_000, 250_000),
            "$300K": (300_000, 300_000),
            "CA$150K – CA$200K": (None, None),
            "€90K – €120K": (None, None),
            "$45 – $60 per hour": (None, None),
            "": (None, None),
        }
        for text, want in cases.items():
            self.assertEqual(parse_salary(text), want, text)

    def test_find_pay_range(self):
        from ats import find_pay_range

        gh = "&lt;div class=&quot;pay-range&quot;&gt;&lt;span&gt;$180,000&lt;/span&gt;&lt;span&gt;&amp;mdash;&lt;/span&gt;&lt;span&gt;$250,000 USD&lt;/span&gt;"
        self.assertEqual(find_pay_range(gh), "$180,000 – $250,000")
        amzn = "pay ranges from $129,300/year in our lowest geographic market up to $223,600/year in our highest"
        self.assertEqual(find_pay_range(amzn), "$129,300 – $223,600")
        nvidia = "The base salary range is 148,000 USD - 235,750 USD for Level 3"
        self.assertEqual(find_pay_range(nvidia), "$148,000 – $235,750")
        self.assertEqual(find_pay_range("$200K - $275K"), "$200K – $275K")
        self.assertEqual(find_pay_range("no pay info"), "")


class StaffingTests(unittest.TestCase):
    f = Filters(SF_CFG)

    def test_employment_from_text(self):
        from ats import employment_from_text as emp

        cases = [
            (("Salesforce Developer (W2 only)", ""), "contract-w2"),
            (("Salesforce Developer", "Duration: 12 months. W2 only, no C2C."), "contract-w2"),
            (("Salesforce Developer", "Long-Term Contract!W2"), "contract-w2"),
            (("Salesforce Developer", "No sponsorship or C2C for this role. Must be a w2 employee", "Contract"), "contract-w2"),
            (("Salesforce Architect - C2C", ""), "contract-c2c"),
            (("Salesforce Developer", "6 month contract, open to W2 or Corp-to-Corp"), "contract-c2c"),
            (("Salesforce Admin", "We are not accepting C2C or 1099 arrangements", "Contract"), "contract"),
            (("Salesforce Admin", "Third-party corp to corp candidates will not be considered.", "Contract"), "contract"),
            (("Salesforce Admin", "This is a 1099 contract role"), "1099"),
            (("Salesforce Admin", "401(k) and Form W-2 not relevant; pay $1,099 bonus"), ""),
            (("Salesforce Developer", "Duration: 12-month contract-to-hire"), "contract-to-hire"),
            (("Salesforce Developer", "", "Temp to Perm"), "contract-to-hire"),
            (("Salesforce Developer", "", "Contractor"), "contract"),
            (("Salesforce Developer", "", "Perm"), "full-time"),
            (("Salesforce Developer", "W2 only. Benefits: Health and 401k", "Permanent"), "full-time"),
            (("Salesforce Developer", "", "FULL_TIME"), "full-time"),
            (("Salesforce Developer", "This is a direct hire position."), "full-time"),
            (("Salesforce Developer", "We build CRM tools for W-2 employees."), ""),
            (("Salesforce Contract Management Developer", ""), ""),
            (("Senior Salesforce Engineer", "<p>Join our team.</p>"), ""),
        ]
        for args, want in cases:
            self.assertEqual(emp(*args), want, args)

    def test_vendor_titles_and_locations_pass(self):
        from ats import Job

        for title in ["Salesforce Developer (W2 only)", "Sr. Salesforce Functional Architect - Hybrid NYC - 2369",
                      "Salesforce Administrator - Contract to Hire", "SFDC Administrator/Developer (Sales Cloud)"]:
            self.assertTrue(self.f.title_ok(title), title)
        for loc, wp in [("Remote", "remote"), ("Hybrid - Dallas, TX", "hybrid"), ("Charlotte, NC", ""),
                        ("Culver City, CA", ""), ("Ann Arbor, MI (Remote)", "remote")]:
            self.assertTrue(self.f(Job(key="k", company="Judge Group", title="Salesforce Developer", location=loc, url="", workplace=wp)), loc)

    def test_workplace_from_title(self):
        from ats import workplace_from_title

        self.assertEqual(workplace_from_title("Salesforce Architect - Hybrid NYC"), "hybrid")
        self.assertEqual(workplace_from_title("Salesforce Admin (Remote)"), "remote")
        self.assertEqual(workplace_from_title("Hybrid Cloud Salesforce Engineer"), "")
        self.assertEqual(workplace_from_title("Salesforce Administrator (Onsite In OKC)"), "onsite")

    def test_employment_qualifiers_dedupe_within_vendor_only(self):
        from dedupe import role_key, title_key

        for a in ["Salesforce Developer (W2 only)", "Salesforce Developer - Contract", "Salesforce Developer (No C2C)",
                  "Salesforce Developer - Contract to Hire - Dallas, TX", "Salesforce Developer (12+ months)"]:
            self.assertEqual(title_key(a), title_key("Salesforce Developer"), a)
        self.assertNotEqual(title_key("Salesforce Contract Developer"), title_key("Salesforce Developer"))
        self.assertNotEqual(role_key("TEKsystems", "Salesforce Developer"), role_key("Judge Group", "Salesforce Developer (W2)"))
        self.assertEqual(role_key("Judge Group", "Salesforce Developer"), role_key("Judge Group", "Salesforce Developer (W2)"))

    def test_phenom(self):
        from unittest import mock

        import ats

        data = {"refineSearch": {"totalHits": 1, "data": {"jobs": [{
            "jobId": "JP-1", "title": "Sr. Salesforce Developer", "location": "Culver City, California, USA",
            "multi_location": ["Culver City,CA,90230,USA", "Denver,CO,80201,USA"], "type": "Contractor",
            "postedDate": "2026-09-15T00:00:00.000+0000", "descriptionTeaser": "Remote role",
        }]}}}
        with mock.patch.object(ats, "_request", return_value=data) as req, mock.patch.object(ats.time, "sleep"):
            jobs = ats.phenom("TEKsystems", host="careers.teksystems.com", queries=["salesforce"])
        self.assertEqual(req.call_args[0][1]["keywords"], "salesforce")
        j = jobs[0]
        self.assertEqual((j.location, j.employment, j.posted), ("Culver City, CA; Denver, CO", "contract", "2026-09-15"))
        self.assertEqual(j.url, "https://careers.teksystems.com/us/en/job/JP-1/Sr-Salesforce-Developer")

    def test_judge_and_roberthalf(self):
        import json
        from unittest import mock

        import ats

        judge = json.dumps({"total": 1, "size": 20, "hits": [{
            "jobOrderId": 7, "title": "Salesforce Administrator", "location": "REMOTE", "type": "Contract",
            "opened": 1758672000000, "description": "<p>12 month contract. W2 only.</p>", "salary": "",
        }]})
        with mock.patch.object(ats, "_request", return_value=judge):
            j = ats.judge("Judge Group", queries=["salesforce"])[0]
        self.assertEqual((j.location, j.workplace, j.employment, j.url),
                         ("Remote", "remote", "contract-w2", "https://www.judge.com/jobs/details/7/"))

        rh = {"found": "1", "jobs": [{
            "unique_job_number": "02210-1", "jobtitle": "Salesforce Developer", "city": "Ann Arbor", "stateprovince": "MI",
            "remote": "Yes", "emptype": "Temp to Perm", "payrate_min": "57", "payrate_max": "66", "payrate_period": "Hourly",
            "date_posted": "2026-09-23T00:00:00Z", "job_detail_url": "https://www.roberthalf.com/us/en/job/x",
        }]}
        with mock.patch.object(ats, "_request", return_value=rh):
            j = ats.roberthalf("Robert Half", queries=["salesforce"])[0]
        self.assertEqual((j.location, j.workplace, j.employment, j.salary),
                         ("Ann Arbor, MI (Remote)", "remote", "contract-to-hire", "$57 – $66/hr"))

    def test_employment_facet_only_when_enabled(self):
        import dashboard
        from ats import Job

        jobs = [Job(key="a:1", company="Judge Group", title="Salesforce Developer (W2)", location="Remote", url="", employment="contract-w2"),
                Job(key="a:2", company="Judge Group", title="Salesforce Developer", location="Remote", url="", employment="contract")]
        seen = {j.key: {"first_seen": "T1"} for j in jobs}
        sf = dashboard.Facets(SF_CFG["dashboard"])
        infra = dashboard.Facets(tomllib.loads((PROFILES / "infra.toml").read_text()).get("dashboard", {}))
        self.assertIn("employments", sf.order())
        self.assertNotIn("employments", infra.order())
        roles = dashboard.build_roles(jobs, seen, lambda _: True, sf)
        self.assertEqual([(r["postings"], r["employment"]) for r in roles], [(2, "Contract (W2)")])
        self.assertNotIn("employment", dashboard.build_roles(jobs, seen, lambda _: True, infra)[0])


if __name__ == "__main__":
    unittest.main()
