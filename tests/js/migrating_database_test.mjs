// A database migrating at this start (#285). The server says so in
// ui-options (database_migrating); the loading module then starts no tab and
// no service - each would wait on the database - and covers each tab that is
// on with a notice: both versions, and how far it has got, asked of the
// server every second. A request that fails is asked again. Once the server
// says it is done, the notices go and the tabs start, in the same page, and
// nothing more is asked. A failure: migration_failed_test.mjs. The server's
// side: migrating_database_test.py.
import { bootPage, checker, mountTab, tabMarkup, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

for (const file of ['tab_queue.py', 'tab_generations.py', 'tab_civitai_browser.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${file}`));
}
document.body.insertAdjacentHTML('afterbegin', `
    <button id="txt2img_queue">Queue</button>
    <button id="img2img_queue">Queue</button>`);
const byId = (id) => document.getElementById(id);

const ROUTE = '/model-manager/database/migration';
const asked = [];
let server = { from: 41, to: 42, progress: '', error: null };
let offline = false;
globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/asset-version') return reply({ success: true, version: '1' });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [], generations_enabled: true, queue_enabled: true,
                       tabs: tabsAnswer({ queue: true, generations: true, model_manager: true, civitai_browser: true }),
                       database_migrating: server, restartable: true });
    }
    if (path === ROUTE) {
        if (offline) throw new TypeError('Failed to fetch');
        return reply({ success: true, migrating: server });
    }
    return reply({ success: true, notes: [], presets: [], models: [], tasks: [], downloads: [] });
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await new Promise((resolve) => setTimeout(resolve, 400));

const ROOTS = ['queue_app', 'generations_app', 'model_manager_app', 'civitai_browser_app'];
const notice = (root) => byId(root)?.querySelector(':scope > .database-migrating');
const progress = (root) => notice(root)?.querySelector('.database-migrating-progress')?.textContent || '';
const offered = () => [...(globalThis.__mmOffered?.keys() || [])]
    .filter((name) => /^(queue|generations|modelManager|civitaiBrowser)\./.test(name));
const areas = () => [...new Set(offered().map((name) => name.split('.')[0]))].sort();
const otherAsks = () => [...new Set(asked)]
    .filter((path) => !['/model-manager/asset-version', '/model-manager/ui-options', ROUTE].includes(path));

check('each of the four tabs is covered by the migrating notice', ROOTS.map((root) => Boolean(notice(root))),
      [true, true, true, true]);
const text = notice('model_manager_app')?.textContent || '';
check('which names both versions, says the tabs start by themselves, and that it is starting',
      ['v41', 'v42', 'start by themselves', 'Starting...'].map((part) => text.includes(part)),
      [true, true, true, true]);
check('no tab is started: none offers an action', offered(), []);
check('and nothing but the migration is asked of the server', otherAsks(), []);
check('the Queue buttons beside Generate are hidden',
      ['txt2img_queue', 'img2img_queue'].map((id) => byId(id).style.display), ['none', 'none']);

server = { ...server, progress: '20,000 of 117,142 images' };
await waitFor('the progress on the notice', () => progress('civitai_browser_app') === server.progress);
check('how far it has got shows on every tab\'s notice, asked of the server',
      ROOTS.map(progress), ROOTS.map(() => '20,000 of 117,142 images'));

offline = true;
const before = asked.filter((path) => path === ROUTE).length;
await waitFor('two failed asks', () => asked.filter((path) => path === ROUTE).length >= before + 2);
offline = false;
server = { ...server, progress: '117,142 images written; checking them against the old table' };
await waitFor('the progress after the failed asks', () => progress('queue_app') === server.progress);
check('a failed ask is asked again, and the notice goes on', progress('queue_app'), server.progress);
check('still no tab started meanwhile', offered(), []);

server = null;
await waitFor('the tabs to start', () => areas().length === 4);
check('once it is done, every notice goes, with the tab\'s cover',
      ROOTS.map((root) => [Boolean(byId(root).querySelector('.newer-database')),
                           byId(root).classList.contains('database-blocked')]),
      ROOTS.map(() => [false, false]));
check('and the four tabs start, with no reload', areas(), ['civitaiBrowser', 'generations', 'modelManager', 'queue']);
check('the Queue buttons show again',
      ['txt2img_queue', 'img2img_queue'].map((id) => byId(id).style.display), ['', '']);
const after = asked.filter((path) => path === ROUTE).length;
await new Promise((resolve) => setTimeout(resolve, 1500));
check('and the server is not asked about it any more', asked.filter((path) => path === ROUTE).length, after);

done();
