"""Explicit unsupported picker promises at published modern/legacy call sites."""
import sandbox  # noqa: F401
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from framey_official import LEGACY_PLUGINS, PLUGINS, archive

ROOT = Path(__file__).resolve().parents[1]


class FilePicker(unittest.TestCase):
    def test_published_helpers_receive_rejected_promises(self):
        snippets = []
        digests = {}
        for plugin_id, start_marker, end_marker in (
                (125, 'var fileOpener =', '\n\nconst createFileHandlers'),
                (7, 'async function openFilePicker(path)', '\n    function fetchThemePath')):
            plugin = next(p for p in (*PLUGINS, *LEGACY_PLUGINS) if p['id'] == plugin_id)
            data = archive(plugin)
            self.assertEqual(hashlib.sha256(data).hexdigest(), plugin['sha256'])
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                frontend = bundle.read(plugin['folder']+'/dist/index.js').decode()
            start = frontend.index(start_marker)
            snippets.append(frontend[start:frontend.index(end_marker, start)])
            digests[plugin_id] = plugin['sha256']
        with tempfile.TemporaryDirectory(prefix='framey-file-picker-') as folder:
            paths = [Path(folder)/f'helper-{index}.js' for index in range(len(snippets))]
            for path, snippet in zip(paths, snippets):
                path.write_text(snippet)
            run = subprocess.run(['node', str(ROOT/'tests/page/framey_file_picker.mjs'),
                                  *map(str, paths)], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        prefix = 'Framey file picker proof: '
        self.assertTrue(run.stdout.startswith(prefix), run.stdout)
        report = json.loads(run.stdout[len(prefix):])
        self.assertIs(report['passed'], True, report)
        report.update(archiveSha256=digests,
                      hostSha256=hashlib.sha256((ROOT/'ui/framey-host.js').read_bytes()).hexdigest())
        print(prefix+json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
