import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const host=readFileSync(new URL('../../ui/framey-host.js',import.meta.url),'utf8');
const source=host.replace(/\n  start\(\);\n\}\)\(\);\s*$/,
  '\n  window.legacyAPI = legacyServerAPI;\n})();');
assert.notEqual(source,host);
const messages=[];
const window={React:{Fragment:'fragment',Component:class {},forwardRef:render=>render,
  createElement:()=>({}),isValidElement:()=>true},ReactDOM:{createRoot:()=>({render(){}})}};
const context=vm.createContext({window,document:{getElementById:()=>({})},navigator:{language:'en'},
  parent:{postMessage:message=>messages.push(message)},addEventListener(){},
  setTimeout(){throw Error('Unsupported fetch must not start a bridge request');},clearTimeout(){},
  fetch(){throw Error('Unsupported fetch must not reach the network');},console,DOMException});
vm.runInContext(source,context);
const legacy=window.legacyAPI;
const startupMessages=messages.length;
// Replay only the exact published login getter, with synthetic settings. Its
// failure branch expects a legacy reply envelope rather than a rejected call.
const getter=readFileSync(process.argv[2],'utf8');
assert.match(getter,/get loggedIn\(\)/);
assert.match(getter,/authenticated\.success/);
const prototype=vm.runInContext('({'+getter+'})',context);
let writes=0;
const model=Object.assign(Object.create(prototype),{_login:false,serverAPI:legacy,
  settings:{retroachievements:{username:'fixture-user',api_key:'fixture-key'},
    writeSettings:()=>{writes++;}}});
assert.equal(await model.loggedIn,false,'published login must take its ordinary failure path');
assert.equal(writes,0,'unsupported authentication must not save settings');
assert.equal(model._login,false);
for(const options of [undefined,{method:'GET'},{method:'POST',body:'fixture'}]){
  const reply=await legacy.fetchNoCors('https://example.invalid/private',options);
  assert.deepEqual(Object.keys(reply).sort(),['result','success']);
  assert.equal(reply.success,false,'an unsupported proxy must not claim a successful request');
  assert.match(reply.result,/not supported on Frame/);
}

// API v1/v2 proxy fetch has the newer rejected-promise contract. Changing the
// legacy result must not silently change the modern API's failure shape.
for(const version of [1,2]){
  const modern=window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit.connect(version,'fixture');
  await assert.rejects(modern.fetchNoCors('https://example.invalid/private'),/unavailable in Framey/);
}
assert.equal(messages.length,startupMessages,'neither API may forward an unsupported request');
console.log('Framey legacy fetch proof: '+JSON.stringify({passed:true,legacyFailureEnvelope:true,
  publishedLoginFailureHandled:true,noSettingsWritten:true,modernRejectionPreserved:true,
  networkContacted:false,backendContacted:false,realFrameContacted:false,wornVRVerified:false}));
