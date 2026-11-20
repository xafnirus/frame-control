"""An older volume write must not expose a newer draft to status refreshes."""
import sandbox  # noqa: F401
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node exercises the shipped volume UI')
class VolumeUI(unittest.TestCase):
    def check_case(self, scenario):
        run = subprocess.run(['node', str(ROOT / 'tests/volume_pending.cjs'),
                              str(ROOT / 'ui/index.html'), scenario],
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_old_success_keeps_new_volume_draft(self):
        self.check_case('success')

    def test_old_failure_keeps_new_volume_draft(self):
        self.check_case('failure')

    def test_old_headset_success_keeps_new_headsets_draft(self):
        self.check_case('switched_success')

    def test_old_headset_failure_keeps_new_headsets_draft(self):
        self.check_case('switched_failure')

    def test_debounce_sends_latest_value_and_retains_failure(self):
        self.check_case('debounce')

    def test_headset_switch_cancels_unsent_value(self):
        self.check_case('switch_cancels_pending')
