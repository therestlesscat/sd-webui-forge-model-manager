// A migration that did not run because of the other WebUI sharing the
// database (#428), as the notice over the tabs says it: the wait for the
// other WebUI ran out; the file that keeps the two apart cannot be used; the
// database was found newer than this copy once the wait ended - #136's
// notice, found through the poll or already in the first answer. Each case
// on a page of its own: once a failure is drawn the page
// asks the server no more. Run without a case, the suite runs each case as a
// child of its own. The rest: migration_failed_test.mjs.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const CASES = ['waited', 'lock_file', 'newer', 'newer_first'];
const WAITING = 'Waiting for the other WebUI sharing this database to finish updating it.';
const which = process.argv[2];

if (!which) {
    let failed = 0;
    for (const name of CASES) {
        const run = spawnSync(process.execPath, [fileURLToPath(import.meta.url), name],
                              { encoding: 'utf8', env: process.env });
        const out = `${run.stdout || ''}${run.stderr || ''}`.trim();
        const passed = run.status === 0 && /All checks passed/.test(out);
        if (!passed) {
            failed += 1;
            console.log(`-- case ${name} (exit ${run.status}):\n${out || 'no output'}`);
        }
    }
    console.log(failed ? `FAIL ${failed} of ${CASES.length} cases` : 'All checks passed.');
    process.exit(failed ? 1 : 0);
}

const { bootPage, checker, mountTab, tabMarkup, tabsAnswer } = await import('./harness.mjs');
const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker(which);

document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_civitai_browser.py'));
const byId = (id) => document.getElementById(id);

const ROUTE = '/model-manager/database/migration';
const PATH = 'X:\\library\\models.db';
const ERRORS = {
    waited: `[ModelManager] The other WebUI sharing the database ${PATH} is still updating it, after an hour of waiting. Restart this WebUI once it is done.`,
    lock_file: `[ModelManager] The file ${PATH}.migrating, which keeps two WebUIs sharing the database from updating it at once, cannot be used: file is not a database. If another program has it open, restart the WebUI once it lets go of it; otherwise delete the file, then restart the WebUI.`,
    newer: `[ModelManager] The database ${PATH} is at schema v50, newer than this copy of the extension knows (v49).`,
};
const NEWER = { schema: 50, known: 49, path: PATH };
// The server's words for each case, as `_migrating_alone` and `_refuse_newer` say them.
const stoppedAs = (name) => ({ from: 42, to: 49, progress: WAITING, error: ERRORS[name], case: name,
                               newer: name === 'newer' ? NEWER : null });
// newer_first: the page loads once the stop is stored, while the server's
// own check for a newer database (`database_newer`) still said nothing.
const first = which === 'newer_first';
const kind = first ? 'newer' : which;
let server = first ? stoppedAs('newer') : { from: 42, to: 49, progress: WAITING, error: null };
globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
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
const text = (root) => [...(byId(root)?.querySelectorAll(':scope > .newer-database') || [])]
    .map((notice) => notice.textContent.replace(/\s+/g, ' ')).join(' | ');
const notices = (root) => byId(root)?.querySelectorAll(':scope > .newer-database').length;

if (!first) {
    check('while it waits on the other WebUI, the notice says so',
          ROOTS.map((root) => text(root).includes(WAITING)), [true, true]);
    server = stoppedAs(which);
}
await waitFor('the notice for the case', () => text('civitai_browser_app').includes(
    kind === 'newer' ? 'older than its database' : ERRORS[kind]));
check('one notice on each tab', ROOTS.map((root) => notices(root)), [1, 1]);
const said = (parts) => ROOTS.map((root) => parts.map((part) => text(root).includes(part)));
const all = (parts) => ROOTS.map(() => parts.map(() => true));

if (kind === 'waited') {
    const parts = ['could not update', 'other WebUI sharing this database is still updating it',
                   'stopped waiting', 'Nothing was changed', 'restarted', ERRORS.waited];
    check('the wait ran out: the other WebUI is still at it, nothing changed, restart once it is done, the server\'s words',
          said(parts), all(parts));
}
if (kind === 'lock_file') {
    const parts = ['could not update', 'cannot be used', 'did not start', 'Nothing was changed',
                   'If another program has the file open', 'otherwise delete the file', ERRORS.lock_file];
    check('the file cannot be used: the update did not start, restart once another program lets go, else delete it, the server\'s words naming it',
          said(parts), all(parts));
}
if (kind === 'newer') {
    const parts = ['older than its database', 'v50', 'v49', `Database: ${PATH}`, 'Open Extensions'];
    check('updated past this copy meanwhile: the notice of a newer database, its versions and file',
          said(parts), all(parts));
    check('and no notice of a failed update beside it',
          ROOTS.map((root) => Boolean(byId(root).querySelector('.database-migration-failed'))), [false, false]);
    check('its buttons act: Open Extensions and the database setting are offered',
          ['database.openExtensions', 'database.openSettings'].map((name) => globalThis.__mmOffered?.has(name)),
          [true, true]);
}
if (kind !== 'newer') {
    check('not the notice of an update stopped partway, which kept what it finished',
          ROOTS.map((root) => text(root).includes('What it finished is kept')), [false, false]);
}

done();
