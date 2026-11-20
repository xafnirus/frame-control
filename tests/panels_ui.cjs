// Execute the shipped headset page with controlled response ordering; no headset.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2] === '-' ? 0 : process.argv[2], 'utf8');

function page({hash='#fixture-key', readKey=()=>null, writeKey=()=>{}}={}) {
  const elements = new Map();
  const requests = [];
  const element = () => ({textContent:'', disabled:false, children:[],
    replaceChildren() { this.children = []; }, append(child) { this.children.push(child); }});
  const get = id => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const locations = [];
  const context = {
    document:{getElementById:get, createElement:element},
    location:{hash, pathname:'/'}, history:{replaceState(...args){locations.push(args);}},
    sessionStorage:{getItem:readKey, setItem:writeKey}, window:{close(){}},
    fetch:(path, options) => new Promise(resolve => requests.push({path, options, resolve})),
  };
  vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  const answer = (index, data, ok=true) => requests[index].resolve({ok, json:async () => data});
  const flush = () => new Promise(resolve => setImmediate(resolve));
  return {get, requests, answer, flush, locations};
}

(async () => {
  // A startup response arriving after a user refresh must not resurrect old panels.
  const first = page();
  const newer = first.get('refresh').onclick();
  first.answer(1, {panels:[{key:'current', title:'Current <panel>'}]});
  await newer;
  first.answer(0, {panels:[{key:'closed', title:'Already closed'}]});
  await first.flush();
  assert.deepEqual(first.get('panels').children.map(b => b.textContent), ['Current <panel>']);
  const selected = first.get('panels').children[0].onclick();
  assert.deepEqual(JSON.parse(first.requests[2].options.body), {key:'current'});
  first.answer(2, {message:'Asked SteamVR to show the panel.'});
  await selected;
  assert.equal(first.get('status').textContent, 'Asked SteamVR to show the panel.');

  // An old failure must not cover the newer successful empty result.
  const second = page();
  const empty = second.get('refresh').onclick();
  second.answer(1, {panels:[]});
  await empty;
  second.answer(0, {error:'Old connection failed'}, false);
  await second.flush();
  assert.equal(second.get('status').textContent, 'No open panels.');

  // A late old success must not hide the most recent refresh failure.
  const third = page();
  const failed = third.get('refresh').onclick();
  third.answer(1, {error:'Current connection failed'}, false);
  await failed;
  third.answer(0, {panels:[{key:'stale', title:'Stale'}]});
  await third.flush();
  assert.equal(third.get('status').textContent, 'Current connection failed');
  assert.equal(third.get('panels').children.length, 0);

  // A blocked tab-storage write must not discard the launch key or prevent
  // the real page from initializing its authenticated list/focus controls.
  const deniedWrite = page({writeKey(){throw Error('tab storage denied');}});
  assert.equal(deniedWrite.requests[0].options.headers['X-Panel-Key'], 'fixture-key');
  assert.deepEqual(deniedWrite.locations, [[null,'','/']]);
  deniedWrite.answer(0, {panels:[{key:'current',title:'Current panel'}]});
  await deniedWrite.flush();
  const focus = deniedWrite.get('panels').children[0].onclick();
  assert.equal(deniedWrite.requests[1].options.headers['X-Panel-Key'], 'fixture-key');
  assert.deepEqual(JSON.parse(deniedWrite.requests[1].options.body), {key:'current'});
  deniedWrite.answer(1, {message:'Asked SteamVR to show the panel.'});
  await focus;
  assert.equal(deniedWrite.get('status').textContent, 'Asked SteamVR to show the panel.');

  // A reload without either a fragment or readable storage must show the
  // ordinary unauthenticated error, not stop before the controls are wired.
  const deniedRead = page({hash:'',readKey(){throw Error('tab storage denied');}});
  assert.equal(deniedRead.requests[0].options.headers['X-Panel-Key'], '');
  deniedRead.answer(0, {error:'Open the switcher from Frame Control.'}, false);
  await deniedRead.flush();
  assert.equal(deniedRead.get('status').textContent, 'Open the switcher from Frame Control.');
  assert.equal(typeof deniedRead.get('refresh').onclick, 'function');
  assert.equal(typeof deniedRead.get('close').onclick, 'function');

  // Normal reloads still read the same tab's key.
  const restored = page({hash:'',readKey:()=> 'saved-key'});
  assert.equal(restored.requests[0].options.headers['X-Panel-Key'], 'saved-key');
  console.log('Panel refresh response ordering: pass');
})().catch(error => { console.error(error); process.exitCode=1; });
