// A page the server refuses: reached by a name the WebUI does not know,
// while it listens on this computer alone, its first answer - ui-options -
// is the refusal: {success: false, refused, error}. The loading module then
// starts no tab - every request would be refused - and covers each tab that
// is on with a notice in the server's own words, and the one step the page
// adds: reload. Its switches come from Forge's own options, as the page loads
// and as they change: a tab off hides, one on shows under the notice, and
// nothing starts or asks for a reload. Its button shows Forge's Settings tab,
// as the settings window would ask the server too. The server's side:
// request_origin_test.py.
import { bootPage, checker, mountTab, press, settingsPageApplied, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// The other four tabs, Forge's tab bar with its Settings tab, and the Queue
// buttons. The Civitai Browser's markup is there, its button not: a tab this
// start did not build, which no notice covers.
for (const file of ['tab_queue.py', 'tab_generations.py', 'tab_gallery.py', 'tab_civitai_browser.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${file}`));
}
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button" class="selected" aria-selected="true">txt2img</button>
        <button id="tab_queue_tab-button">Queue</button>
        <button id="tab_generations_tab-button">Generations</button>
        <button id="tab_gallery_tab-button">Civitai Images</button>
        <button id="tab_model_manager_tab-button">Model Manager</button>
        <button id="tab_settings-button">Settings</button>
    </div>
    <div id="tab_settings" style="display: none"></div>
    <button id="txt2img_queue">Queue</button>
    <button id="img2img_queue">Queue</button>`);
const byId = (id) => document.getElementById(id);
byId('tab_settings-button').addEventListener('click', () => { byId('tab_settings').style.display = 'block'; });

// Forge's switches as the page loads: the Queue off - on where nothing is
// said - and Civitai Images off; the rest on.
Object.assign(globalThis.opts, {
    model_manager_queue_enabled: false, model_manager_record_generations: true, model_manager_gallery_tab: false,
    model_manager_model_manager_enabled: true, model_manager_civitai_browser_enabled: true,
});

// The server's words, holding markup a name could carry: drawn as text (S2).
const WORDS = 'Refused: this WebUI was reached as <b data-mm-marker>rebind</b>.example, a name it does not know. '
    + 'If that is how you reach it, add the name in Settings -> Model Manager -> Access.';
const asked = [];
globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    return { ok: false, status: 403,
             json: async () => ({ success: false, refused: 'rebind.example', error: WORDS }) };
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await new Promise((resolve) => setTimeout(resolve, 400));

const ROOTS = { queue: 'queue_app', generations: 'generations_app', gallery: 'gallery_app',
                modelManager: 'model_manager_app', civitaiBrowser: 'civitai_browser_app' };
const BUTTONS = { queue: 'tab_queue_tab-button', generations: 'tab_generations_tab-button',
                  gallery: 'tab_gallery_tab-button', modelManager: 'tab_model_manager_tab-button' };
const notice = (name) => byId(ROOTS[name])?.querySelector(':scope > .page-refused');
const shown = (name) => byId(BUTTONS[name]).style.display !== 'none';
const popup = () => document.querySelector('.mm-reload-dialog');
const offered = () => [...(globalThis.__mmOffered?.keys() || [])]
    .filter((name) => /^(queue|generations|gallery|modelManager|civitaiBrowser)\./.test(name));

check('each tab on and built is covered by the refusal\'s notice; the Queue and Civitai Images, off, and the Civitai Browser, not built, are not',
      Object.keys(ROOTS).map((name) => Boolean(notice(name))), [false, true, false, true, false]);
const text = notice('modelManager')?.textContent || '';
check('in the server\'s own words, and the one step the page adds',
      [text.includes(WORDS), text.includes('Then reload this page.')], [true, true]);
check('the words drawn as text, not markup (S2)', document.querySelectorAll('[data-mm-marker]').length, 0);
check('each tab\'s button as its switch says: the Queue\'s and Civitai Images\'s hidden', Object.keys(BUTTONS).map(shown),
      [false, true, false, true]);
check('no tab is started: none offers an action', offered(), []);
// The loader asks asset-version first, in the page; the harness boots without it.
check('and nothing is asked of the server but ui-options', [...new Set(asked)], ['/model-manager/ui-options']);
check('the Queue buttons beside Generate are hidden',
      ['txt2img_queue', 'img2img_queue'].map((id) => byId(id).style.display), ['none', 'none']);
check('no question about restarting or reloading', Boolean(popup()), false);

// Forge's Settings page applied: the switches hide and show the tabs, and
// nothing starts or asks for a reload - the page that read Civitai Images as
// off and newly on asked for a Reload UI.
settingsPageApplied({ model_manager_gallery_tab: true, model_manager_record_generations: false });
await new Promise((resolve) => setTimeout(resolve, 50));
check('Civitai Images switched on shows, covered; Generations switched off hides; no question asked',
      [shown('gallery'), Boolean(notice('gallery')), shown('generations'), Boolean(popup())], [true, true, false, false]);
check('the Civitai Browser, not built at this start, still uncovered', Boolean(notice('civitaiBrowser')), false);
check('and still no tab is started, nothing more asked', [offered(), [...new Set(asked)]],
      [[], ['/model-manager/ui-options']]);

const button = [...(notice('modelManager')?.querySelectorAll('button') || [])]
    .find((b) => b.textContent.trim() === 'Open Settings');
if (button) {
    await press(button);
    await waitFor('the Settings tab to show', () => byId('tab_settings').style.display !== 'none');
}
check('Open Settings shows the WebUI\'s Settings tab', byId('tab_settings').style.display, 'block');

done();
