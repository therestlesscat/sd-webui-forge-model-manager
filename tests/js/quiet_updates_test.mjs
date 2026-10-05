// The WebUI runs every onAfterUiUpdate callback 250 ms after any change to
// the page (script.js, scheduleAfterUiUpdateCallbacks) - so a callback that
// writes to the page whether or not anything changed schedules itself again,
// forever: the Group by button, the new-version notice and both SFW banners
// rewrote their text four times a second, and every extension's callbacks
// ran with them. With all four tabs loaded, as in the WebUI, a second round
// of the callbacks, nothing having changed, has to change nothing.
import { readFileSync } from 'node:fs';
import { ROOT, checker, mountTab, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();
for (const tab of ['tab_civitai_browser.py', 'tab_generations.py', 'tab_queue.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${tab}`));
}
// Each tab's header has its version and gear (tabMarkup, as ui/header.py fills it):
// the notice goes beside the version.

const hooks = [];
globalThis.onAfterUiUpdate = (callback) => hooks.push(callback);
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/update')) {
        return reply({ success: true, current: '0.41.14', latest: '0.42.0', build: 300, newer: true, note: '' });
    }
    if (href.includes('/ui-options')) {
        return reply({ success: true, nsfw_detection: 'model', gallery_hide_nsfw: true, generations_enabled: true,
                       samplers: [], schedulers: [] });
    }
    if (href.includes('/generations/browse')) {
        return reply({ success: true, tiles: [], more: false, state: { total: 0, filtered: 0 }, scope: { count: 0 } });
    }
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
await import(`file:///${ROOT}/javascript/generations.mjs`);
await import(`file:///${ROOT}/javascript/queue.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the update notice', () => document.querySelector('.mm-update'));
await new Promise((resolve) => setTimeout(resolve, 300));

const runHooks = () => hooks.forEach((hook) => hook());
runHooks();                                         // anything to put right, put right
await new Promise((resolve) => setTimeout(resolve, 50));

const changes = [];
const observer = new window.MutationObserver((records) => changes.push(...records));
observer.observe(document.body, { childList: true, subtree: true });
runHooks();
await new Promise((resolve) => setTimeout(resolve, 50));
observer.disconnect();
const where = (node) => {
    const el = node.nodeType === 1 ? node : node.parentNode;
    return el?.id || el?.className || el?.nodeName || '?';
};
check('the callbacks were registered', hooks.length >= 4, true);
check('a second round, nothing having changed, changes nothing on the page',
      [...new Set(changes.map((r) => where(r.target) + ' +' + [...r.addedNodes].map(where).join('/') + ' -' + [...r.removedNodes].map(where).join('/')))], []);

done();
