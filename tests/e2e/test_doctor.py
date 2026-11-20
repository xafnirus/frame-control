"""Real doctor/SSH against fake-Frame faults; never a real headset."""
import subprocess
import socket
import sys
import tempfile
from pathlib import Path

import harness
from harness import ROOT, ctl

harness.require()


class Doctor(harness.FrameTestCase):
    def doctor(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/frame_doctor.py'),
                               '--lan', harness.FAKE_HOST, '--usb', harness.FAKE_HOST, *args],
                              capture_output=True, text=True, timeout=120)

    def test_disk_full(self):
        before = self.doctor()
        self.assertNotIn('BROKEN 4. Steam and storage', before.stdout)
        ctl('disk-full', 'on')
        r = self.doctor()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('BROKEN 4. Steam and storage: Less than 16 MiB free', r.stdout)

    def test_unreachable_asleep(self):
        ctl('sleep', 'on')
        r = self.doctor()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('No authenticated SSH path', r.stdout)

    def test_no_ssh_and_no_devkit(self):
        ctl('sshd', 'off')
        ctl('devkit-service', 'off')
        r = self.doctor()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('Devkit port did not respond', r.stdout)

    def test_no_keys_but_devkit_available(self):
        ctl('keys', 'none')
        r = self.doctor()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('SSH key rejected', r.stdout)
        self.assertIn('no pairing request was sent', r.stdout)

    def test_plan_and_before_after_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline = str(Path(folder) / 'before.json')
            ctl('disk-full', 'on')
            before = self.doctor('--plan', '--save-report', baseline)
            self.assertEqual(before.returncode, 1, before.stdout + before.stderr)
            self.assertIn('use Steam storage management', before.stdout)
            ctl('disk-full', 'off')  # fake fault control, not a doctor repair
            after = self.doctor('--plan', '--compare-before', baseline)
            self.assertEqual(after.returncode, 1, after.stdout + after.stderr)
            self.assertIn('Steam and storage: BROKEN ->', after.stdout)
            self.assertNotIn('Steam and storage: BROKEN -> BROKEN', after.stdout)
            self.assertIn('no automatic repair is available', after.stdout)

    def test_no_usb_baseline_uses_alias_and_refuses_changed_routes(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline = str(Path(folder) / 'alias-only.json')
            command = [sys.executable, str(ROOT / 'scripts/frame_doctor.py')]
            before = subprocess.run([*command, '--no-usb', '--save-report', baseline],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(before.returncode, 1, before.stdout + before.stderr)
            self.assertIn('OK Connection: configured alias', before.stdout)
            self.assertTrue(Path(baseline).is_file())
            after = subprocess.run([*command, '--no-usb', '--compare-before', baseline],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(after.returncode, 1, after.stdout + after.stderr)
            self.assertIn('Before/after', after.stdout)
            changed = subprocess.run([*command, '--compare-before', baseline],
                                     capture_output=True, text=True, timeout=120)
            self.assertEqual(changed.returncode, 2, changed.stdout + changed.stderr)
            self.assertIn('SSH target configuration differs', changed.stdout)

    def test_no_usb_does_not_probe_test_hosts_loopback(self):
        # A different devkit-like service on the computer is not the Frame.
        # Only this isolated test-host container owns this listener.
        with socket.create_server(('127.0.0.1', 32000)) as local:
            ctl('sshd', 'off')
            ctl('devkit-service', 'off')
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/frame_doctor.py'),
                                  '--no-usb'], capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
            self.assertIn('Devkit port did not respond', run.stdout)
            local.settimeout(.1)
            with self.assertRaises(socket.timeout):
                local.accept()
