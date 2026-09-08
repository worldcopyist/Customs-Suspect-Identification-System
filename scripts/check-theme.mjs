import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../ui/theme.js', import.meta.url), 'utf8');
function harness(saved, blocked = false) {
  const listeners = {}, system = {matches: false, addEventListener: (_, fn) => listeners.system = fn};
  const root = {dataset: {}, style: {}}, select = {id: 'theme-select', value: ''};
  const storage = {value: saved, getItem() {if(blocked) throw Error(); return this.value;}, setItem(_, v) {if(blocked) throw Error(); this.value = v;}};
  vm.runInNewContext(source, {window: {matchMedia: () => system, addEventListener: (e, fn) => listeners[e] = fn}, document: {documentElement: root, getElementById: () => select, addEventListener: (e, fn) => listeners[e] = fn}, localStorage: storage});
  return {root, system, listeners, storage, choose(value) {select.value = value; listeners.change({target: select});}};
}
const h = harness(null);
assert.equal(h.root.dataset.theme, 'light');
h.system.matches = true; h.listeners.system(); assert.equal(h.root.dataset.theme, 'dark');
h.choose('light'); h.listeners.system(); assert.equal(h.root.dataset.theme, 'light');
assert.equal(harness(h.storage.value).root.dataset.theme, 'light');
h.choose('system'); assert.equal(h.root.dataset.theme, 'dark');
h.listeners.storage({key: 'customs-ui-theme', newValue: 'light'}); assert.equal(h.root.dataset.theme, 'light');
h.listeners.storage({key: null, newValue: null}); assert.equal(h.root.dataset.theme, 'dark');
const blocked = harness(null, true); blocked.choose('dark'); assert.equal(blocked.root.dataset.theme, 'dark');
assert.equal(harness('invalid').root.dataset.theme, 'light');
console.log('PASS: system changes, manual override, persistence, cross-tab sync and blocked storage');
