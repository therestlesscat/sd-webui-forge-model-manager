// Tabs reach each other through the loading module (#184): a link to another
// tab is disabled, saying why, while that tab is not available - off, not
// built at this start, or stopped - and works, opening it, once it is. One
// rule keeps every such link so (data-needs-tab, in shared/loading.mjs); a
// tab draws it right in the first place (linkTo). A tab used to call the
// other's action by name, after checking ready() its own way, and drew its
// link whether that tab was there or not. Here the Queue's Show images, to
// Generations; a note's Sync, to the Model Manager; and where the page goes
// when the tab showing hides. That no tab names another's actions:
// check_js_references.mjs.
import { bootPage, checker, mountTab, sharedModule, tabMarkup, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_generations.py'));
const { check, waitFor, done } = checker();
const byId = (id) => document.getElementById(id);

// Forge's tab bar, the Queue showing. Clicked, a tab's button is selected.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button">txt2img</button>
        <button id="tab_queue_tab-button" class="selected" aria-selected="true">Queue</button>
        <button id="tab_generations_tab-button">Generations</button>
    </div>`);
const clicked = [];
for (const button of document.querySelectorAll('#tabs button')) {
    button.addEventListener('click', () => {
        clicked.push(button.textContent);
        for (const other of document.querySelectorAll('#tabs button')) {
            other.classList.toggle('selected', other === button);
            other.setAttribute('aria-selected', String(other === button));
        }
    });
}

let generationsOn = false;
const TASK = { id: 14, mode: 'txt2img', status: 'completed', prompt: 'a lighthouse', image_count: 3, generations: [],
               created_at: '2026-10-05T12:50:00', finished_at: '2026-10-05T13:05:00', modules: [] };
const browsed = [];
const SYNC_NOTE = { id: 'a-sync-note', version: '0.1.0', kind: 'action', title: 'Sync again', text: 't',
                    action: { id: 'sync', label: 'Sync' } };
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], generations_enabled: generationsOn,
                       queue_enabled: true, tabs: tabsAnswer({ queue: true, generations: generationsOn }) });
    }
    if (href.includes('/model-manager/notes')) return reply({ success: true, notes: [SYNC_NOTE] });
    if (href.includes('/model-manager/queue/status')) {
        return reply({ success: true, running: false, progress: null, counts: { completed: 1 } });
    }
    if (href.includes('/model-manager/queue/tasks')) {
        const which = new URL(href, 'http://webui').searchParams.get('which');
        const tasks = which === 'history' ? [TASK] : [];
        return reply({ success: true, which, page: 1, pages: 1, page_size: 20, total: tasks.length, tasks });
    }
    if (href.includes('/model-manager/generations/browse')) {
        browsed.push(new URL(href, 'http://webui').searchParams.get('search'));
        return reply({ success: true, tiles: [], more: false, state: {} });
    }
    return reply({ success: true });
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const showImages = () => document.querySelector('#queue_history [data-action="queue.showImages"]');
await waitFor('the Queue tab, and its task', () => showImages());
const loading = await sharedModule('loading.mjs');

// ------------------------------------------------ Generations not available
check('Generations off: Show images is disabled, saying why',
      [showImages()?.disabled, showImages()?.title], [true, 'Your generations is turned off in the settings']);

// The same rule for any link: one to the Model Manager, which this start did not build.
document.body.insertAdjacentHTML('beforeend', `<button id="a_link"${loading.linkTo?.('modelManager', 'Open it') ?? ''}>x</button>`);
check('a link to a tab not built at this start: disabled, saying why',
      [byId('a_link').disabled, byId('a_link').title],
      [true, 'The Model Manager tab was turned on after the WebUI started: it comes with a restart']);

// A note's Sync opens the Model Manager's sync dialog: not drawn without it.
await waitFor('the Queue\'s notes', () => document.querySelector('#queue_notes [data-note]'));
check('a note\'s Sync is not drawn while the Model Manager is not available',
      document.querySelector('#queue_notes [data-note-action="sync"]'), null);

// --------------------------------------------- Generations switched on
generationsOn = true;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: {
    changed: ['model_manager_record_generations'], settings: { model_manager_record_generations: { value: true } } } }));
await waitFor('the Generations tab to start', () => loading.available?.('generations'));
await waitFor('Show images to work', () => showImages() && !showImages().disabled);
check('on: Show images works, with its own title',
      [showImages()?.disabled, showImages()?.title], [false, 'Open the Generations tab on the 3 images this task made']);

showImages().dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the Generations tab, on the task', () => browsed.includes('task:14'));
check('pressed, it opens the Generations tab, searched by the task',
      [clicked.at(-1), browsed.includes('task:14')], ['Generations', true]);

// ------------------------------------------- the showing tab hides
// Generations' own fallback is the Model Manager, which is not available.
clicked.length = 0;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: {
    changed: ['model_manager_record_generations'], settings: { model_manager_record_generations: { value: false } } } }));
await waitFor('the page to leave Generations', () => clicked.length > 0);
check('off while showing: to its fallback, skipping one not available', clicked, ['txt2img']);
check('and Show images is disabled again, saying why',
      [showImages()?.disabled, showImages()?.title], [true, 'Your generations is turned off in the settings']);

done();
