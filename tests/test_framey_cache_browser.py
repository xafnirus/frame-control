"""Native browser storage recovery with real parent-page controls, offline."""
import sandbox  # noqa: F401
import hashlib
import html
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from test_framey_textfield_browser import BROWSER, run_browser, wait_browser_group

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'ui'))
import frame_steam


@unittest.skipUnless(sys.platform.startswith('linux') and BROWSER, 'Linux Chrome/Chromium is needed for native browser storage')
class CacheBrowser(unittest.TestCase):
    def test_async_save_reports_native_storage_failure_and_recovers(self):
        source = (ROOT/'ui/headset.html').read_text()
        host = (ROOT/'ui/framey-host.js').read_text()
        host = host.replace('\n  start();\n})();', '\n  window.waitForSeed = waitForSeed;\n})();')
        child = '<div id="framey-root"></div><div id="framey-error"></div><div id="framey-toasts"></div><div id="framey-modal"></div>'
        child += "<script>addEventListener('error',event=>parent.postMessage({type:'test:failure',error:event.message},'*'));</script>"
        for script in [(ROOT/'ui/vendor/react-18.3.1.min.js').read_text(),
                       (ROOT/'ui/vendor/react-dom-18.3.1.min.js').read_text(), host]:
            child += '<script>'+script.replace('</script', r'<\/script')+'</script>'
        child += '''<script>
        (async()=>{
          try{
            if(window.origin!=='null')throw Error('Plugin iframe must have an opaque origin');
            await waitForSeed();
            await SteamClient.Storage.SetObject('setting',{enabled:false});
            let failure='';
            try{await SteamClient.Storage.SetObject('setting',{enabled:true});}
            catch(error){failure=error.message;}
            if(!failure.includes('only in memory'))throw Error('Blocked save did not reject: '+failure);
            if(await SteamClient.Storage.GetJSON('setting')!=='{"enabled":true}')throw Error('Draft lost');
            await SteamClient.Storage.SetObject('setting',{enabled:true});
            parent.postMessage({type:'test:complete'},'*');
          }catch(error){parent.postMessage({type:'test:failure',error:String(error)},'*');}
        })();</script>'''
        page = source.split('refresh();refreshGames();')[0]+'</script><pre id="result">Pending</pre><script>'
        page = page.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" '
                            'content="default-src \'none\'; script-src \'unsafe-inline\'; '
                            'style-src \'unsafe-inline\'; frame-src \'self\'">', 1)
        page += r'''(() => {
        const key='framey-plugin-cache-v1:14',phaseKey='framey-commit-proof';
        const result=document.getElementById('result');
        const assert=(value,message)=>{if(!value)throw Error(message);};
        const previous=sessionStorage.getItem(phaseKey);
        if(previous){
          try{
            assert(JSON.parse(localStorage.getItem(key))['steam-client:setting']==='{"enabled":true}',
              'acknowledged save did not survive page reload');
            result.textContent=JSON.stringify({...JSON.parse(previous),pageReloadReadback:true});
          }catch(error){result.textContent=JSON.stringify({passed:false,error:String(error)});}
        }else{
          activeFrameyId=14;frameySession='';
          document.getElementById('frameyPanel').hidden=false;
          const frame=document.getElementById('frameyFrame'),nativeSet=Storage.prototype.setItem;
          let denied=false,commits=0;
          Storage.prototype.setItem=function(name,value){
            if(name===key&&denied)throw new DOMException('Synthetic quota failure','QuotaExceededError');
            return nativeSet.call(this,name,value);
          };
          addEventListener('message',event=>{
            if(event.source!==frame.contentWindow||result.textContent!=='Pending')return;
            try{
              if(event.data?.type==='test:failure')throw Error(event.data.error);
              if(event.data?.type==='test:complete'){
                assert(commits===3,'expected three acknowledged save attempts');
                Storage.prototype.setItem=nativeSet;
                sessionStorage.setItem(phaseKey,JSON.stringify({passed:true,opaqueIframe:true,
                  nativeBrowserStorage:true,blockedSaveRejected:true,retrySavedDraft:true,
                  subsequentSaveSucceeded:true,realFrameContacted:false,wornVRVerified:false}));
                location.reload();return;
              }
              if(!['framey:cache:commit','framey:cache:save'].includes(event.data?.type))return;
              commits++;
              const value=JSON.parse(localStorage.getItem(key))['steam-client:setting'];
              if(commits===1){
                assert(value==='{"enabled":false}','save resolved before native storage changed');
                denied=true;
              }else if(commits===2){
                assert(value==='{"enabled":false}','blocked save changed disk');
                assert(!document.getElementById('frameyCacheWarning').hidden,'failed save notice missing');
                denied=false;document.getElementById('frameyCacheRetry').click();
                assert(document.getElementById('frameyCacheWarning').hidden,'retry did not clear notice');
                assert(JSON.parse(localStorage.getItem(key))['steam-client:setting']==='{"enabled":true}',
                  'retry did not persist the rejected save draft');
              }
            }catch(error){if(result.textContent==='Pending')result.textContent=JSON.stringify({passed:false,error:String(error)});}
          });
          frame.srcdoc=__CHILD__;
        }
        })();
        '''.replace('__CHILD__', json.dumps(child).replace('</script', r'<\/script'))
        page += '</script></body></html>'
        with tempfile.TemporaryDirectory(prefix='framey-cache-commit-') as folder:
            document = Path(folder)/'fixture.html'
            document.write_text(page)
            # dump-dom/virtual time can end before opaque-frame message tasks
            # settle. Observe this owned browser over CDP with a real deadline.
            process = subprocess.Popen([BROWSER, '--headless', '--disable-gpu', '--no-first-run',
                '--no-default-browser-check', '--disable-background-networking',
                '--user-data-dir='+str(Path(folder)/'profile'), '--remote-debugging-address=127.0.0.1',
                '--remote-debugging-port=0', document.as_uri()], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
            connection = None
            value = 'Pending'
            try:
                deadline = time.monotonic()+15
                while value == 'Pending' and time.monotonic() < deadline:
                    try:
                        if connection is None:
                            port = (Path(folder)/'profile/DevToolsActivePort').read_text().splitlines()[0]
                            with patch.object(frame_steam, 'CDP', 'http://127.0.0.1:'+port+'/json'):
                                connection = frame_steam.Page('Frame Control VR [fc-headset]')
                        value = connection.eval('document.getElementById("result")?.textContent || "Pending"')
                    except (OSError, IndexError, frame_steam.Fail):
                        pass  # Includes the intentional full page reload.
                    time.sleep(.02)
                self.assertNotEqual(value, 'Pending', 'Private storage browser did not complete')
                report = json.loads(value)
            finally:
                if connection is not None:
                    connection.sock.close()
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                wait_browser_group(process.pid)
        self.assertIs(report.get('passed'), True, report)
        self.assertIs(report.get('pageReloadReadback'), True, report)
        print('Framey async storage browser proof: '+json.dumps(report, sort_keys=True))

    def test_retry_saves_latest_panel_cache_across_real_page_reload(self):
        source = (ROOT/'ui/headset.html').read_text()
        # Keep the actual parent DOM, handlers and persistence code. Stop only
        # automatic remote startup; CSP blocks every network/frame connection.
        marker = 'refresh();refreshGames();'
        self.assertEqual(source.count(marker), 1)
        page = source.split(marker)[0]+'</script>'
        page = page.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" '
                            'content="default-src \'none\'; script-src \'unsafe-inline\'; '
                            'style-src \'unsafe-inline\'">', 1)
        page += (ROOT/'tests/page/framey_cache_retry.html').read_text()+'</body></html>'
        with tempfile.TemporaryDirectory(prefix='framey-cache-browser-') as folder:
            document = Path(folder)/'fixture.html'
            document.write_text(page)
            run = run_browser([BROWSER, '--headless', '--disable-gpu', '--no-first-run',
                               '--no-default-browser-check', '--disable-background-networking',
                               '--user-data-dir='+str(Path(folder)/'profile'), '--dump-dom',
                               '--virtual-time-budget=3000', document.as_uri()])
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        result = re.search(r'<pre id="result">([^<]*)</pre>', run.stdout)
        self.assertIsNotNone(result, run.stderr[-2000:])
        report = json.loads(html.unescape(result.group(1)))
        self.assertIs(report.get('passed'), True, report)
        self.assertIs(report.get('realPageReloadReadback'), True, report)
        report['headsetSourceSha256'] = hashlib.sha256(source.encode()).hexdigest()
        print('Framey cache retry browser proof: '+json.dumps(report, sort_keys=True))

    def test_unreadable_cache_never_becomes_an_empty_saved_snapshot(self):
        source = (ROOT/'ui/headset.html').read_text()
        # Keep the actual parent DOM, handlers and persistence code. Stop only
        # automatic remote startup; CSP blocks every network/frame connection.
        marker = 'refresh();refreshGames();'
        self.assertEqual(source.count(marker), 1)
        page = source.split(marker)[0]+'</script>'
        page = page.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" '
                            'content="default-src \'none\'; script-src \'unsafe-inline\'; '
                            'style-src \'unsafe-inline\'">', 1)
        page += (ROOT/'tests/page/framey_cache_read.html').read_text()+'</body></html>'
        with tempfile.TemporaryDirectory(prefix='framey-cache-browser-') as folder:
            document = Path(folder)/'fixture.html'
            document.write_text(page)
            run = run_browser([BROWSER, '--headless', '--disable-gpu', '--no-first-run',
                               '--no-default-browser-check', '--disable-background-networking',
                               '--user-data-dir='+str(Path(folder)/'profile'), '--dump-dom',
                               '--virtual-time-budget=3000', document.as_uri()])
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        result = re.search(r'<pre id="result">([^<]*)</pre>', run.stdout)
        self.assertIsNotNone(result, run.stderr[-2000:])
        report = json.loads(html.unescape(result.group(1)))
        self.assertIs(report.get('passed'), True, report)
        self.assertIs(report.get('failedReadPreservedSavedBytes'), True, report)
        report['headsetSourceSha256'] = hashlib.sha256(source.encode()).hexdigest()
        print('Framey cache read browser proof: '+json.dumps(report, sort_keys=True))
