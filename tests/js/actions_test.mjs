// Markup says what it does by name (shared/calls.mjs, #95). It said it in
// JavaScript - onclick="window.mmSelectModel(3)" - reaching window globals by
// names in strings, in the modules' templates and the tabs' Python, which no
// check followed: a rename broke a button only when it was pressed.
//
// Here, the page's one listener: a click calls what the innermost data-action
// names, with the element's other data; a field acts on its change, not its
// click; a link stays where it is; nothing else is stopped - Copy JSON in the
// metadata window reaches its listener; a name nothing provides says so. And
// with the three tabs loaded, every action their markup names is there.
import { readFileSync } from 'node:fs';
import { ROOT, checker, mountTab, sharedModule, startServices, startTab, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
for (const tab of ['tab_civitai_browser.py', 'tab_generations.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${tab}`));
}
const { check, done } = checker();

const warned = [];
const warn = console.warn;
console.warn = (...args) => warned.push(args.join(' '));

// Started, as a tab starts it (#182) - the second copy too: it listens to nothing.
const { provide } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
await startServices('calls.mjs');
const { createScope } = await sharedModule('loading.mjs');
(await import(`file:///${ROOT}/javascript/shared/calls.mjs?again`)).start(createScope('again'));
const pressed = [];
provide('test.card', (data, element) => pressed.push(['card', data, element.id]));
provide('test.pin', (data) => pressed.push(['pin', data]));
provide('test.tick', (data, box) => pressed.push(['tick', box.checked]));
provide('test.link', () => pressed.push(['link']));

document.body.insertAdjacentHTML('beforeend', `
    <div id="test_card" data-action="test.card" data-index="3" data-model-id="70">
        <span id="test_name">A model</span>
        <button type="button" id="test_pin" data-action="test.pin" data-index="3">📌</button>
    </div>
    <label><input type="checkbox" id="test_tick" data-action="test.tick"> Tick</label>
    <a href="#elsewhere" id="test_link" data-action="test.link">Settings</a>
    <button type="button" id="test_nothing" data-action="test.nobody">Nothing</button>`);
const $ = (id) => document.getElementById(id);
const click = (element) => {
    const event = new window.Event('click', { bubbles: true, cancelable: true });
    element.dispatchEvent(event);
    return event;
};
let reached = 0;
document.addEventListener('click', () => { reached += 1; });

click($('test_name'));
check('a click inside an element calls what it names, with its data and itself',
      pressed.splice(0), [['card', { index: '3', modelId: '70' }, 'test_card']]);
click($('test_pin'));
check('a button inside it calls its own, not the card\'s', pressed.splice(0), [['pin', { index: '3' }]]);
check('and nothing is stopped: the page saw both clicks', reached, 2);

const box = $('test_tick');
box.checked = true;
click(box);
check('a field\'s click does nothing', pressed.splice(0), []);
box.dispatchEvent(new window.Event('change', { bubbles: true }));
check('its change does, once - however many copies of the module are loaded', pressed.splice(0), [['tick', true]]);

check('a link does what it names, and stays where it is',
      [click($('test_link')).defaultPrevented, pressed.splice(0)], [true, [['link']]]);
click($('test_nothing'));
check('a name nothing provides says so', warned.splice(0),
      ['[ModelManager] test.nobody is not ready: its tab has not loaded']);

// The metadata window's Copy JSON: a stop in the window kept its click from
// the listener that copies (shared/core.mjs), and the button did nothing.
const { showImageMeta } = await import(`file:///${ROOT}/javascript/shared/image_card.mjs`);
await startServices('core.mjs');
let copied = null;
Object.defineProperty(globalThis, 'navigator', { configurable: true,
    value: { clipboard: { writeText: (text) => { copied = text; return Promise.resolve(); } } } });
showImageMeta({ id: 1, meta: { prompt: 'a lighthouse', steps: 20 } });
const copy = document.querySelector('.mm-modal-overlay [data-copy]');
check('the metadata window\'s markup stops nothing', document.querySelector('.mm-modal-overlay [onclick]'), null);
click(copy);
check('Copy JSON copies the image\'s data', JSON.parse(copied ?? 'null'), { prompt: 'a lighthouse', steps: 20 });

// ------------------------------------------- every action the tabs name
globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async () => ({ ok: true, json: async () => ({ success: true }) });
await startTab('modelManager');
await startTab('civitaiBrowser');
await startTab('generations');
const { ready } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
const { downloads } = await import(`file:///${ROOT}/javascript/shared/downloads.mjs`);
downloads();                                  // the panels' own, offered once the list is made
const named = [...new Set([...document.querySelectorAll('[data-action]')].map((el) => el.dataset.action))]
    .filter((name) => !name.startsWith('test.'));
check('the tabs\' markup names actions', named.length > 0, true);
check('and with the tabs loaded, each is there', named.filter((name) => !ready(name)), []);

console.warn = warn;
done();
