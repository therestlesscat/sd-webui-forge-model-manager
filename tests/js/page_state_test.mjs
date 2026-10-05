// Page-wide state is the shared modules' own (#93, #96). Each tab used to
// import them under a version of its own, so each ran once per tab, and what
// the page has one of - the downloads panel, the notes, the switch for Your
// generations, the update notice, the settings window - had to live on
// window to be one. Under one version (#53) a shared module runs once, so its
// state is plain module state, and window keeps only what markup calls.
//
// So every shared module has to be asked for under one URL, the server's
// version on it - by the tabs, and by the shared modules importing each
// other: a plain import between them would be a URL without it, and a second
// copy with state of its own. Every URL Node resolves under javascript/shared/
// is recorded while all three tabs load.
//
// And asked for at once: a tab that awaited each before asking for the next
// waited a round trip per module. So by the time the first of them runs, the
// tab has asked for every one.
import { registerHooks } from 'node:module';
import { readdirSync, readFileSync } from 'node:fs';
import { ROOT, checker, mountTab, sharedModule, tabMarkup } from './harness.mjs';

const urls = new Map();         // file name -> the URLs it was asked for under
registerHooks({
    resolve(specifier, context, nextResolve) {
        const result = nextResolve(specifier, context);
        const at = result.url.indexOf('/javascript/shared/');
        if (at >= 0) {
            const name = result.url.slice(at + '/javascript/shared/'.length).split('?')[0];
            if (!urls.has(name)) urls.set(name, new Set());
            urls.get(name).add(result.url.split('?')[1] ?? '');
        }
        return result;
    },
});

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
for (const tab of ['tab_civitai_browser.py', 'tab_generations.py', 'tab_queue.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${tab}`));
}
const { check, done } = checker();

let copies = 0;
let askedBeforeOneRan = null;
globalThis.onAfterUiUpdate = (fn) => {
    if (!String(fn).includes('apiKeyBanners')) return;
    copies += 1;
    askedBeforeOneRan ??= [...urls.keys()].sort();      // ui_options.mjs runs; what had been asked for
};
globalThis.fetch = async (url) => ({ ok: true, json: async () => (String(url).includes('/asset-version')
    ? { success: true, version: '1700000123' } : { success: true, downloads: [], notes: [] }) });

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
await import(`file:///${ROOT}/javascript/generations.mjs`);
await import(`file:///${ROOT}/javascript/queue.mjs`);

const shared = readdirSync(`${ROOT}/javascript/shared`).filter((name) => name.endsWith('.mjs')).sort();
check('every shared module is loaded by the tabs', [...urls.keys()].sort(), shared);
check('each under one URL, with the server\'s version',
      Object.fromEntries(shared.map((name) => [name, [...(urls.get(name) || [])]])),
      Object.fromEntries(shared.map((name) => [name, ['v=1700000123']])));
check('so ui_options.mjs ran once, though all three tabs that use it import it', copies, 1);
check('the first tab asked for every module it needs before any of them ran', askedBeforeOneRan, shared);

const { downloads } = await sharedModule('downloads.mjs');
const settings = await sharedModule('settings.mjs');
downloads();
settings.settingsWindow();
settings.restampNotice();

const PAGE_STATE = ['mmDownloads', 'mmNotePiles', 'mmNoteRedraw', 'mmNotesDismissed', 'mmGenerationsEnabled',
                    'mmGenerationsWatched', 'mmUpdate', 'mmUpdateWatched', 'mmSettingsWindow', 'mmRestampNotice'];
check('the page\'s state is the shared modules\' own, none of it on window',
      PAGE_STATE.filter((name) => name in window), []);
check('the downloads panel is one, asked for twice', downloads(), downloads());
check('the settings window too', settings.settingsWindow(), settings.settingsWindow());

const { escapeHtml } = await sharedModule('core.mjs');
check('one escape function: the settings window keeps a 0 as 0', escapeHtml(0), '0');
check('and nothing as nothing', [escapeHtml(null), escapeHtml(undefined), escapeHtml('')], ['', '', '']);

done();
