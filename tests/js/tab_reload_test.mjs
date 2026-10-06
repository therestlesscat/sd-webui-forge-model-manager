// A switch that cannot take effect in the page says so, and offers what will
// (#185). Off, a tab stops and hides at once; on, one built at this start and
// never started in the page starts at once - neither asks anything. On again
// after it ran here, a tab comes back with a page reload; on, one this start
// did not build is created by Settings -> Reload UI. A popup says which, and
// offers it - the WebUI's own Reload UI button, which reloads the page too -
// or Later. One popup for every switch saved at once. It is the loading
// module's, so it works with every tab off.
import { bootPage, checker, mountTab, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button" class="selected" aria-selected="true">txt2img</button>
        <button id="tab_queue_tab-button">Queue</button>
    </div>
    <button id="settings_restart_gradio">Reload UI</button>`);
let reloadUi = 0;
document.getElementById('settings_restart_gradio').addEventListener('click', () => { reloadUi += 1; });
let reloaded = 0;
window.location.reload = () => { reloaded += 1; };

globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        // The Queue on and built; Generations built and off; the Model Manager
        // off, and so not built at this start.
        const tabs = tabsAnswer({ queue: true, generations: false });
        tabs.model_manager = { on: false, built: false };
        return reply({ success: true, samplers: [], schedulers: [], tabs });
    }
    return reply({ success: true, notes: [], tasks: [], total: 0, page: 1, pages: 1, counts: {} });
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the Queue tab to start', () => globalThis.__mmOffered?.has('queue.start'));

const popup = () => document.querySelector('.mm-reload-dialog');
const said = () => popup()?.querySelector('.mm-reload-list')?.textContent.replace(/\s+/g, ' ').trim();
const buttons = () => Array.from(popup()?.querySelectorAll('button') || []).map((b) => b.textContent.trim());
const press = (label) => Array.from(popup()?.querySelectorAll('button') || [])
    .find((b) => b.textContent.trim() === label)?.dispatchEvent(new window.Event('click', { bubbles: true }));
const save = (settings) => window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: {
    changed: Object.keys(settings),
    settings: Object.fromEntries(Object.entries(settings).map(([key, value]) => [key, { value }])) } }));
const settle = () => new Promise((resolve) => setTimeout(resolve, 50));

// --------------------------------------------- what takes effect at once
save({ model_manager_queue_enabled: false });
await settle();
check('off: it stops and hides at once - nothing asked', popup(), null);
save({ model_manager_record_generations: true });
await settle();
check('on, built and never started here: it starts at once - nothing asked', popup(), null);

// --------------------------------------------------- what needs a reload
save({ model_manager_queue_enabled: true });
await waitFor('the popup', () => popup());
check('on again after it ran here: a page reload brings it back', said(), 'The Queue comes back with a page reload.');
check('offered, or later', buttons(), ['Reload the page', 'Later']);
press('Later');
check('Later closes it, and reloads nothing', [popup(), reloaded], [null, 0]);

// ------------------------------------------------ what needs Reload UI
save({ model_manager_model_manager_enabled: true });
await waitFor('the popup', () => popup());
check('on, not built at this start: Reload UI creates it',
      said(), 'The Model Manager tab is created by Settings -> Reload UI.');
check('offered, or later', buttons(), ['Reload UI', 'Later']);
press('Reload UI');
check('Reload UI presses the WebUI\'s own button', [reloadUi, popup()], [1, null]);

// ----------------------------------------- several saved at once: one popup
save({ model_manager_queue_enabled: false });
await settle();
save({ model_manager_queue_enabled: true, model_manager_model_manager_enabled: false });
await settle();
save({ model_manager_model_manager_enabled: true });
await waitFor('the popup', () => popup());
check('one popup at a time, every tab waiting listed', document.querySelectorAll('.mm-reload-dialog').length, 1);
check('the Queue and the Model Manager both, Reload UI offered for both',
      [said(), buttons()], ['The Queue comes back with a page reload. '
                            + 'The Model Manager tab is created by Settings -> Reload UI.', ['Reload UI', 'Later']]);
press('Later');

done();
