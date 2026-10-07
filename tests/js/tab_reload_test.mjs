// A tab switch the page cannot fully take says so, and offers what will
// (#185, #186). A tab that ran here may have left something its stop missed,
// and one turned on again comes back only in a new page; one this start did
// not build is created by Settings -> Reload UI. One popup, for every switch
// saved at once, offers Restart WebUI - the server and the page afresh, the
// cleanest slate - the lighter way, or Later: off, a page reload; on again
// after it ran here, a page reload; not built, the WebUI's own Reload UI. A
// tab turned on that starts at once asks nothing - unless the services it
// needs stopped with the last tab that used them (#186). Either way the tab showing
// is kept, for the new page to show again. It is the loading module's, so it
// works with every tab off. Where the WebUI would not come back, and the new
// page going back to the tab: tab_reload_return_test.mjs.
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
let restarted = 0;
globalThis.restart_reload = () => { restarted += 1; };
const stored = new Map();
globalThis.sessionStorage = { getItem: (k) => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, String(v)),
                              removeItem: (k) => stored.delete(k) };

let restartAnswer = { success: true };
const restarts = [];
globalThis.fetch = async (url, options) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        // The Queue on and built; Generations and the Civitai Browser built
        // and off; the Model Manager off, and so not built at this start. A
        // WebUI that comes back.
        const tabs = tabsAnswer({ queue: true, generations: false, civitai_browser: false });
        tabs.model_manager = { on: false, built: false };
        return reply({ success: true, samplers: [], schedulers: [], tabs, restartable: true });
    }
    if (href.includes('/model-manager/restart')) {
        restarts.push(options?.method);
        return reply(restartAnswer);
    }
    return reply({ success: true, notes: [], tasks: [], total: 0, page: 1, pages: 1, counts: {} });
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the Queue tab to start', () => globalThis.__mmOffered?.has('queue.start'));

const popup = () => document.querySelector('.mm-reload-dialog');
const said = () => popup()?.querySelector('.mm-reload-list')?.textContent.replace(/\s+/g, ' ').trim();
const notes = () => popup()?.querySelector('.mm-reload-notes')?.textContent.replace(/\s+/g, ' ').trim();
const buttons = () => Array.from(popup()?.querySelectorAll('button') || []).map((b) => b.textContent.trim());
const button = (label) => Array.from(popup()?.querySelectorAll('button') || []).find((b) => b.textContent.trim() === label);
const press = (label) => button(label)?.dispatchEvent(new window.Event('click', { bubbles: true }));
const save = (settings) => window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: {
    changed: Object.keys(settings),
    settings: Object.fromEntries(Object.entries(settings).map(([key, value]) => [key, { value }])) } }));
const settle = () => new Promise((resolve) => setTimeout(resolve, 50));

// ---------------------------------------------------- one that starts at once
save({ model_manager_record_generations: true });
await settle();
check('on, built and never started here: it starts at once - nothing asked', popup(), null);

// ------------------------------------------------------- a tab switched off
save({ model_manager_queue_enabled: false });
await waitFor('the popup', () => popup());
check('off, after it ran here: it stops at once, and a clean slate is offered',
      [said(), buttons()], ['The Queue is turned off.', ['Restart WebUI', 'Reload the page', 'Later']]);
check('what each way costs, said', notes(),
      'Restart WebUI starts the server and the page afresh: the cleanest slate. A running generation and sync '
      + 'end. Downloads come back paused: resume them after. '
      + 'Reloading loses unsaved input, like a typed prompt.');
press('Later');
check('Later closes it, and reloads nothing', [popup(), reloaded, restarted], [null, 0, 0]);

// --------------------------------- the last tab off: its services stop with it
save({ model_manager_record_generations: false });
await waitFor('the popup', () => popup());
press('Later');
save({ model_manager_civitai_browser_enabled: true });
await waitFor('the popup', () => popup());
check('then one never started: what it needs has stopped, so only a new page brings it',
      said(), 'The Civitai Browser tab comes back with a page reload.');
press('Later');

// ------------------------------------------------- on again after it ran here
save({ model_manager_queue_enabled: true });
await waitFor('the popup', () => popup());
check('on again after it ran here: a page reload, or a restart, brings it back',
      [said(), buttons()], ['The Queue comes back with a page reload.', ['Restart WebUI', 'Reload the page', 'Later']]);
press('Reload the page');
check('the page reloads, the tab showing kept for the new one', [reloaded, popup(), stored.get('mm-return-to')],
      [1, null, 'tab_txt2img']);

// ------------------------------------------------------- one not built
save({ model_manager_model_manager_enabled: true });
await waitFor('the popup', () => popup());
check('on, not built at this start: Reload UI creates it',
      [said(), buttons()], ['The Model Manager tab is created by Settings -> Reload UI.',
                            ['Restart WebUI', 'Reload UI', 'Later']]);
press('Reload UI');
check('Reload UI presses the WebUI\'s own button', [reloadUi, popup()], [1, null]);

// ----------------------------------------- several saved at once: one popup
save({ model_manager_queue_enabled: false, model_manager_model_manager_enabled: false });
await settle();
save({ model_manager_queue_enabled: true, model_manager_model_manager_enabled: true });
await waitFor('the popup', () => popup());
check('one popup at a time, every tab waiting listed', document.querySelectorAll('.mm-reload-dialog').length, 1);
check('the Queue and the Model Manager both, Reload UI the lighter way for both',
      [said(), buttons()], ['The Queue comes back with a page reload. '
                            + 'The Model Manager tab is created by Settings -> Reload UI.',
                            ['Restart WebUI', 'Reload UI', 'Later']]);

// ------------------------------------------------------------ a restart
stored.clear();
press('Restart WebUI');
await waitFor('the WebUI to restart', () => restarted > 0);
check('Restart WebUI: asked of the server, then the WebUI\'s own wait for it, the tab showing kept',
      [restarts, restarted, popup(), stored.get('mm-return-to')], [['POST'], 1, null, 'tab_txt2img']);

// One the server refuses: said, and offered again.
restartAnswer = { success: false, error: 'This WebUI was not started by webui.bat or webui.sh' };
save({ model_manager_queue_enabled: false });
await waitFor('the popup', () => popup());
press('Restart WebUI');
await waitFor('the refusal', () => popup()?.querySelector('.mm-reload-error'));
check('refused: the popup stays, says why, and Restart WebUI can be pressed again',
      [popup()?.querySelector('.mm-reload-error')?.textContent.trim(), button('Restart WebUI')?.disabled, restarted],
      ['The WebUI did not restart: This WebUI was not started by webui.bat or webui.sh', false, 1]);
press('Later');

done();
