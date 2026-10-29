// A library that needs no repair (#241): the page asks once the tabs have
// started, the server names none, and no repair's script is imported - its
// window not offered, nothing drawn in the settings window's place for them.
import { bootPage, checker, mountTab, tabsAnswer, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const asked = [];
globalThis.fetch = withGalleryPages(async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [], tabs: tabsAnswer({ generations: true }) });
    }
    if (path === '/model-manager/repairs') return reply({ success: true, repairs: {} });
    return reply({ success: true, generations: [], images: [], notes: [], total: 0 });
});

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the question', () => asked.includes('/model-manager/repairs'));
await new Promise((resolve) => setTimeout(resolve, 50));
check('asked once', asked.filter((p) => p === '/model-manager/repairs').length, 1);
check('none named: no repair\'s window offered', globalThis.__mmOffered?.has('repairs.recorded_twice'), false);
check('and none of its routes asked', asked.filter((p) => p.startsWith('/model-manager/repairs/')), []);
const slot = document.createElement('div');
slot.dataset.repairsSlot = '';
document.body.appendChild(slot);
window.dispatchEvent(new window.CustomEvent('mm-upkeep-drawn', { detail: { slot } }));
check('the settings window\'s place for repairs stays empty', slot.innerHTML, '');

done();
