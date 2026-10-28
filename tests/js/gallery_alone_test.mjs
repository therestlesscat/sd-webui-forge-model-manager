// The Civitai Images tab alone starts the page's listener its buttons need
// (#269). Every button it draws goes through data-action, which the listener
// calls.mjs starts runs; the tab did not name calls.mjs in its STARTS, so
// with no other tab on - or the last other one switched off - none of them
// did anything. Another tab once started it for it: gallery_viewer_test.mjs
// still does.
import { checker, mountTab, press, sharedModule, startServices, startTab } from './harness.mjs';

const { document } = mountTab('model_manager/ui/tab_gallery.py');
const { check, waitFor, done } = checker();

let browsed = 0;
globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/gallery/browse')) {
        browsed += 1;
        return reply({ success: true, seed: 1, more: false, state: { total: 0, filtered: 0 }, scope: { count: 0 },
                       tiles: [] });
    }
    if (href.includes('/model-manager/ui-options')) return reply({ success: true, samplers: [], schedulers: [], gallery_grid: 'Classic' });
    return reply({ success: true });
};

/** Refresh pressed through the page's listener: 'acted', or why not - and whether the tab asked again. */
async function refresh() {
    const before = browsed;
    let outcome = 'acted';
    try {
        await press(document.querySelector('[data-action="gallery.refresh"]'));
    } catch (error) {
        outcome = error.message;
    }
    if (outcome === 'acted') await waitFor('the tiles asked for again', () => browsed > before);
    return [outcome, browsed > before];
}

await startTab('gallery');
await waitFor('the first tiles', () => browsed === 1);
check('alone, its Refresh reaches the page\'s listener, and the tab asks for its tiles again', await refresh(),
      ['acted', true]);

// Another user of the listener comes and goes - the last other tab switched
// off: the tab, still on, keeps it.
await startServices('calls.mjs');
const { leaveServices } = await sharedModule('loading.mjs');
leaveServices('suite');
check('with the last other user of the listener gone, its Refresh still works', await refresh(), ['acted', true]);

done();
