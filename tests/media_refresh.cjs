// Exercise the shipped API, action wrapper and media handlers with deferred HTTP.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');

function page() {
  const elements = new Map(), requests = [], notifications = [];
  const get = id => {
    if (!elements.has(id)) {
      elements.set(id, {
      textContent: id === 'mediaState' ? 'Current display' : '', value:'', disabled:false,
      children:[], replaceChildren() { this.children = []; this.value = ''; },
      add(option) { this.children.push(option); if (this.children.length === 1) this.value = option.value; },
      });
      if (id === 'mediaFile') elements.get(id).add({text:'Refresh to load your media', value:''});
    }
    return elements.get(id);
  };
  const context = {
    $:get, UI_KEY:'fixture-key', window:{connDevice:'frame-a'},
    Option:function(text, value) { this.text = text; this.value = value; },
    fetch:(path, options) => new Promise((resolve, reject) => requests.push({path, options, resolve, reject})),
    log(){}, toast:(message, error=false) => notifications.push({message, error}),
    setOnline(){}, setTimeout(){},
  };
  const api = html.slice(html.indexOf('let devGen = 0;'), html.indexOf('// What a panel shows'));
  const act = html.slice(html.indexOf('async function act('), html.indexOf('function setConn('));
  const media = html.slice(html.indexOf('function copyToDownloads('), html.indexOf('let apkLookup ='));
  vm.createContext(context);
  vm.runInContext(api + '\n' + act + '\n' + media, context);
  return {
    get, requests, notifications,
    refresh:selectId => context.refreshMedia(selectId),
    answer:(index, data, ok=true) => requests[index].resolve({ok, status:ok ? 200 : 500, json:async()=>data}),
    switchHeadset() { context.window.connDevice = 'frame-b'; vm.runInContext('devGen++', context); },
    flush:() => new Promise(resolve => setImmediate(resolve)),
  };
}
const snapshot = (name, state='playing') => ({files:[{id:name, name:name+'.mp4'}], player:{state, file:name+'.mp4'}});
const assertDisplay = (p, name, state='playing') => {
  assert.deepEqual(Array.from(p.get('mediaFile').children,o=>o.text), [name+'.mp4']);
  assert.equal(p.get('mediaFile').value, name);
  assert.equal(p.get('mediaState').textContent, state+': '+name+'.mp4');
};

const cases = {
  async newer_success() {
    const p=page(), old=p.refresh('old'), current=p.refresh('current');
    p.answer(1, snapshot('current')); await current;
    p.answer(0, snapshot('old')); await old;
    assertDisplay(p, 'current');
  },
  async obsolete_failure() {
    const p=page();
    // The delayed read after Play has this error handler; Refresh can overlap it.
    const old=p.refresh().catch(e=>{p.get('mediaState').textContent=e.message;});
    const current=p.get('mediaRefresh').onclick();
    p.answer(1, snapshot('current')); await current;
    p.answer(0, {error:'Obsolete list failed'}, false); await old;
    assertDisplay(p, 'current');
    assert.equal(p.notifications.filter(n=>n.error).length, 0);
    assert.equal(p.get('mediaRefresh').disabled, false);
  },
  async current_failure() {
    const p=page(), old=p.refresh(), current=p.get('mediaRefresh').onclick();
    p.answer(1, {error:'Current list failed'}, false); await current;
    p.answer(0, snapshot('old')); await old;
    assert.equal(p.get('mediaState').textContent, 'Current display');
    assert.deepEqual(Array.from(p.get('mediaFile').children,o=>o.text), ['Refresh to load your media']);
    assert.deepEqual(p.notifications, [{message:'Refresh media failed: Current list failed', error:true}]);
  },
  async stop_refresh() {
    const p=page(), old=p.refresh(), stop=p.get('mediaStop').onclick();
    assert.deepEqual(JSON.parse(p.requests[1].options.body), {action:'stop'});
    p.answer(1, {message:'Stopped'}); await p.flush();
    assert.deepEqual(JSON.parse(p.requests[2].options.body), {action:'list'});
    p.answer(2, snapshot('current', 'stopped')); await stop;
    p.answer(0, snapshot('old')); await old;
    assertDisplay(p, 'current', 'stopped');
    assert.equal(p.get('mediaStop').disabled, false);
  },
  async switched_success() {
    const p=page(), old=p.get('mediaRefresh').onclick();
    p.switchHeadset(); const current=p.refresh();
    p.answer(1, snapshot('current')); await current;
    p.answer(0, snapshot('old')); await old;
    assertDisplay(p, 'current');
    assert.equal(p.notifications.filter(n=>n.error).length, 0);
    assert.deepEqual(p.requests.map(r=>r.options.headers['X-Frame-Device']), ['frame-a','frame-b']);
    assert.ok(p.requests.every(r=>r.path==='/api/media' && r.options.headers['X-Frame-UI']==='fixture-key'));
  },
  async switched_transport_failure() {
    const p=page(), old=p.get('mediaRefresh').onclick();
    p.switchHeadset(); const current=p.refresh();
    p.answer(1, snapshot('current')); await current;
    p.requests[0].reject(Error('Old headset connection lost')); await old;
    assertDisplay(p, 'current');
    assert.equal(p.notifications.filter(n=>n.error).length, 0);
  },
};
(async()=>{
  const name=process.argv[3];
  assert.ok(cases[name], 'Unknown media scenario');
  await cases[name]();
  console.log('Media response ordering: '+name+' passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
