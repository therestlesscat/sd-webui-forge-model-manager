// A ui-options answer that failed without being a refusal - {success: false,
// error}, no `refused` - says nothing of the tabs: each is as its switch is by
// default, and the ones on start, as before (#183). Only a refusal blocks the
// page (refused_page_test.mjs); this is the line between the two.
import { bootPage, checker, mountTab, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();
for (const file of ['tab_civitai_browser.py', 'tab_gallery.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${file}`));
}
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button" class="selected" aria-selected="true">txt2img</button>
        <button id="tab_model_manager_tab-button">Model Manager</button>
        <button id="tab_civitai_browser_tab-button">Civitai Browser</button>
        <button id="tab_gallery_tab-button">Civitai Images</button>
    </div>`);

globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    if (path === '/model-manager/ui-options') {
        return { ok: false, status: 500, json: async () => ({ success: false, error: 'Something went wrong' }) };
    }
    return { ok: true, status: 200, json: async () => ({ success: true, notes: [], presets: [] }) };
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const offered = () => [...(globalThis.__mmOffered?.keys() || [])];
await waitFor('the Model Manager to start', () => offered().some((name) => name.startsWith('modelManager.')));

check('the tabs start, as their switches are by default',
      ['modelManager.', 'civitaiBrowser.'].map((tab) => offered().some((name) => name.startsWith(tab))), [true, true]);
check('Civitai Images, off where the server does not say, neither starts nor shows',
      [offered().some((name) => name.startsWith('gallery.')),
       document.getElementById('tab_gallery_tab-button').style.display], [false, 'none']);
check('and no notice covers them', document.querySelectorAll('.page-refused, .newer-database').length, 0);

done();
