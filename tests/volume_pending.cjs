// Deferred requests run the shipped API, volume input and status-render code.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');

function page() {
  const nodes = new Map(), timers = new Map(), requests = [], errors = [];
  let nextTimer = 1;
  const get = id => {
    if (!nodes.has(id)) {
      let value='20';
      nodes.set(id, {get value(){return value;},set value(v){value=String(v);},
        textContent:'',style:{setProperty(){}}});
    }
    return nodes.get(id);
  };
  const context = {
    window:{connDevice:'frame-a'}, UI_KEY:'fixture', volTimer:null,
    $:get, setOnline(){}, toast:(message, error)=>errors.push({message,error}),
    setTimeout(fn, delay) { assert.equal(delay,250); const id=nextTimer++; timers.set(id,fn); return id; },
    clearTimeout(id) { timers.delete(id); },
    fetch:(path, options)=>new Promise((resolve,reject)=>requests.push({path,options,resolve,reject})),
  };
  vm.createContext(context);
  const api = source.slice(source.indexOf('let devGen = 0;'),source.indexOf('// What a panel shows'));
  const volume = source.slice(source.indexOf('function setVolume('),source.indexOf('$("muteBtn").onclick'));
  const status = source.match(/if \(s\.volume && !volTimer\) setVolume\([^\n]+/)[0];
  vm.runInContext(api+'\n'+volume,context);
  return {
    requests, errors, get, timers,
    input(level) { get('vol').value=String(level); get('vol').oninput(); return context.volTimer; },
    pending:()=>context.volTimer,
    fire(id) { const fn=timers.get(id); assert.ok(fn,'timer is pending'); timers.delete(id); return fn(); },
    reply(index, ok=true) { requests[index].resolve({ok,status:ok?200:500,json:async()=>ok?{}:{error:'Write failed'}}); },
    status(level) { context.s={volume:{level,muted:false}}; vm.runInContext(status,context); },
    switchHeadset() {
      context.window.connDevice='frame-b'; vm.runInContext('devGen++',context);
      // These are the shipped connection handler's cancellation statements.
      const cancel=source.match(/clearTimeout\(volTimer\); volTimer = null;[^\n]*/)[0];
      vm.runInContext(cancel,context);
    },
  };
}

async function overlap(failed, switched) {
  const p=page(), first=p.input(40), old=p.fire(first);
  assert.equal(p.requests.length,1);
  if (switched) p.switchHeadset();
  const latest=p.input(80);
  p.reply(0,!failed); await old;
  assert.equal(p.pending(),latest,'old completion must not release the newer draft');
  p.status(.2);
  assert.equal(p.get('vol').value,'80','status must not replace the pending draft');
  const current=p.fire(latest);
  assert.equal(JSON.parse(p.requests[1].options.body).level,.8);
  assert.equal(p.requests[1].options.headers['X-Frame-Device'],switched?'frame-b':'frame-a');
  p.reply(1); await current;
  assert.equal(p.pending(),null);
  p.status(.8); assert.equal(p.get('volNum').textContent,'80%');
}

const cases = {
  success:()=>overlap(false,false),
  failure:()=>overlap(true,false),
  switched_success:()=>overlap(false,true),
  switched_failure:()=>overlap(true,true),
  async debounce() {
    const p=page(), first=p.input(40), latest=p.input(80);
    assert.equal(p.timers.has(first),false);
    const current=p.fire(latest);
    assert.equal(p.requests.length,1);
    assert.equal(JSON.parse(p.requests[0].options.body).level,.8);
    p.reply(0,false); await current;
    assert.equal(p.pending(),null);
    assert.deepEqual(p.errors,[{message:'Write failed',error:true}]);
  },
  async switch_cancels_pending() {
    const p=page(), pending=p.input(80); p.switchHeadset();
    assert.equal(p.timers.has(pending),false);
    assert.equal(p.pending(),null); assert.equal(p.requests.length,0);
    p.status(.2); assert.equal(p.get('volNum').textContent,'20%');
  },
};
(async()=>{await cases[process.argv[3]]();})().catch(error=>{console.error(error);process.exitCode=1;});
