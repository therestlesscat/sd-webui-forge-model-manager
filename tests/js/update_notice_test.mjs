// "v0.42.0 available" beside the version in a tab's header, when the server's
// check (update_check_test.py) found a newer one: linking where the version
// does, saying in its tooltip how to update. Put back after Gradio redraws the
// header; gone when the setting is turned off.
import { ROOT, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

// The header's version and gear are the harness's, from ui/header.py; this
// is what a redraw by Gradio puts back.
const HEADER = `<span class="mm-header-actions"><a class="mm-version" href="https://example.test/CHANGELOG.md"
    target="_blank" rel="noopener">v0.41.11</a><button class="mm-settings-btn"></button></span>`;

let update = { success: true, current: '0.41.11', latest: '0.42.0', build: 260, newer: true, note: '' };
let asked = 0;
const redraws = [];
globalThis.onAfterUiUpdate = (callback) => redraws.push(callback);
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/update')) {
        asked += 1;
        return reply(update);
    }
    return reply({ success: true });
};

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const notice = () => document.querySelector('.gen-header .mm-update');
await waitFor('the notice', () => notice());
check('beside the version, the version out, linking where the version does - the changelog',
      [notice().previousElementSibling?.className, notice().textContent, notice().getAttribute('href'),
       notice().target],
      ['mm-version', 'v0.42.0.260 available', document.querySelector('.gen-header a.mm-version')?.getAttribute('href'), '_blank']);
check('its tooltip says how to update', /Extensions -> Check for updates/.test(notice().title), true);
check('asked once for the page, however many tabs', asked, 1);

// Gradio redraws the header's markup wholesale.
document.querySelector('.gen-header .mm-header-actions').outerHTML = HEADER;
check('a redraw takes it away', notice(), null);
redraws.forEach((callback) => callback());
check('and after the redraw it is back, once', document.querySelectorAll('.gen-header .mm-update').length, 1);

// A version.json from before the build was written down: the version alone.
update = { success: true, current: '0.41.11', latest: '0.42.0', build: null, newer: true, note: '' };
window.dispatchEvent(new window.CustomEvent('mm-settings-saved',
    { detail: { changed: ['model_manager_check_updates'], settings: {} } }));
await waitFor('the version alone', () => notice()?.textContent === 'v0.42.0 available');
check('without a build, the version alone', notice().textContent, 'v0.42.0 available');

// Turned off in the settings window: the server says nothing is newer.
update = { success: true, current: '0.41.11', latest: null, newer: false, note: '' };
window.dispatchEvent(new window.CustomEvent('mm-settings-saved',
    { detail: { changed: ['model_manager_check_updates'], settings: {} } }));
await waitFor('the notice gone', () => !notice());
check('the setting turned off, it goes', notice(), null);

// A change to another setting does not ask.
const before = asked;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved',
    { detail: { changed: ['model_manager_page_size'], settings: {} } }));
await new Promise((resolve) => setTimeout(resolve, 50));
check('another setting saved: not asked again', asked, before);

done();
