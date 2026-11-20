"""Deferred responses exercise the actual media page and authenticated API wrapper."""
import sandbox  # noqa: F401
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node exercises the shared page JS')
class MediaUI(unittest.TestCase):
    def check_order(self, scenario):
        run = subprocess.run(['node', str(ROOT/'tests/media_refresh.cjs'),
                              str(ROOT/'ui/index.html'), scenario],
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_latest_success_keeps_its_library_and_player_state(self):
        self.check_order('newer_success')

    def test_obsolete_failure_does_not_report_an_error(self):
        self.check_order('obsolete_failure')

    def test_current_failure_survives_an_older_success(self):
        self.check_order('current_failure')

    def test_stop_refresh_survives_an_older_playing_snapshot(self):
        self.check_order('stop_refresh')

    def test_old_headset_success_leaves_current_display(self):
        self.check_order('switched_success')

    def test_old_headset_transport_failure_leaves_current_display(self):
        self.check_order('switched_transport_failure')
