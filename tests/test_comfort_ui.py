"""Run the actual shared page's comfort renderer against a minimal DOM/bridge."""
import sandbox  # noqa: F401  (first: keeps tests off real data and services)
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node exercises the shared page JS')
class ComfortUI(unittest.TestCase):
    def test_late_status_cannot_overwrite_session_changes(self):
        page = (ROOT / 'ui/index.html').read_text(encoding='utf-8')
        api = page[page.index('let devGen ='):page.index('function setConn(')]
        comfort = page[page.index('let comfortBusy ='):page.index('// Show a destination now,')]
        setup = r'''
const assert = require('node:assert/strict');
const elements = new Map();
const $ = id => {
  const value = {sessionMinutes:'30',breakMinutes:'20',stillMinutes:'30'}[id] || '';
  if (!elements.has(id)) elements.set(id, {textContent:'',hidden:true,disabled:false,
    value,defaultValue:value,checked:true,defaultChecked:true,
    type:/Alert$/.test(id)?'checkbox':'number'});
  return elements.get(id);
};
const window = {connDevice:'one',frameApp:{notify:async()=>{notifications++;}}};
const UI_KEY = 'test', log = ()=>{}, toast = ()=>{}, setTimeout = ()=>{};
let online = true, notifications = 0;
const requests = [];
const fetch = (path, opts) => new Promise((resolve, reject) => {
  requests.push({body:JSON.parse(opts.body),resolve,reject});
});
const reply = (request, value) => request.resolve({ok:true,json:async()=>value});
const inactive = {id:'session',active:false,time:100,events:[]};
const active = {...inactive,active:true,remaining:1800,
  options:{minutes:30,breakMinutes:20,stillMinutes:30,batteryAlert:true,heatAlert:true}};
'''
        checks = r'''
(async()=>{
  const start = ACTION === 'start';
  renderComfort(start ? inactive : active);
  const pendingPoll = pollComfort();
  assert.equal(requests.length,1);
  const mutation = start ? $('comfortForm').onsubmit({preventDefault(){}})
                         : $('sessionCancel').onclick();
  assert.equal(requests[1].body.action,ACTION);
  const duringMutation = pollComfort();
  await duringMutation;
  assert.equal(requests.length,2,'no status request while a session change is pending');
  reply(requests[1],start ? active : inactive);
  await mutation;
  const expected = $('comfortStatus').textContent;
  if (FAIL) requests[0].reject(Error('late network failure'));
  else reply(requests[0],start ? inactive : active);
  await pendingPoll;
  assert.equal($('comfortStatus').textContent,expected,'old poll replaced the completed action');
  assert.equal($('sessionStart').disabled,start);
  assert.equal($('sessionCancel').disabled,!start);
  assert.equal(notifications,0);
  const next = pollComfort();
  assert.equal(requests.length,3,'polling resumes after the change');
  reply(requests[2],{...active,remaining:1200});
  await next;
  assert.match($('comfortStatus').textContent,/20 min/);
  // No older poll is running now: the mutation itself must suppress new polls.
  const failedCancel = $('sessionCancel').onclick();
  assert.equal(requests.length,4);
  await pollComfort();
  assert.equal(requests.length,4);
  requests[3].resolve({ok:false,status:500,json:async()=>({error:'Cancel failed'})});
  await failedCancel;
  assert.match($('comfortStatus').textContent,/20 min/);
  const recovery = pollComfort();
  reply(requests[4],inactive);
  await recovery;
  assert.equal($('sessionStart').disabled,false);
  // The shared api rejects old-headset answers; the comfort error path must
  // preserve the new headset's display rather than show "Switched headsets".
  const switchingPoll = pollComfort();
  devGen++;
  window.connDevice = 'two';
  $('comfortStatus').textContent = 'New headset';
  if (FAIL) requests[5].reject(Error('old headset transport failed'));
  else reply(requests[5],active);
  await switchingPoll;
  assert.equal($('comfortStatus').textContent,'New headset');
  const newHeadsetPoll = pollComfort();
  reply(requests[6],inactive);
  await newHeadsetPoll;
  assert.equal($('comfortStatus').textContent,'No session running.');
  // A current failure still appears and a later poll can recover.
  const currentFailure = pollComfort();
  requests[7].resolve({ok:false,status:500,json:async()=>({error:'Status failed'})});
  await currentFailure;
  assert.equal($('comfortStatus').textContent,'Session status unavailable: Status failed');
  const finalPoll = pollComfort();
  reply(requests[8],inactive);
  await finalPoll;
  assert.equal($('comfortStatus').textContent,'No session running.');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        for action in ('start', 'cancel'):
            for fail in (False, True):
                with self.subTest(action=action, late_failure=fail):
                    constants = f"const ACTION = '{action}', FAIL = {str(fail).lower()};\n"
                    result = subprocess.run(['node', '-e', setup + constants + api + comfort + checks],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_notification_failure_survives_poll_until_success(self):
        page = (ROOT / 'ui/index.html').read_text(encoding='utf-8')
        code = page[page.index('let comfortBusy ='):page.index('async function pollComfort()')]
        setup = r'''
const assert = require('node:assert/strict');
const elements = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, {textContent:'', hidden:true, disabled:false, type: 'number'});
  return elements.get(id);
};
let denied = 0;
const window = {frameApp:{notify:async()=>{denied++;throw Error('permission denied');}}};
const log = ()=>{}, toast = ()=>{};
'''
        checks = r'''
(async()=>{
  const active = {id:'session-one',active:true,time:100,remaining:120,
    options:{minutes:2,breakMinutes:1,stillMinutes:1,batteryAlert:true,heatAlert:true},
    events:[{id:'event-one',kind:'battery',time:99,message:'Low battery'}]};
  renderComfort(active); // initial history must not replay even a fresh event
  assert.equal(denied,0);
  assert.equal($('comfortAnnouncement').textContent,'');
  active.events.push({id:'event-two',kind:'break',time:100,message:'Take a break'});
  renderComfort(active);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(denied,1);
  assert.equal($('comfortAnnouncement').textContent,'Take a break');
  assert.equal($('comfortNotificationStatus').hidden,false);
  assert.match($('comfortNotificationStatus').textContent,/notification settings/);
  renderComfort({...active,time:105}); // the next normal poll must not erase failure
  assert.equal($('comfortNotificationStatus').hidden,false);
  assert.equal($('sessionStart').disabled,true);
  assert.equal($('sessionMinutes').disabled,true);
  assert.equal($('sessionCancel').disabled,false);
  let requests=0;
  window.frameApp.notify=async()=>{requests++;};
  renderComfort({...active,time:106});
  assert.equal($('comfortAnnouncement').textContent,'Take a break');
  assert.equal(requests,0); // polling does not replay an already-seen event
  await localNotification('test',true);
  assert.equal($('comfortNotificationStatus').hidden,true);
  renderComfort({...active,active:false});
  assert.equal($('sessionStart').disabled,false);
  assert.equal($('sessionMinutes').disabled,false);
  assert.equal($('sessionCancel').disabled,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', setup + code + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_finished_session_leaves_the_defaults(self):
        """A one-minute test session that has ended mustn't fill the form with 1 / 0 / 0."""
        page = (ROOT / 'ui/index.html').read_text(encoding='utf-8')
        code = page[page.index('let comfortBusy ='):page.index('async function pollComfort()')]
        setup = r'''
const assert = require('node:assert/strict');
const elements = new Map();
const $ = id => {
  // The form's own defaults, as in the page's HTML.
  const value = {sessionMinutes:'30', breakMinutes:'20', stillMinutes:'30'}[id] || '';
  if (!elements.has(id)) elements.set(id, {textContent:'', hidden:true, disabled:false, value, defaultValue:value,
    checked:true, defaultChecked:true, type: /Alert$/.test(id) ? 'checkbox' : 'number'});
  return elements.get(id);
};
const window = {frameApp:{notify:async()=>{}}};
const log = ()=>{}, toast = ()=>{};
'''
        checks = r'''
renderComfort({id:'old', active:false, time:100, options:{minutes:1,breakMinutes:0,stillMinutes:0,batteryAlert:false,heatAlert:false},
  events:[{id:'old:1',kind:'finished',time:90,message:'Session ended'}]});
assert.equal($('sessionMinutes').value, '30');
assert.equal($('breakMinutes').value, '20');
assert.equal($('batteryAlert').checked, true);
assert.match($('comfortEvents').textContent, /Session ended/);
assert.notEqual($('comfortEvents').textContent, 'Session ended');  // it carries a time
renderComfort({id:'new', active:true, time:200, remaining:600, options:{minutes:45,breakMinutes:15,stillMinutes:20,batteryAlert:true,heatAlert:false}, events:[]});
assert.equal($('sessionMinutes').value, 45);  // a running session shows its own settings
assert.equal($('heatAlert').checked, false);
// The page stays open while that session ends: the next one starts from the defaults again.
renderComfort({id:'new', active:false, time:900, options:{minutes:45,breakMinutes:15,stillMinutes:20,batteryAlert:true,heatAlert:false},
  events:[{id:'new:1',kind:'finished',time:899,message:'Session ended'}]});
assert.equal($('sessionMinutes').value, '30');
assert.equal($('breakMinutes').value, '20');
assert.equal($('heatAlert').checked, true);
renderComfort({id:'new', active:false, time:905, options:{minutes:45}, events:[]});
$('sessionMinutes').value = '50';  // what's typed for the next session
renderComfort({id:'new', active:false, time:910, options:{minutes:45}, events:[]});
assert.equal($('sessionMinutes').value, '50');  // later polls leave it alone
'''
        result = subprocess.run(['node', '-e', setup + code + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_poll_waits_while_the_frame_is_unreachable(self):
        page = (ROOT / 'ui/index.html').read_text(encoding='utf-8')
        start = page.index('async function pollComfort()')
        code = page[start:page.index('$("comfortForm").onsubmit', start)]
        js = r'''
const assert = require('node:assert/strict');
const el = {textContent: 'Checking session…'};
const $ = () => el;
let online = false, comfortBusy = false, comfortChanging = 0, comfortRevision = 0, devGen = 0, calls = 0, timers = 0;
const api = async () => { calls++; return {}; };
const renderComfort = () => {};
const setTimeout = () => { timers++; };
''' + code + r'''
(async () => {
  await pollComfort();
  assert.equal(calls, 0);  // no ssh attempt while the status check can't reach the Frame
  assert.match(el.textContent, /when the Frame is connected/);
  assert.equal(timers, 1);  // still scheduled, to resume when it's back
  online = true;
  await pollComfort();
  assert.equal(calls, 1);
  online = null;  // a status check that failed for another reason: keep polling
  await pollComfort();
  assert.equal(calls, 2);
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', js], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
