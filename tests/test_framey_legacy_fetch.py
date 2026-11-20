"""Legacy proxy failure contract with an exact published plugin call site."""
import sandbox  # noqa: F401
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from framey_official import PLUGINS, archive

ROOT = Path(__file__).resolve().parents[1]


class LegacyFetch(unittest.TestCase):
    def test_published_login_handles_unsupported_proxy_without_a_rejection(self):
        plugin = next(p for p in PLUGINS if p['id'] == 28)
        data = archive(plugin)
        self.assertEqual(hashlib.sha256(data).hexdigest(), plugin['sha256'])
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            frontend = bundle.read(plugin['folder']+'/dist/index.js').decode()
        start = frontend.index('      get loggedIn() {')
        end = frontend.index('      async init() {', start)
        getter = frontend[start:end]
        self.assertIn('this.serverAPI.fetchNoCors', getter)
        self.assertIn('authenticated.success', getter)
        with tempfile.TemporaryDirectory(prefix='framey-legacy-fetch-') as folder:
            path = Path(folder)/'published-getter.js'
            path.write_text(getter)
            run = subprocess.run(['node', str(ROOT/'tests/page/framey_legacy_fetch.mjs'), str(path)],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        prefix = 'Framey legacy fetch proof: '
        self.assertTrue(run.stdout.startswith(prefix), run.stdout)
        report = json.loads(run.stdout[len(prefix):])
        self.assertIs(report['passed'], True, report)
        report.update(archiveSha256=plugin['sha256'],
                      hostSha256=hashlib.sha256((ROOT/'ui/framey-host.js').read_bytes()).hexdigest())
        print(prefix+json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
