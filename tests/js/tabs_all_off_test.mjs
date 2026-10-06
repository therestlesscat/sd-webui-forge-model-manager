// Every tab off, the extension does nothing in the page (#185): the WebUI
// loads the loader alone, which asks for the version and ui-options once,
// and loads no tab's script and starts no shared module - no action offered,
// no notes, no update check, no downloads. Only what follows the switches
// stays, to start a tab turned on again (shared/loading.mjs) - from the
// WebUI's Settings page, as the settings window cannot open.
import { readdirSync } from 'fs';
import { ROOT, checker, mountTab, settingsPageApplied } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, done } = checker();

const asked = [];
globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    const off = { on: false, built: false };
    const body = path === '/model-manager/asset-version' ? { success: true, version: '1' }
        : path === '/model-manager/ui-options'
            ? { success: true, tabs: { queue: off, generations: off, model_manager: off, civitai_browser: off } }
            : { success: true };
    return { ok: true, status: 200, json: async () => body };
};
const hooks = [];
globalThis.onAfterUiUpdate = (fn) => hooks.push(fn.name || 'anonymous');

// What the WebUI loads: each .mjs directly in javascript/, in name order.
for (const name of readdirSync(`${ROOT}/javascript`).filter((f) => f.endsWith('.mjs')).sort()) {
    await import(`file:///${ROOT}/javascript/${name}`);
}
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await new Promise((resolve) => setTimeout(resolve, 500));

check('it asks for the version and ui-options, once each, and nothing else',
      asked, ['/model-manager/asset-version', '/model-manager/ui-options']);
check('no action is offered: no tab, no shared module started', [...(globalThis.__mmOffered?.keys() || [])], []);
check('the only hook is what keeps the tabs\' buttons as their switches say', hooks, ['applyAll']);

// The way back. No tab was built at this start, so Reload UI creates one.
settingsPageApplied({ model_manager_civitai_browser_enabled: true });
await new Promise((resolve) => setTimeout(resolve, 50));
check('a switch turned on on the Settings page: the popup offers Reload UI, asking nothing',
      [document.querySelector('.mm-reload-dialog .mm-reload-list')?.textContent.trim(),
       document.querySelector('.mm-reload-dialog [data-reload="ui"]')?.textContent.trim(), asked.length],
      ['The Civitai Browser tab is created by Settings -> Reload UI.', 'Reload UI', 2]);

done();
