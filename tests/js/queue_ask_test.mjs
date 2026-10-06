// Generate asks before a large batch (#166): above the setting - batch count
// times batch size - a press of Generate is caught before Forge's own
// listener, and a question offers Generate, Queue or Cancel. Generate lets
// the press through, Queue presses the tab's Queue button instead, Cancel
// does neither. "Don't ask again in this browser", with Generate or Queue,
// is kept in the browser's storage. Never asked: at or below the setting, with
// it at 0, with the queue off, or for a press Generate forever makes itself -
// though Ctrl+Enter, which Forge's script turns into a press, is the person's.
// In img2img alike. The setting comes from ui-options, and again when saved.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();

// Forge's Generate and Queue buttons and its batch sliders, as far as the question reads them.
const controls = (tab) => `
    <div id="${tab}_batch_count"><input type="number" value="1"><input type="range" value="1"></div>
    <div id="${tab}_batch_size"><input type="number" value="1"><input type="range" value="1"></div>
    <button id="${tab}_generate">Generate</button>
    <button id="${tab}_queue">Queue</button>`;
document.body.insertAdjacentHTML('afterbegin', controls('txt2img') + controls('img2img'));
const byId = (id) => document.getElementById(id);
const pressed = [];
for (const tab of ['txt2img', 'img2img']) byId(`${tab}_queue`).addEventListener('click', () => pressed.push(`${tab} queue`));
const batch = (tab, count, size) => {
    byId(`${tab}_batch_count`).querySelector('input[type="number"]').value = String(count);
    byId(`${tab}_batch_size`).querySelector('input[type="number"]').value = String(size);
};

let askAbove = 4;
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], generations_enabled: true, queue_enabled: true,
                       queue_ask_above: askAbove });
    }
    if (href.includes('/asset-version')) return reply({ success: true, version: '1' });
    return reply({ success: true, notes: [], tasks: [], total: 0, page: 1, pages: 1 });
};

await import(`file:///${ROOT}/javascript/queue.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
// Forge's own listener on Generate. A browser runs the page's capture listener
// before it; this DOM has no capture phase, so it stands after ours on the
// document. tests/work/probe_queue_ask/ shows the hold in a real browser.
document.addEventListener('click', (event) => {
    const generate = event.target.closest?.('#txt2img_generate, #img2img_generate');
    if (generate) pressed.push(`${generate.id.split('_')[0]} generate`);
});
await new Promise((resolve) => setTimeout(resolve, 50));

/** A press of Generate: the person's own, or - not trusted - a script's. */
function press(tab, person = true) {
    const event = new window.Event('click', { bubbles: true, cancelable: true });
    if (person) Object.defineProperty(event, 'isTrusted', { value: true });
    byId(`${tab}_generate`).dispatchEvent(event);
}
const dialog = () => document.querySelector('.queue-dialog');
async function answer(label, never = false) {
    await waitFor(`the question, for ${label}`, () => dialog());
    const asked = dialog()?.textContent.replace(/\s+/g, ' ').trim();
    if (never && dialog()) dialog().querySelector('input[name="never"]').checked = true;
    [...(dialog()?.querySelectorAll('button') || [])].find((b) => b.textContent.trim() === label)?.click();
    await new Promise((resolve) => setTimeout(resolve, 10));
    return asked;
}

batch('txt2img', 1, 4);
press('txt2img');
check('at the setting, Generate is not asked about', [pressed, dialog()], [['txt2img generate'], null]);

pressed.length = 0;
batch('txt2img', 2, 4);
press('txt2img');
check('above it, the press is held and the question asked', [pressed, Boolean(dialog())], [[], true]);
const asked = await answer('Cancel', true);
check('it says how many, and why', [asked?.startsWith('Generate 8 images?'), asked?.includes('Batch count 2 × batch size 4')],
      [true, true]);
check('Cancel does nothing, and forgets the box', [pressed, localStorage.getItem('mm_queue_never_ask_large_batch')],
      [[], null]);

press('txt2img');
await answer('Queue');
check("Queue presses the tab's Queue button instead", pressed, ['txt2img queue']);

pressed.length = 0;
press('txt2img');
await answer('Generate');
check('Generate lets the press through, once', pressed, ['txt2img generate']);

pressed.length = 0;
press('txt2img', false);
check('Generate forever presses Generate itself: not asked', [pressed, dialog()], [['txt2img generate'], null]);

pressed.length = 0;
// linkedom has no KeyboardEvent: a plain one, with the keys the listener reads.
document.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Enter', ctrlKey: true }));
press('txt2img', false);
check("Ctrl+Enter's press is the person's: asked", [pressed, Boolean(dialog())], [[], true]);
await answer('Cancel');

pressed.length = 0;
batch('img2img', 3, 2);
press('img2img');
await answer('Generate');
check('in img2img alike', pressed, ['img2img generate']);

pressed.length = 0;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: ['model_manager_queue_ask_above'],
    settings: { model_manager_queue_ask_above: { value: 0 } } } }));
press('txt2img');
check('with the setting at 0, never asked', [pressed, dialog()], [['txt2img generate'], null]);
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: ['model_manager_queue_ask_above'],
    settings: { model_manager_queue_ask_above: { value: 4 } } } }));

pressed.length = 0;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: ['model_manager_queue_enabled'],
    settings: { model_manager_queue_enabled: { value: false } } } }));
press('txt2img');
check('with the queue off, never asked', [pressed, dialog()], [['txt2img generate'], null]);
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: ['model_manager_queue_enabled'],
    settings: { model_manager_queue_enabled: { value: true } } } }));

pressed.length = 0;
press('txt2img');
await answer('Generate', true);
check("Don't ask again, with Generate, is kept in the browser",
      [pressed, localStorage.getItem('mm_queue_never_ask_large_batch')], [['txt2img generate'], 'true']);
pressed.length = 0;
press('txt2img');
check('and then the browser is never asked', [pressed, dialog()], [['txt2img generate'], null]);

done();
