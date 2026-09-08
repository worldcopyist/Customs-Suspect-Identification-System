import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = new URL('..', import.meta.url);
const read = relative => fs.readFileSync(new URL(relative, root), 'utf8');
const files = ['ui/intro/animitor.html', 'ui/intro/xuanzhuan.html'];
for (const file of files) {
  const source = read(file);
  assert.ok(!/<script\b/i.test(source), `${file} must not execute script`);
  assert.ok(!/https?:\/\//i.test(source), `${file} must not load external resources`);
}
for (const file of ['background.jpeg', 'texture.jpg', 'portrait-a.png', 'portrait-b.png', 'portrait-c.png']) {
  assert.ok(fs.statSync(path.join(fileURLToPath(new URL('assets/startup-animation/', root)), file)).isFile(), `missing startup asset ${file}`);
}
const core = read('ui/core.js');
assert.match(core, /await playStartAnimation\(\);showAuth\('login'/, 'anonymous boot must play the intro before login');
console.log('PASS: startup animations have no script/external resources and anonymous login awaits them');
