// Page-wide state is the shared modules' own (#93, #96). Each tab used to
// import them under a version of its own, so each ran once per tab, and what
// the page has one of - the downloads panel, the notes, the switch for Your
// generations, the update notice, the settings window - had to live on
// window to be one. Under one version (#53) a shared module runs once, so its
// state is plain module state, and window keeps only what markup calls.
//
// settings.mjs and viewer.mjs take escapeHtml from common.mjs, through the
// version the tabs asked for theirs under: a plain import would be a second
// copy of it, with state of its own.
import { ROOT, checker, mountTab, sharedModule } from './harness.mjs';
const { window } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, done } = checker();

let copies = 0;
globalThis.onAfterUiUpdate = (fn) => { if (String(fn).includes('apiKeyBanners')) copies += 1; };
// The server answers with a version, so the shared modules are asked for
// under it - and a plain import between them would be a URL without it.
globalThis.fetch = async (url) => ({ ok: true, json: async () => (String(url).includes('/asset-version')
    ? { success: true, version: '1700000123' } : { success: true, downloads: [], notes: [] }) });

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
const common = await sharedModule('common.mjs');
const settings = await sharedModule('settings.mjs');
common.downloads();
settings.settingsWindow();
settings.restampNotice();

const PAGE_STATE = ['mmDownloads', 'mmNotePiles', 'mmNoteRedraw', 'mmNotesDismissed', 'mmGenerationsEnabled',
                    'mmGenerationsWatched', 'mmUpdate', 'mmUpdateWatched', 'mmSettingsWindow', 'mmRestampNotice'];
check('the page\'s state is the shared modules\' own, none of it on window',
      PAGE_STATE.filter((name) => name in window), []);
check('the downloads panel is one, asked for twice', common.downloads(), common.downloads());
check('the settings window too', settings.settingsWindow(), settings.settingsWindow());
check('common.mjs ran once, though the tab, the settings and the viewer each import it', copies, 1);
check('one escape function: the settings window keeps a 0 as 0', common.escapeHtml(0), '0');
check('and nothing as nothing', [common.escapeHtml(null), common.escapeHtml(undefined), common.escapeHtml('')], ['', '', '']);

done();
