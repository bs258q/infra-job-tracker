import tomllib
import unittest
from pathlib import Path

from tracker import Filters

CFG = tomllib.loads((Path(__file__).parent / "config.toml").read_text())


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


if __name__ == "__main__":
    unittest.main()
