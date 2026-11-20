"""Plugin names and receipt digests stay exact across inventory and RPC."""
import sandbox  # noqa: F401
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shlex
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ui'))
import frame_decky
import frame_decky_store
import framey_panel


class PluginNameIdentity(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.folder = self.home/'.local/share/frame-control/decky/plugins/Example'
        self.folder.mkdir(parents=True)
        self.name = 'Shared plugin prefix ' * 6 + '雪 "quoted" \\ suffix'
        self.digest = 'a' * 64
        (self.folder/'plugin.json').write_text(json.dumps({'name':self.name,'flags':[]}))
        (self.folder/'.frame-control-store.json').write_text(json.dumps(
            {'storeId':42,'sha256':self.digest,'version':'1.0'}))

    def inventory(self):
        # Execute the real lightweight remote inventory in a disposable home.
        output = io.StringIO()
        with patch.object(Path, 'home', return_value=self.home), contextlib.redirect_stdout(output):
            exec(frame_decky.PLUGINS_PROBE, {})
        return json.loads(output.getvalue())

    def test_inventory_does_not_truncate_or_coerce_receipt_digests(self):
        receipt = self.folder/'.frame-control-store.json'
        for digest in (self.digest, self.digest+'b', self.digest+' trailing',
                       self.digest+'雪', int('1'*64), None, True, [], {}):
            with self.subTest(digest=digest):
                raw = json.dumps({'storeId':42,'sha256':digest,'version':'1.0'}).encode()
                receipt.write_bytes(raw)
                found = self.inventory()['plugins'][0]
                self.assertEqual(found['sha256'], digest if isinstance(digest,str) else '')
                self.assertEqual(found['storeId'],42)
                self.assertEqual(found['name'],self.name)
                self.assertEqual(receipt.read_bytes(),raw)

    def test_malformed_digest_cannot_authorize_backend_calls_and_recovers_after_repair(self):
        receipt = self.folder/'.frame-control-store.json'
        (self.folder/'plugin.json').write_text(json.dumps({'name':self.name,'flags':[],'api_version':2}))
        dist = self.folder/'dist'
        dist.mkdir()
        bundle = b'export default () => ({content: null});'
        (dist/'index.js').write_bytes(bundle)
        forwarded = []

        def ssh(command, stdin=None, **kwargs):
            self.assertEqual(command,'python3 -')
            if stdin == frame_decky.PLUGINS_PROBE:
                return json.dumps(self.inventory())
            forwarded.append(stdin)
            return json.dumps({'result':True})

        with patch.object(framey_panel,'PLUGINS',self.folder.parent):
            for digest, reviewed in ((self.digest+'b',self.digest), (int('1'*64),'1'*64)):
                with self.subTest(digest=digest):
                    raw = json.dumps({'storeId':42,'sha256':digest,'version':'1.0'}).encode()
                    receipt.write_bytes(raw)
                    with self.assertRaises(FileNotFoundError):
                        framey_panel.local_bundle(42)
                    for legacy,args in ((False,['enabled',True]), (True,[{'key':'enabled','value':True}])):
                        with self.assertRaisesRegex(framey_panel.PanelError,'plugin changed'):
                            framey_panel.call_method(ssh,42,'set_setting',args,legacy,reviewed)
                    with self.assertRaisesRegex(framey_panel.PanelError,'plugin changed'):
                        framey_panel.poll_events(ssh,42,'receipt-test',['settings:changed'],receipt=reviewed)
                    self.assertEqual(forwarded,[],'invalid receipt must stop before a CEF request')
                    self.assertEqual(receipt.read_bytes(),raw)
            # A fresh read recognizes a repaired receipt without reinstalling.
            receipt.write_text(json.dumps({'storeId':42,'sha256':self.digest,'version':'1.0'}))
            self.assertEqual(framey_panel.local_bundle(42),bundle)
            self.assertEqual(framey_panel.call_method(ssh,42,'set_setting',['enabled',True],
                                                     receipt=self.digest),{'result':True})
            self.assertEqual(len(forwarded),1)

    def records(self, names):
        return [{'id':42+index,'name':name,'versions':[{'name':'1.0','hash':self.digest}],'tags':[]}
                for index,name in enumerate(names)]

    def test_catalog_names_match_archive_names_without_truncating_shared_prefixes(self):
        names = ['x'*80, 'x'*81, 'x'*100, 'x'*100+'one', 'x'*100+'two', self.name]
        with patch.object(frame_decky_store.urllib.request, 'urlopen',
                          return_value=io.BytesIO(json.dumps(self.records(names)).encode())):
            catalog = frame_decky_store.catalog()
        self.assertEqual([plugin['name'] for plugin in catalog], names)
        for plugin in catalog:
            with self.subTest(name=plugin['name']):
                output = io.BytesIO()
                with zipfile.ZipFile(output,'w') as archive:
                    archive.writestr('Example/plugin.json',json.dumps({'name':plugin['name'],'flags':[]}))
                    archive.writestr('Example/dist/index.js',b'export default {};' + b' '*1500)
                data = output.getvalue()
                self.assertEqual(frame_decky_store.archive_info(data,hashlib.sha256(data).hexdigest(),
                                                               plugin['name']), 'Example')

    def test_inventory_keeps_complete_distinct_names(self):
        other = self.folder.parent/'Other'
        other.mkdir()
        second = self.name[:-6]+'different suffix'
        (other/'plugin.json').write_text(json.dumps({'name':second}))
        result = self.inventory()['plugins']
        self.assertEqual([plugin['name'] for plugin in result], [self.name,second])
        self.assertEqual(result[0]['storeId'],42)
        self.assertEqual(result[0]['sha256'],self.digest)

    def test_backend_calls_and_event_subscriptions_use_inventory_identity(self):
        routes = []
        class Page:
            sock = types.SimpleNamespace(close=lambda:None)
            def eval(page, expression):
                arguments = expression.split('DeckyBackend.call(',1)[1].split(')})()',1)[0]
                routes.append(json.loads('['+arguments+']'))
                return True
        def ssh(command, stdin=None, **kwargs):
            if stdin == frame_decky.PLUGINS_PROBE:
                return json.dumps(self.inventory())
            if command == 'python3 -':
                output = io.StringIO()
                with patch.dict(sys.modules, {'frame_steam':types.SimpleNamespace(Page=Page)}), \
                     patch.object(sys, 'path', list(sys.path)), contextlib.redirect_stdout(output):
                    exec(stdin,{})
                return output.getvalue()
            payload = json.loads(shlex.split(command)[2])
            self.assertEqual(payload['name'], self.name)
            return json.dumps({'events':[],'cursor':0})
        for legacy,args in [(False,['enabled',True]),(True,[{'key':'enabled','value':True}])]:
            with self.subTest(legacy=legacy):
                self.assertEqual(framey_panel.call_method(ssh,42,'set_setting',args,legacy,self.digest),{'result':True})
                self.assertEqual(routes[-1],[('loader/call_legacy_plugin_method' if legacy else 'loader/call_plugin_method'),
                                             self.name,'set_setting',*args])
        framey_panel.poll_events(ssh,42,'identity-test',['settings:changed'],receipt=self.digest)

    def test_existing_complete_name_blocks_duplicate_before_archive_download(self):
        state = {'managed':True,'running':True,**self.inventory()}
        # A different store ID still cannot install the same backend name.
        records = self.records([self.name]); records[0]['id'] = 43
        with patch.object(frame_decky_store.frame_decky,'status',return_value=state), \
             patch.object(frame_decky_store.urllib.request,'urlopen',
                          side_effect=[io.BytesIO(json.dumps(records).encode()),
                                       AssertionError('Duplicate reached archive download')]) as network:
            with self.assertRaisesRegex(ValueError,'name is already installed'):
                frame_decky_store.change(lambda *a,**k:self.fail('Duplicate reached headset transfer'),
                                         'install',43,reviewed_hash=self.digest)
        self.assertEqual(network.call_count,1,'Only the catalog may be read; do not download an archive')
        self.assertEqual(self.inventory()['plugins'][0]['name'],self.name)


if __name__ == '__main__':
    unittest.main()
