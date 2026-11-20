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
  setTimeout(){throw Error('Unsupported picker must not start a bridge request');},clearTimeout(){},
  fetch(){throw Error('Unsupported picker must not reach the network');},console,DOMException});
vm.runInContext(source,context);
const startupMessages=messages.length;
const connect=window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit.connect;
const unsupported=/Decky file picker is not supported on Frame/;

// LocalSend chains .then directly on Decky's promise. An absent method throws
// inside its executor and bypasses its normal cancellation rejection branch.
const localSend=readFileSync(process.argv[2],'utf8');
assert.match(localSend,/\.then\(resolve, \(\) => reject\('User Canceled'\)\)/);
for(const version of [1,2]){
  const modern=connect(version,'fixture');
  context.openFilePicker=modern.openFilePicker;
  const fileOpener=vm.runInContext(localSend+'\nfileOpener;',context);
  for(const folder of [false,true]){
    await assert.rejects(fileOpener('/fixture',true,undefined,{},folder),
      error=>error==='User Canceled','published wrapper must take its rejection handler');
  }
  // Preserve an actionable reason for plugins that display the API error.
  let reply;
  assert.doesNotThrow(()=>{reply=modern.openFilePicker(0,'/fixture',true,true);});
  assert.equal(typeof reply.then,'function','picker must return a promise');
  await assert.rejects(reply,unsupported);
}

// CSS Loader's legacy helper forwards this rejected promise unchanged.
context.server=window.legacyAPI;
const cssLoader=readFileSync(process.argv[3],'utf8');
assert.match(cssLoader,/return await server\.openFilePicker\(path, true\)/);
const legacyHelper=vm.runInContext('('+cssLoader+')',context);
await assert.rejects(legacyHelper('/fixture'),unsupported);
for(const method of ['openFilePicker','openFilePickerV2']){
  let reply;
  const args=method==='openFilePicker' ? ['/fixture',true] : [0,'/fixture',true,true];
  assert.doesNotThrow(()=>{reply=window.legacyAPI[method](...args);});
  assert.equal(typeof reply.then,'function');
  await assert.rejects(reply,unsupported);
}
assert.equal(messages.length,startupMessages,'unsupported pickers must not call a backend');
assert.equal(window.localStorage.length,0,'failed selection must not change cached settings');
console.log('Framey file picker proof: '+JSON.stringify({passed:true,
  publishedModernRejectionHandled:true,publishedLegacyRejectionHandled:true,
  modernVersions:[1,2],legacyMethods:['openFilePicker','openFilePickerV2'],
  backendContacted:false,realFrameContacted:false,wornVRVerified:false}));
