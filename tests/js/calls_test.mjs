// What one part of the page offers the rest, by name (shared/calls.mjs, #94).
// The tabs and the shared modules once reached each other through window
// globals, and what a caller got when the other tab had not loaded was
// whatever its own check said, or nothing at all.
//
// The registry: a name nothing has offered answers undefined and says so; an
// offer is called with what it is given; offered again, the later answers.
// It is one for the page, even when the shared modules load twice. And with
// all three tabs loaded, every name the page calls has been offered.
import { readdirSync, readFileSync } from 'node:fs';
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
for (const tab of ['tab_civitai_browser.py', 'tab_generations.py']) {
    const source = readFileSync(`${ROOT}/model_manager/ui/${tab}`, 'utf8');
    document.body.insertAdjacentHTML('beforeend', source.match(/gr\.HTML\(\s*("""|''')([\s\S]*?)\1/)[2]);
}
const { check, done } = checker();

const warned = [];
const warn = console.warn;
console.warn = (...args) => warned.push(args.join(' '));

const { provide, ready, call } = await import(`file:///${ROOT}/javascript/shared/calls.mjs?one`);
check('a name nothing has offered is not ready', ready('test.echo'), false);
check('and calling it answers undefined', call('test.echo', 1) === undefined, true);
check('saying so', warned, ['[ModelManager] test.echo is not ready: its tab has not loaded']);

provide('test.echo', (...args) => args);
check('offered, it is ready', ready('test.echo'), true);
check('and called with what it is given', call('test.echo', 1, 'two', { three: 3 }), [1, 'two', { three: 3 }]);
provide('test.echo', () => 'later');
check('offered again, the later one answers', call('test.echo'), 'later');

// Without the server's version each tab imports its own copy of the shared
// modules: one tab's offers still reach the others.
const other = await import(`file:///${ROOT}/javascript/shared/calls.mjs?two`);
check('another copy of the module is another module', other.call === call, false);
check('but the same registry', other.call('test.echo'), 'later');

// ---------------------------------------------- every name the page calls
globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async () => ({ ok: true, json: async () => ({ success: true }) });
await import(`file:///${ROOT}/javascript/model_manager.mjs`);
await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
await import(`file:///${ROOT}/javascript/generations.mjs`);

const files = [...readdirSync(`${ROOT}/javascript`).filter((f) => f.endsWith('.mjs')),
               ...readdirSync(`${ROOT}/javascript/shared`).filter((f) => f.endsWith('.mjs')).map((f) => `shared/${f}`)];
const called = new Set();
for (const file of files) {
    const source = readFileSync(`${ROOT}/javascript/${file}`, 'utf8');
    for (const m of source.matchAll(/\b(?:call|ready)\(\s*'([^']+)'/g)) called.add(m[1]);
}
check('the page calls names between its parts', called.size > 0, true);
check('and with the tabs loaded, each has been offered', [...called].filter((name) => !ready(name)), []);
check('the settings window offers each tab\'s card preview a place',
      ['cardPreview.model_manager_card_size', 'cardPreview.model_manager_civitai_card_size'].map(ready), [true, true]);

console.warn = warn;
done();
