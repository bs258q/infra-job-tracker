import tempfile
import unittest
from datetime import date
from pathlib import Path

import storage_check as sc


def write(root: Path, rel: str, size: int) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x" * size)


class MeasureTests(unittest.TestCase):
    def test_flags_only_files_over_their_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, "state/infra/seen.json", 1024)
            write(root, "state/infra/discovery.json", sc.STATE_FILE_WARN)
            write(root, "web/public/data/infra/jobs.json", sc.DATA_FILE_WARN + 1)
            write(root, "web/public/data/infra/history.json", 1024)
            write(root, "web/public/data/profiles.json", sc.DATA_FILE_WARN * 2)  # not a per-profile file
            crossed = {c.key for c in sc.measure(root) if c.crossed}
            self.assertEqual(
                crossed,
                {"state-file:state/infra/discovery.json", "data-file:web/public/data/infra/jobs.json"},
            )

    def test_state_total_counts_every_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            per_file = sc.STATE_TOTAL_WARN // 4 + 1
            for p in ("a", "b", "c", "d"):
                write(root, f"state/{p}/seen.json", per_file)
            checks = {c.key: c for c in sc.measure(root)}
            self.assertTrue(checks["state-total"].crossed)
            self.assertEqual(checks["state-total"].size, 4 * per_file)
            self.assertIn("PRUNE_AFTER_DAYS", checks["state-file:state/a/seen.json"].advice)


class DedupeTests(unittest.TestCase):
    today = date(2026, 10, 11)

    def test_nothing_crossed_never_alerts(self):
        self.assertFalse(sc.should_alert([], {}, self.today))
        self.assertFalse(sc.should_alert([], {"sent": "2020-01-01", "keys": ["state-total"]}, self.today))

    def test_first_crossing_alerts(self):
        self.assertTrue(sc.should_alert(["state-total"], {}, self.today))

    def test_same_set_waits_a_week(self):
        last = {"sent": "2026-10-08", "keys": ["state-total"]}
        self.assertFalse(sc.should_alert(["state-total"], last, self.today))
        last = {"sent": "2026-10-04", "keys": ["state-total"]}
        self.assertTrue(sc.should_alert(["state-total"], last, self.today))

    def test_changed_set_alerts_immediately(self):
        last = {"sent": "2026-10-10", "keys": ["state-total"]}
        self.assertTrue(sc.should_alert(["repo-size", "state-total"], last, self.today))
        self.assertTrue(sc.should_alert(["repo-size"], last, self.today))

    def test_bad_alert_file_alerts(self):
        self.assertTrue(sc.should_alert(["state-total"], {"keys": ["state-total"], "sent": "garbage"}, self.today))


if __name__ == "__main__":
    unittest.main()
