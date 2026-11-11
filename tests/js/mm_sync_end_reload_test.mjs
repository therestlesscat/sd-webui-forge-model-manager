// A sync from the dialog, ending while another grid load runs, loads the
// grid again after it (#388).
//
// The sync's end asks for the grid's first page again, to show what it
// changed. A load asked for while another runs returned at once, so the
// grid kept what that other load drew - rows from before the sync. It now
// waits for it (loadModelsNow), as Delete, a jump and a model's Sync do.
import { checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

let finish = false;          // the sync's progress answers complete once set
let completeAnswered = 0;
let holdNextGrid = false;
let release = null;
const gridAsked = [];

globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/sync/progress')) {
        if (!finish) {
            return reply({ success: true, progress: { total: 2, processed: 1, synced: 1, skipped: 0, errors: 0,
                not_found: 0, current_model: 'a', error_messages: [], is_complete: false } });
        }
        completeAnswered += 1;
        return reply({ success: true, progress: { total: 2, processed: 2, synced: 2, skipped: 0, errors: 0,
            not_found: 0, current_model: '', error_messages: [], is_complete: true } });
    }
    if (href.includes('/model-manager/models') && !href.includes('/models/')) {
        if (holdNextGrid) {
            holdNextGrid = false;
            await new Promise((resolve) => { release = resolve; });
        }
        gridAsked.push(new URL(href, 'http://webui').searchParams);
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [{
            id: 1, model_id: 1, display_name: 'A', file_path: 'C:/m/a.safetensors', file_name: 'a.safetensors',
            model_type: 'LORA', local_version_count: 1 }] });
    }
    return reply({ success: true });
};

// The page's polls shortened: the stand-in answers at once.
window.mmTiming = { poll: 50 };
await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
// The tab found the sync running as it started, and follows it.
await waitFor('the sync followed', () => document.getElementById('mm_status')?.textContent.startsWith('Sync'));

// The end asks for the grid half a second after it is seen: that timer is
// watched, so the held load is let go only once it has run - on a slow
// machine a fixed wait could let it go first, and the old code pass.
let endReloadRan = false;
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (callback, ms, ...args) => realSetTimeout(ms === 500
    ? (...a) => { const answer = callback(...a); endReloadRan = true; return answer; } : callback, ms, ...args);
holdNextGrid = true;
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the held load', () => release !== null);
finish = true;
await waitFor('the sync\'s end', () => completeAnswered > 0);
await waitFor('the end\'s reload asked for', () => endReloadRan, 100);
globalThis.setTimeout = realSetTimeout;
const asked = gridAsked.length;
release?.();
await waitFor('the loads after it', () => gridAsked.length - asked >= 2, 40);
check('the sync\'s reload comes after the load under way, not skipped by it',
      [gridAsked.length - asked, gridAsked.at(-1)?.get('page')], [2, '1']);

done();
