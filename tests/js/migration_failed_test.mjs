// A database's migration failing at this start (#285): the notice over the
// tabs says so, with the server's error, and stays - the tabs do not start,
// and the server is not asked again, as only a restart tries it again. The
// rest: migrating_database_test.mjs.
import { bootPage, checker, mountTab, tabMarkup, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_civitai_browser.py'));
const byId = (id) => document.getElementById(id);
// What runs after each of Gradio's updates: the notices are drawn again there.
const afterUpdates = [];
globalThis.onAfterUiUpdate = (callback) => afterUpdates.push(callback);

const ROUTE = '/model-manager/database/migration';
const ERROR = 'There is not room for the update beside the database: a made-up failure';
const asked = [];
let server = { from: 41, to: 42, progress: '20,000 of 117,142 images', error: null };
globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/asset-version') return reply({ success: true, version: '1' });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [],
                       tabs: tabsAnswer({ model_manager: true, civitai_browser: true }),
                       database_migrating: server, restartable: true });
    }
    if (path === ROUTE) return reply({ success: true, migrating: server });
    return reply({ success: true, notes: [], presets: [], models: [], downloads: [] });
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await new Promise((resolve) => setTimeout(resolve, 400));

const ROOTS = ['model_manager_app', 'civitai_browser_app'];
const notices = (root) => byId(root)?.querySelectorAll(':scope > .newer-database').length;
const failedText = (root) => byId(root)?.querySelector(':scope > .database-migration-failed')?.textContent || '';
const offered = () => [...(globalThis.__mmOffered?.keys() || [])]
    .filter((name) => /^(modelManager|civitaiBrowser)\./.test(name));
const routeAsks = () => asked.filter((path) => path === ROUTE).length;

check('while it runs, both tabs are covered', ROOTS.map((root) => notices(root)), [1, 1]);

server = { ...server, error: ERROR };
await waitFor('the failure on the notice', () => failedText('civitai_browser_app').includes(ERROR));
check('a failure replaces the notice on each tab, one notice each', ROOTS.map((root) => notices(root)), [1, 1]);
check('saying it could not, with the server\'s error, and that a restart tries it again',
      ROOTS.map((root) => ['could not update', ERROR, 'restarted'].map((part) => failedText(root).includes(part))),
      ROOTS.map(() => [true, true, true]));
check('without the running notice\'s progress', Boolean(byId('model_manager_app')
    .querySelector('.database-migrating-progress')), false);
const after = routeAsks();
await new Promise((resolve) => setTimeout(resolve, 1500));
check('the server is not asked again', routeAsks(), after);
check('no tab started', offered(), []);
afterUpdates.forEach((callback) => callback());
check('and the notice stays, after Gradio\'s updates too', ROOTS.map((root) => [notices(root), failedText(root).includes(ERROR)]),
      ROOTS.map(() => [1, true]));

done();
