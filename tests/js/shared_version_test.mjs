// The shared modules under one version (#53). Each tab asked for them with
// its own ?mtime, so a release that changed only a shared file left every
// URL as it was, and a browser could serve the copy it held - Gradio's file
// route sends no Cache-Control. And three tabs, three versions: each shared
// module ran once per tab.
//
// Here one tab script is loaded twice, under two versions, as two tabs
// stamped at different mtimes are. ui_options.mjs registers one
// onAfterUiUpdate callback when it runs; counted, they say how many copies ran.
import { ROOT, checker, mountTab } from './harness.mjs';

mountTab('model_manager/ui/tab_generations.py');
const { check, done } = checker();

const commonCopies = [];
globalThis.onAfterUiUpdate = (fn) => {
    if (String(fn).includes('apiKeyBanners')) commonCopies.push(fn);
};

const asked = [];
let version = { success: true, version: '1700000000' };
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/asset-version')) {
        asked.push(href);
        return { ok: true, json: async () => version };
    }
    return { ok: true, json: async () => ({ success: true, generations: [], groups: [], total: 0 }) };
};

await import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-1`);
await import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-2`);
check('two tabs at different versions run the shared module once', commonCopies.length, 1);
check('asking the server for its version once', asked.length, 1);

// Without an answer it falls back to the tab's own version, as before.
delete window.mmSharedVersion;
version = { success: false };
await import(`file:///${ROOT}/javascript/generations.mjs?tab-stamped-at-3`);
check('no version from the server: the tab\'s own, so another copy runs', commonCopies.length, 2);

done();
