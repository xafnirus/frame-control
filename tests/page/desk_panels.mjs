// The live view's Desktop panel list (#73), run in node against the real functions from
// ui/index.html with a fake server: the headset's reason when it lists no panels, a failed
// listing shown (first time too) rather than "Finding…", and recovery after it.
import { readFileSync } from "fs";
import assert from "node:assert/strict";
const src = readFileSync(process.argv[2] || new URL("../../ui/index.html", import.meta.url), "utf8");
const grab = name => {
  const m = src.match(new RegExp(`(?:\\nconst ${name} = [^\\n]*\\n)|((?:async )?function ${name}\\([\\s\\S]*?\\n}\\n)`));
  if (!m) throw new Error("not found: " + name);
  return m[0];
};
// The page's scripts share one global scope, so a second loadPanels would silently replace
// the Desktop view's (what broke #73 until #84): the one grabbed here must be the only one.
for (const name of ["loadPanels", "noPanelWhy", "deskPanel", "ctrlTarget"]) {
  const count = (src.match(new RegExp(`\\n(?:async )?function ${name}\\(`, "g")) || []).length;
  if (count !== 1) { console.log(`FAIL ${name} is defined ${count} times`); process.exit(1); }
}
const code = ["desk", "panelKey", "noPanelWhy", "deskPanel", "loadPanels", "watchPanels", "ctrlTarget"].map(grab).join("");
const fail = msg => { console.log("FAIL " + msg); process.exit(1); };

function page(answer) {
  const calls = [], logged = [], timers = new Map();
  let nextTimer = 1;
  const env = {
    view: "flat", live: false, ctrlMode: () => "abs", renderPanelPick: () => {}, toggleLive: () => {}, ctrlShow: () => {},
    document: {hidden: false},
    setTimeout: (fn, delay) => { const id=nextTimer++; timers.set(id,{fn,delay}); return id; },
    clearTimeout: id => timers.delete(id),
    log: (m) => logged.push(m),
    api: async (path, body) => { calls.push([path, body]); return answer(); },
  };
  const fns = new Function(...Object.keys(env), `${code}
    return { desk, noPanelWhy, loadPanels, watchPanels, ctrlTarget,
      setView: value => { view=value; } };`)(...Object.values(env));
  return { ...fns, calls, logged, timers };
}

// The Desktop view asks for the headset's panels with a plain GET (no switcher action).
{
  const p = page(() => ({ panels: [], focus: null, why: "The headset's desktop is running, but SteamOS isn't listing it as a panel." }));
  if (p.ctrlTarget().why !== "Finding the headset's panels…") fail("before loading: " + p.ctrlTarget().why);
  await p.loadPanels();
  if (!(p.calls.length === 1 && p.calls[0][0] === "/api/panels" && p.calls[0][1] === undefined))
    fail("request " + JSON.stringify(p.calls));
  if (!p.desk.loaded) fail("not marked loaded");
  if (!p.noPanelWhy().startsWith("The headset's desktop is running")) fail("why for capture: " + p.noPanelWhy());
  if (!p.ctrlTarget().why.startsWith("The headset's desktop is running")) fail("why for control: " + p.ctrlTarget().why);
}
// An unreadable list is unknown: both Capture and Control retain that distinction.
{
  const why = "Frame Control couldn't read gamescope's panel list, so it can't tell whether an app panel is open. " +
    "Check that SteamVR is running in the headset, then try again or use the Headset view. " +
    "If this persists, report your SteamOS version and this exact message.";
  const p = page(() => ({ panels: [], focus: null, why }));
  await p.loadPanels();
  if (p.noPanelWhy() !== why || p.ctrlTarget().why !== why) fail("unreadable list reason lost");
}
// An older headset script without "why": the generic advice.
{
  const p = page(() => ({ panels: [], focus: null }));
  await p.loadPanels();
  if (!p.noPanelWhy().startsWith("No app panel is open in the headset. Open the desktop")) fail("generic: " + p.noPanelWhy());
}
// The first listing fails: Control and Capture say so (logged once), then recover.
{
  let broken = true;
  const p = page(() => {
    if (broken) throw new Error("Timed out talking to frame");
    return { panels: [{ window: 7, display: ":0", name: "Desktop" }], focus: 7, focus_display: ":0" };
  });
  await p.loadPanels(); await p.loadPanels();
  const why = p.ctrlTarget().why;
  if (why !== "Couldn't list the headset's panels: Timed out talking to frame") fail("initial failure in Control: " + why);
  if (p.noPanelWhy() !== why) fail("initial failure in Capture: " + p.noPanelWhy());
  if (p.logged.length !== 1) fail("logged " + p.logged.length + " times");
  broken = false;
  await p.loadPanels();
  if (p.desk.error) fail("error kept after recovery");
  const t = p.ctrlTarget();
  if (!t.why || t.why.includes("Couldn't list")) fail("after recovery: " + JSON.stringify(t));
  if (p.desk.panels.length !== 1) fail("panels after recovery");
}
// Waiting for the Frame: shown in Control, not logged every poll. An answer about the
// previous headset (stale) is ignored.
{
  let err;
  const p = page(() => { throw err; });
  err = Object.assign(new Error("Can't reach the Frame"), { offline: true });
  await p.loadPanels(); await p.loadPanels();
  if (p.logged.length) fail("offline logged: " + p.logged);
  if (p.ctrlTarget().why !== "Couldn't list the headset's panels: Can't reach the Frame") fail("offline: " + p.ctrlTarget().why);
  const q = page(() => { throw Object.assign(new Error("old headset"), { offline: true, stale: true }); });
  await q.loadPanels();
  if (q.logged.length || q.desk.error) fail("stale answer used: " + q.desk.error);
  if (q.ctrlTarget().why !== "Finding the headset's panels…") fail("stale: " + q.ctrlTarget().why);
}
// Deferred reads and the real polling functions reproduce overlap in both orders.
const failures = [];
for (const scenario of ["late_success", "late_error", "new_error", "duplicate_poll"]) {
  try {
    const pending = [];
    const p = page(() => new Promise((resolve,reject) => pending.push({resolve,reject})));
    if (scenario === "duplicate_poll") {
      p.watchPanels();
      p.setView("headset"); p.setView("flat"); p.watchPanels();
      pending[1].resolve({panels:[],focus:null});
      await new Promise(resolve=>setImmediate(resolve));
      pending[0].resolve({panels:[],focus:null});
      await new Promise(resolve=>setImmediate(resolve));
      assert.equal(p.timers.size,1,"only the current poll chain may reschedule");
      const [id,timer] = [...p.timers][0];
      assert.equal(timer.delay,3000);
      p.timers.delete(id); timer.fn();
      pending[2].resolve({panels:[],focus:null});
      await new Promise(resolve=>setImmediate(resolve));
      assert.equal(p.timers.size,1,"the single chain must keep polling");
      p.setView("headset");
      const next = [...p.timers.values()][0]; next.fn();
      assert.equal(p.calls.length,3,"no request outside Desktop view");
    } else {
      const old = p.loadPanels(), current = p.loadPanels();
      const snapshot = window => ({panels:[{window,display:":0",name:String(window)}],focus:window,focus_display:":0"});
      if (scenario === "new_error") pending[1].reject(new Error("Current failure"));
      else pending[1].resolve(snapshot(9));
      await current;
      if (scenario === "late_error") pending[0].reject(new Error("Old failure"));
      else pending[0].resolve(snapshot(7));
      if (scenario !== "new_error") { p.desk.pick=":0/9"; p.desk.shown=":0/9"; }
      await old;
      if (scenario === "new_error") {
        assert.equal(p.desk.error,"Current failure");
        assert.equal(p.desk.panels.length,0,"old success cannot hide a current failure");
      } else {
        assert.equal(p.desk.panels[0].window,9,"old list must not replace current panels");
        assert.equal(p.desk.pick,":0/9");
        assert.equal(p.desk.error,"");
        assert.equal(p.ctrlTarget().panel.window,9,"control target stays on current panel");
      }
    }
  } catch (error) { failures.push({scenario,error:String(error)}); }
}
assert.deepEqual(failures,[]);
console.log("ok");
