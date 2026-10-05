// The queue off (#156): its tab's button and the Queue buttons beside
// Generate are hidden at once, without a restart - the page leaving the
// Queue tab for txt2img if it was showing - and come back when it is on
// again. Known from ui-options, and again when the setting is saved: in the
// settings window (its answer carries the value) or on the Settings page (only
// which keys changed, so the page asks). Your generations' switch, beside it,
// is left as it was. The server's side: queue_switch_test.py.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();

// Forge's tab bar and the two Queue buttons, as far as the switch looks at them.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button">txt2img</button>
        <button id="tab_queue_tab-button" class="selected" aria-selected="true">Queue</button>
        <button id="tab_generations_tab-button">Generations</button>
    </div>
    <button id="txt2img_queue">Queue</button>
    <button id="img2img_queue">Queue</button>`);
const byId = (id) => document.getElementById(id);
const clicked = [];
document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => clicked.push(b.textContent)));
const hidden = () => ['tab_queue_tab-button', 'txt2img_queue', 'img2img_queue'].map((id) => byId(id).style.display === 'none');

let serverSays = false;
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], generations_enabled: true, queue_enabled: serverSays });
    }
    if (href.includes('/asset-version')) return reply({ success: true, version: '1' });
    return reply({ success: true, notes: [], tasks: [], total: 0, page: 1, pages: 1 });
};

await import(`file:///${ROOT}/javascript/queue.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

await waitFor('the switch', () => byId('tab_queue_tab-button').style.display === 'none');
check('off: the Queue tab and both Queue buttons are hidden at once', hidden(), [true, true, true]);
check('and, as the Queue tab was showing, the page goes to txt2img', clicked, ['txt2img']);
check("Your generations' tab is left as it was", byId('tab_generations_tab-button').style.display, '');

window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: ['model_manager_queue_enabled'],
    settings: { model_manager_queue_enabled: { value: true } } } }));
check('on again, from the settings window: all three are back', hidden(), [false, false, false]);

serverSays = false;
window.dispatchEvent(new window.CustomEvent('mm-settings-page-applied',
    { detail: { changed: ['model_manager_queue_enabled'] } }));
await waitFor('the page to ask', () => byId('tab_queue_tab-button').style.display === 'none');
check('off again, from the Settings page: hidden', hidden(), [true, true, true]);

done();
