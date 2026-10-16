// The database file's space and its old backups, under Database file in the
// settings window (#287): the Compact database line in each state, its
// question, following a compact to its end, Cancel; the backups, each line,
// Delete's and Delete all's questions, names sent and never paths.
import { call, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The page's waits, shortened (TIMING): a running compact's poll, the ask
// again while something stops one.
window.mmTiming = { compactPoll: 30, compactRetry: 80, drawRetry: 25 };
globalThis.MutationObserver = window.MutationObserver;
const { check, waitFor, done } = checker();

const MB = 1048576;
const GB = 1073741824;
const SETTINGS = {
    model_manager_hash_threads: { label: 'Hashing threads', info: '', kind: 'number', value: 4, default: 4,
                                  minimum: 1, maximum: 32, step: 1 },
    model_manager_database_path: { label: 'Database file', info: '', kind: 'text', value: '', default: '' },
};
const ORDER = Object.keys(SETTINGS);

// The server's answers, as db/upkeep.py gives them.
const BACKUPS = [
    { name: 'models.db.backup_20261015_233900_v42', made: '2026-10-15T23:39:00', kind: 'database', holds: 41,
      bytes: Math.round(1.03 * GB) },
    { name: 'models.db.backup_20261015_233857_v41', made: '2026-10-15T23:38:57', kind: 'database', holds: 40,
      bytes: Math.round(1.03 * GB) },
];
function space(extra = {}) {
    const answer = { success: true, path: 'C:\\m\\models.db', file_bytes: 1923043328, wal_bytes: 0, page_size: 4096,
                     pages: 469493, free_bytes: 566 * MB, kept_bytes: 1923043328 - 566 * MB, min_free: 10 * MB,
                     room: [], blocked: null, compact: null, custom_database: false, backups: BACKUPS, ...extra };
    answer.backups_bytes = answer.backups.reduce((sum, b) => sum + b.bytes, 0);
    return answer;
}
let spaceAnswers = [space()];        // one per ask; the last repeats
let compactAnswers = [];             // the poll's, one per ask; the last repeats
let startAnswer = { success: true };
let deleteAnswer = null;
let compactHold = null;              // a poll's answer held back until this settles
const requests = [];

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const method = init.method || 'GET';
    const json = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/database/')) {
        const path = href.replace(/^.*\/model-manager\/database\//, '').split('?')[0];
        requests.push([method, path, init.body ? JSON.parse(init.body) : null]);
        if (path === 'space') return json(spaceAnswers.length > 1 ? spaceAnswers.shift() : spaceAnswers[0]);
        if (path === 'compact' && method === 'POST') return json(startAnswer);
        if (path === 'compact') {
            if (compactHold) await compactHold;
            return json(compactAnswers.length > 1 ? compactAnswers.shift() : compactAnswers[0]);
        }
        if (path === 'compact/cancel') return json({ success: true });
        if (path === 'backups/delete') return json(deleteAnswer);
    }
    if (href.includes('/model-manager/notes')) return json({ success: true, notes: [] });
    if (href.includes('/model-manager/settings/modules')) return json({ success: false });
    if (href.includes('/model-manager/settings')) {
        return json({ success: true, settings: SETTINGS, order: ORDER, database_in_use: 'C:\\m\\models.db' });
    }
    return json({ success: true, models: [], total: 0 });
};

const asked = [];
let confirmAnswer = true;
window.confirm = (text) => {
    asked.push(text);
    return confirmAnswer;
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (sel) => document.querySelector(sel);
const box = () => $('#mm_settings_upkeep');
const text = () => (box()?.textContent || '').replace(/\s+/g, ' ').trim();
const button = (act) => box()?.querySelector(`[data-act="${act}"]`);
const asks = (path, method = 'GET') => requests.filter(([m, p]) => m === method && p === path).length;

async function open() {
    await call('settings.open', { section: 'storage' });
    await waitFor('the database part drawn', () => /unused|compact|waits|needs/i.test(text()));
}
function close() {
    $('[data-act="cancel"]').click();
}

// ------------------------------------------------- 16. what can be freed
await open();
check('16. under Database file, below its In use line',
      box()?.previousElementSibling?.getAttribute('data-extra'), 'model_manager_database_path');
check('16. the line says how much of the file is unused', text().includes('About 566.00 MB of the 1.79 GB file is unused.'),
      true);
check('16. and Compact database is on', button('compact')?.disabled, false);
close();

// ------------------------------------------------ 17. nothing worth freeing
spaceAnswers = [space({ free_bytes: 2 * MB })];
await open();
check('17. under the floor: already compact, saying how much',
      text().includes('The file is already compact: 2.00 MB of 1.79 GB unused.'), true);
check('17. the button off, saying the same', [button('compact')?.disabled, button('compact')?.title],
      [true, 'The file is already compact: 2.00 MB of 1.79 GB unused.']);
close();

// ------------------------------------- 18. something stops it, then ends
spaceAnswers = [space({ blocked: 'Compacting waits for Sync with Civitai to end.' }), space()];
await open();
check('18. a sync running: the line says so', text().includes('Compacting waits for Sync with Civitai to end.'), true);
check('18. the button off, saying why', [button('compact')?.disabled, button('compact')?.title],
      [true, 'Compacting waits for Sync with Civitai to end.']);
await waitFor('the window to ask again', () => button('compact')?.disabled === false);
check('18. asked again a few seconds on, the button comes back by itself', button('compact')?.disabled, false);
close();

// ------------------------------------------------- 19. the question, no
spaceAnswers = [space()];
await open();
confirmAnswer = false;
asked.length = 0;
button('compact').click();
await new Promise((r) => setTimeout(r, 50));
check('19. pressed, a question first', asked.length, 1);
check('19. answered no: nothing is sent', asks('compact', 'POST'), 0);
check('19. the question says what it does, and that this WebUI waits',
      asked[0], 'Compact the database? It rewrites the 1.79 GB file: about 15 seconds on a fast disk, longer on a slow '
      + 'one. Generations, downloads and syncs in this WebUI wait until it ends.');
close();

// ------------------------------------- 20. yes: followed to its end
const running = (seconds) => ({ state: 'running', started: 0, before: 1923043328, seconds });
const ended = { state: 'done', started: 0, before: 1923043328, seconds: 18.2, finished: 18, after: 1923043328 - 566 * MB,
                shrunk: true, locked: false, error: null };
spaceAnswers = [space(), space({ compact: running(0.1) }), space({ free_bytes: 0, compact: ended })];
compactAnswers = [{ success: true, compact: running(1.2) }, { success: true, compact: running(2.4) },
                  { success: true, compact: ended }];
await open();
confirmAnswer = true;
button('compact').click();
await waitFor('the start sent', () => asks('compact', 'POST') === 1);
await waitFor('the running line', () => text().includes('Compacting the database...'));
check('20. running: the time so far, and Cancel', [/Compacting the database\.\.\. \d+ s/.test(text()),
      Boolean(button('compact-cancel'))], [true, true]);
await waitFor('its end', () => text().includes('Compacted:'));
check('20. followed by the poll until it ends', asks('compact') >= 3, true);
check('20. done: both sizes, what it freed, how long',
      text().includes('Compacted: 1.79 GB to 1.24 GB, 566.00 MB freed, in 18 s.'), true);
check('20. and nothing left to free', button('compact')?.disabled, true);
close();

// ------------------------------------------ 21. two WebUIs on one file
spaceAnswers = [space({ custom_database: true })];
await open();
confirmAnswer = false;
asked.length = 0;
button('compact').click();
check('21. a database path of its own set: the question warns of the other WebUI',
      asked[0]?.endsWith(' Another WebUI sharing this file should not generate or sync meanwhile: its writes give up '
                         + 'after 30 seconds.'), true);
close();

// ---------------------------------------------------------- 22. Cancel
const cancelled = { ...ended, state: 'cancelled', after: 1923043328, shrunk: false };
spaceAnswers = [space({ compact: running(3) }), space({ compact: cancelled })];
compactAnswers = [{ success: true, compact: running(4) }, { success: true, compact: cancelled }];
requests.length = 0;
await open();
await waitFor('Cancel drawn', () => Boolean(button('compact-cancel')));
button('compact-cancel').click();
await waitFor('the cancel sent', () => asks('compact/cancel', 'POST') === 1);
await waitFor('the cancelled line', () => text().includes('Cancelled: the database is as it was.'));
check('22. Cancel says the database is as it was', text().includes('Cancelled: the database is as it was.'), true);
close();

// ----------------------------------- 23. closed while running, opened again
// Closed while a poll waits for its answer: the answer, once it comes, asks nothing more.
spaceAnswers = [space({ compact: running(5) })];
compactAnswers = [{ success: true, compact: running(6) }];
requests.length = 0;
let release;
compactHold = new Promise((r) => { release = r; });
await open();
await waitFor('the poll, its answer held', () => asks('compact') >= 1);
close();
release();
compactHold = null;
const polled = asks('compact');
await new Promise((r) => setTimeout(r, 150));
check('23. closed: no more asking', asks('compact'), polled);
await open();
check('23. opened again while it runs: the running line, and the poll again',
      [text().includes('Compacting the database...'), (await waitFor('the poll again', () => asks('compact') > polled),
                                                        asks('compact') > polled)], [true, true]);
close();
compactAnswers = [{ success: true, compact: ended }];

// ---------------------------------------------------------- 24. backups
spaceAnswers = [space(), space({ backups: BACKUPS.slice(1) })];
requests.length = 0;
await open();
const lines = Array.from(box().querySelectorAll('.mm-upkeep-backups > span')).map((s) => s.textContent.trim());
check('24. a heading with how many and their total', text().includes('Old backups: 2 copies, 2.06 GB'), true);
check('24. each backup: when, which version it holds, its size, newest first', lines,
      ['15 Oct 2026, 23:39', 'database version 41', '1.03 GB', '15 Oct 2026, 23:38', 'database version 40', '1.03 GB']);
confirmAnswer = false;
asked.length = 0;
box().querySelector('[data-act="backup-delete"]').click();
check('24. Delete asks first, naming the version, when, and what it frees', asked[0],
      'Delete the backup of database version 41, made 15 Oct 2026, 23:39? It frees 1.03 GB. It cannot be undone.');
check('24. answered no: nothing sent', asks('backups/delete', 'POST'), 0);
confirmAnswer = true;
deleteAnswer = { success: true, results: [{ name: BACKUPS[0].name, deleted: true, error: null }] };
box().querySelector('[data-act="backup-delete"]').click();
await waitFor('the delete sent', () => asks('backups/delete', 'POST') === 1);
check('24. only its name is sent, never a path', requests.find(([m, p]) => p === 'backups/delete')[2],
      { names: [BACKUPS[0].name] });
await waitFor('the list drawn again', () => box().querySelectorAll('[data-act="backup-delete"]').length === 1);
check('24. the list is drawn again from the server', text().includes('Old backups: 1 copy, 1.03 GB'), true);
close();

spaceAnswers = [space()];
deleteAnswer = { success: true, results: [{ name: BACKUPS[0].name, deleted: true, error: null },
                                          { name: BACKUPS[1].name, deleted: false, error: 'in use by another program' }] };
requests.length = 0;
await open();
asked.length = 0;
button('backups-delete-all').click();
await waitFor('Delete all sent', () => asks('backups/delete', 'POST') === 1);
check('24. Delete all asks, with how many and what they free', asked[0],
      'Delete all 2 backups? They free 2.06 GB. They cannot be undone.');
check('24. and sends every name', requests.find(([m, p]) => p === 'backups/delete')[2],
      { names: BACKUPS.map((b) => b.name) });
await waitFor('what was not deleted', () => text().includes('Could not delete'));
check('24. a copy not deleted is said, with why',
      text().includes(`Could not delete ${BACKUPS[1].name}: in use by another program.`), true);
close();

// ------------------------------------------------------- 25. no backups
spaceAnswers = [space({ backups: [] })];
await open();
check('25. none: one line, and no buttons for them',
      [text().includes('No old backups beside the database.'), Boolean(button('backups-delete-all')),
       Boolean(box().querySelector('[data-act="backup-delete"]'))], [true, false, false]);
close();

done();
