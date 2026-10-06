// The page a reload brings, after the popup asked for it (#186): back on the
// tab that showed, once Gradio has drawn its button - a reload lands on the
// first tab. And a WebUI started without its own script, which a restart
// would leave shut down: Restart WebUI is disabled, saying why, and the
// lighter way is the one offered. The popup itself: tab_reload_test.mjs.
import { bootPage, checker, mountTab, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();
const hooks = [];
globalThis.onAfterUiUpdate = (fn) => hooks.push(fn);
const stored = new Map([['mm-return-to', 'tab_queue_tab']]);
globalThis.sessionStorage = { getItem: (k) => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, String(v)),
                              removeItem: (k) => stored.delete(k) };

globalThis.fetch = async (url) => {
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (String(url).includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], tabs: tabsAnswer({ queue: true }), restartable: false });
    }
    return reply({ success: true, notes: [], tasks: [], total: 0, page: 1, pages: 1, counts: {} });
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the Queue tab to start', () => globalThis.__mmOffered?.has('queue.start'));
check('the tab to go back to is taken, once', stored.has('mm-return-to'), false);

// Gradio draws the tab bar after the scripts: the txt2img tab showing, as on any load.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button" class="selected" aria-selected="true">txt2img</button>
        <button id="tab_queue_tab-button">Queue</button>
    </div>`);
const clicked = [];
document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => clicked.push(b.textContent)));
hooks.forEach((hook) => hook());
check('drawn: the tab that showed before the reload shows again', clicked, ['Queue']);
hooks.forEach((hook) => hook());
check('once: the next update leaves the tab bar alone', clicked, ['Queue']);

// --------------------------------------------- a WebUI that would not come back
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: {
    changed: ['model_manager_queue_enabled'], settings: { model_manager_queue_enabled: { value: false } } } }));
await waitFor('the popup', () => document.querySelector('.mm-reload-dialog'));
const restart = Array.from(document.querySelectorAll('.mm-reload-dialog button')).find((b) => b.textContent.trim() === 'Restart WebUI');
const why = 'This WebUI was not started by webui.bat or webui.sh: a restart would leave it shut down';
check('Restart WebUI disabled, saying why, on it and under the tabs',
      [restart?.disabled, restart?.title,
       document.querySelector('.mm-reload-dialog .mm-reload-notes p')?.textContent.trim()], [true, why, `${why}.`]);
check('the lighter way offered first',
      document.querySelector('.mm-reload-dialog [data-reload="page"]')?.classList.contains('primary'), true);

done();
