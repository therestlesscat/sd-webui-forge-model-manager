// A tab switched off is not loaded at all (#183). The WebUI loads every .mjs
// directly in javascript/, whatever the switches say: the tabs' scripts were
// there, and with Generations off its script still ran - its actions offered,
// its listeners added. Now there is one, the loader, and it loads only the
// tabs that are on (shared/loading.mjs). One switched on again, built at this
// start and never started in this page, starts at once.
import { readdirSync } from 'fs';
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

let generationsOn = false;
const tab = (on) => ({ on, built: true });
globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/asset-version') return reply({ success: true, version: '1' });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [], generations_enabled: generationsOn,
                       queue_enabled: true, tabs: { queue: tab(true), generations: tab(generationsOn),
                                                    model_manager: tab(true), civitai_browser: tab(true) } });
    }
    return reply({ success: true, notes: [], tiles: [], more: false, state: {} });
};

// What the WebUI loads: each .mjs directly in javascript/, in name order (list_scripts).
const scripts = readdirSync(`${ROOT}/javascript`).filter((name) => name.endsWith('.mjs')).sort();
for (const name of scripts) await import(`file:///${ROOT}/javascript/${name}`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await new Promise((resolve) => setTimeout(resolve, 500));

const offered = () => [...(globalThis.__mmOffered?.keys() || [])].filter((name) => name.startsWith('generations.'));
check('the WebUI loads one script, the loader', scripts, ['loader.mjs']);
check('Generations off: nothing of its script runs - none of its actions is offered', offered(), []);

// Switched on in the settings window: built at this start, so started at once.
generationsOn = true;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: {
    changed: ['model_manager_record_generations'], settings: { model_manager_record_generations: { value: true } } } }));
await waitFor('the Generations tab to start', () => offered().length > 0);
check('switched on, it starts at once: its markup is there', offered().includes('generations.refresh'), true);

done();
