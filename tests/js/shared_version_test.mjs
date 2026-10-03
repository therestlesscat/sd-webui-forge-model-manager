// The shared modules under one version (#53). Each tab asked for them with
// its own ?mtime, so a release that changed only a shared file left every
// URL as it was, and a browser could serve the copy it held - Gradio's file
// route sends no Cache-Control. And three tabs, three versions: each shared
// module ran once per tab.
//
// Here one tab script is loaded twice, under two versions, as two tabs
// stamped at different mtimes are. ui_options.mjs registers one
// onAfterUiUpdate callback when it runs; counted, they say how many copies ran.
//
// And a page loaded before the extension's routes are added (#121): one
// reloaded by "Apply and restart UI" comes back as soon as the WebUI's own
// /internal/ping answers, and that is added before the extensions'
// app_started. The version request failed, and each tab fell back to its own
// version - a copy of every shared module per tab, and with them a downloads
// list, a note pile and an update check per tab, for the whole session. Now
// the tabs ask until the routes answer, then load once, under that version.
import { readFileSync } from 'node:fs';
import { ROOT, checker, mountTab } from './harness.mjs';

mountTab('model_manager/ui/tab_generations.py');
const { check, done } = checker();

const commonCopies = [];
globalThis.onAfterUiUpdate = (fn) => {
    if (String(fn).includes('apiKeyBanners')) commonCopies.push(fn);
};

const asked = [];
let version = { success: true, version: '1700000000' };
let notYet = 0;                 // requests answered 404, as before app_started
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/asset-version')) {
        asked.push(href);
        if (notYet > 0) {
            notYet -= 1;
            return { ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) };
        }
        return { ok: true, json: async () => version };
    }
    return { ok: true, json: async () => ({ success: true, generations: [], groups: [], total: 0 }) };
};

await import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-1`);
await import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-2`);
check('two tabs at different versions run the shared module once', commonCopies.length, 1);
check('asking the server for its version once', asked.length, 1);

// Before the routes exist: not answered twice, then answered.
delete window.mmSharedVersion;
asked.length = 0;
notYet = 2;
version = { success: true, version: '1700000999' };
const said = [];
const log = console.log;
console.log = (...args) => { said.push(args.join(' ')); log(...args); };
const loading = Promise.all([import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-3`),
                             import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-4`)]);
await new Promise((resolve) => setTimeout(resolve, 250));
check('while the routes are not there, no tab runs a copy of its own', commonCopies.length, 1);
check('saying, once, what it waits for', said.filter((line) => /waiting for the Model Manager's API/.test(line)).length, 1);
await loading;
console.log = log;
check('once they answer, both tabs run one copy, under the server\'s version', commonCopies.length, 2);
check('asked until answered, and no more', asked.length, 3);

// Answered, but with no version to use: nothing to wait for. The first tab's
// own version, for every tab - still one copy.
delete window.mmSharedVersion;
asked.length = 0;
version = { success: false };
await Promise.all([import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-5`),
                   import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-6`)]);
check('an answer without a version is not waited on: one ask, one copy for both tabs',
      [asked.length, commonCopies.length], [1, 3]);

// The three tabs ask the same way: the lines are each tab's own, as the
// shared modules cannot be loaded before they have run.
const snippet = (file) => (readFileSync(`${ROOT}/javascript/${file}`, 'utf8')
    .match(/window\.mmSharedVersion \|\|=[\s\S]*?\nconst shared = [^\n]*/) || [''])[0];
check('the three tabs ask for the version in the same lines',
      new Set(['model_manager.mjs', 'civitai_browser.mjs', 'generations.mjs'].map(snippet)).size, 1);
check('and those lines are there', snippet('generations.mjs').length > 0, true);

done();
