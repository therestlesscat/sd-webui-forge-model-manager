// A database newer than this copy of the extension knows (#136). The server
// says so in ui-options (database_newer); the loading module then starts no
// tab and no service - nothing asks the database - and covers each tab that
// is on with a notice: both versions, the file, what to do. Its buttons show
// the WebUI's Extensions tab, and open our settings window at the database
// path, starting that window alone. The Queue buttons beside Generate hide.
// The server's side: newer_database_test.py.
import { bootPage, checker, mountTab, press, tabMarkup, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// The other three tabs, Forge's tab bar with its Extensions tab, and the Queue buttons.
for (const file of ['tab_queue.py', 'tab_generations.py', 'tab_civitai_browser.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${file}`));
}
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button" class="selected" aria-selected="true">txt2img</button>
        <button id="tab_model_manager_tab-button">Model Manager</button>
        <button id="tab_extensions-button">Extensions</button>
    </div>
    <div id="tab_extensions" style="display: none"></div>
    <button id="txt2img_queue">Queue</button>
    <button id="img2img_queue">Queue</button>`);
const byId = (id) => document.getElementById(id);
byId('tab_extensions-button').addEventListener('click', () => { byId('tab_extensions').style.display = 'block'; });

const PATH = 'F:\\shared\\models.db';
const asked = [];
let savedPath = '';
globalThis.fetch = async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/asset-version') return reply({ success: true, version: '1' });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [], generations_enabled: true, queue_enabled: true,
                       tabs: tabsAnswer({ queue: true, generations: true, model_manager: true, civitai_browser: true }),
                       database_newer: { schema: 36, known: 35, path: PATH }, restartable: true });
    }
    if (path === '/model-manager/settings') {
        let changed = [];
        if (init.method === 'POST') {
            savedPath = JSON.parse(init.body).values.model_manager_database_path;
            changed = ['model_manager_database_path'];
        }
        return reply({ success: true, order: ['model_manager_database_path'], database_in_use: null, changed,
                       settings: { model_manager_database_path: { label: 'Database file', info: '', kind: 'text',
                                                                   value: savedPath, default: '' } } });
    }
    return reply({ success: true, notes: [], presets: [] });
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await new Promise((resolve) => setTimeout(resolve, 400));

const ROOTS = ['queue_app', 'generations_app', 'model_manager_app', 'civitai_browser_app'];
const notice = (root) => byId(root)?.querySelector('.newer-database');
check('each of the four tabs is covered by the notice', ROOTS.map((root) => Boolean(notice(root))),
      [true, true, true, true]);
const text = notice('model_manager_app')?.textContent || '';
check('which names both versions and the file, and says what to do',
      ['v36', 'v35', PATH, 'Check for updates', 'Database file'].map((part) => text.includes(part)),
      [true, true, true, true, true]);
const offered = () => [...(globalThis.__mmOffered?.keys() || [])]
    .filter((name) => /^(queue|generations|modelManager|civitaiBrowser)\./.test(name));
check('no tab is started: none offers an action', offered(), []);
// The loader asks asset-version first, in the page; the harness boots without it.
check('and nothing else is asked of the server',
      [...new Set(asked)].filter((path) => !['/model-manager/asset-version', '/model-manager/ui-options'].includes(path)),
      []);
check('the Queue buttons beside Generate are hidden',
      ['txt2img_queue', 'img2img_queue'].map((id) => byId(id).style.display), ['none', 'none']);

const button = (label) => [...(notice('model_manager_app')?.querySelectorAll('button') || [])]
    .find((b) => b.textContent.trim() === label);
if (button('Open Extensions')) {
    await press(button('Open Extensions'));
    await waitFor('the Extensions tab to show', () => byId('tab_extensions').style.display !== 'none');
}
check('Open Extensions shows the WebUI\'s Extensions tab', byId('tab_extensions').style.display, 'block');

const focused = [];
const realFocus = window.HTMLElement.prototype.focus;
window.HTMLElement.prototype.focus = function focus() { focused.push(this.dataset?.key || this.id); };
if (button('Database settings')) {
    await press(button('Database settings'));
    await waitFor('the settings window', () => document.querySelector('[data-key="model_manager_database_path"]'));
    await new Promise((resolve) => setTimeout(resolve, 50));
}
window.HTMLElement.prototype.focus = realFocus;
const field = document.querySelector('[data-key="model_manager_database_path"]');
check('Database settings opens our settings window at the database path, its section open, the field focused',
      [Boolean(field), field?.closest('details')?.hasAttribute('open'), focused.includes('model_manager_database_path')],
      [true, true, true]);

// Saved with another file: the server opens it only at startup, so the
// Restart WebUI is offered - the popup a tab switch offers (#186).
const popup = () => document.querySelector('.mm-reload-dialog');
const input = document.querySelector('input[data-key="model_manager_database_path"]');
if (input) {
    input.value = 'F:\\mine\\models2.db';
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
    document.getElementById('mm_settings_save')?.click();
    await waitFor('the save', () => savedPath !== '');
    await new Promise((resolve) => setTimeout(resolve, 50));
}
const restart = popup()?.querySelector('[data-reload="restart"]');
check('a new database file saved: Restart WebUI is offered, saying why',
      [savedPath, Boolean(restart), restart?.disabled, /database file/i.test(popup()?.textContent || '')],
      ['F:\\mine\\models2.db', true, false, true]);
check('with no page reload beside it: the page alone cannot open the file',
      Boolean(popup()?.querySelector('[data-reload="page"], [data-reload="ui"]')), false);
popup()?.querySelector('[data-reload="later"]')?.click();
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: {
    changed: ['model_manager_page_size'], settings: { model_manager_page_size: { value: 30 } } } }));
await new Promise((resolve) => setTimeout(resolve, 50));
check('another setting saved offers nothing', Boolean(popup()), false);

done();
