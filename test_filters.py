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


if __name__ == "__main__":
    unittest.main()
