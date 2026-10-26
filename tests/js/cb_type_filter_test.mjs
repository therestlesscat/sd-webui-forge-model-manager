// The Civitai Browser's Type filter (#341): Civitai's own list of types as
// rows, one picked at a time unless Select several is ticked; several asked
// for comma-joined, with Checkpoint Type sent while Checkpoint is among them,
// as Civitai then narrows the checkpoints alone; and Combine LoRA kinds,
// Civitai's LORA, LoCon and DoRA as one row. Our client sends each as its
// own parameter to Civitai: client_test.py.
import { act, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const TYPES = ['Checkpoint', 'TextualInversion', 'Hypernetwork', 'LORA', 'LoCon', 'DoRA', 'Controlnet', 'Upscaler',
               'VAE', 'Poses', 'Other'];
const searches = [];
let combined = true;
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/civitai/enums')) {
        return { ok: true, json: async () => ({ success: true, model_types: TYPES, base_models: ['SDXL 1.0'] }) };
    }
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({ success: true, combine_lora_kinds: combined }) };
    }
    if (href.includes('/model-manager/civitai/models')) {
        searches.push(new URL(href, 'http://webui').searchParams);
        const queue = [{ type: 'meta', pageSize: 20 }, { type: 'done', nextCursor: null, filterStats: {} }]
            .map((line) => new TextEncoder().encode(JSON.stringify(line) + '\n'));
        return { ok: true, json: async () => ({ success: true, models: [], pageSize: 20 }),
                 body: { getReader: () => ({ read: async () => (queue.length ? { done: false, value: queue.shift() }
                                                                               : { done: true }),
                                             cancel: async () => {} }) } };
    }
    return { ok: true, json: async () => ({ success: true, filters: null }) };
};

await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const row = (value) => document.querySelector(`#cb_type_panel input[value="${value}"]`);
// A row a break left out is not clicked, so the checks after say so rather than the suite crash.
const click = (box) => {
    if (!box) return;
    box.checked = !box.checked;
    box.dispatchEvent(new window.Event('change', { bubbles: true }));
};
const shown = () => [...document.querySelectorAll('#cb_type_panel input[type="checkbox"][value]')]
    .filter((box) => box.value && !box.closest('[hidden]')).map((box) => box.value);
const search = async () => {
    const before = searches.length;
    act('civitaiBrowser.search');
    await waitFor('the search', () => searches.length > before);
    return searches.at(-1);
};

check('Type is a list of rows with Select several at its bottom',
      [Boolean($('cb_type_panel')), $('cb_type_panel')?.lastElementChild?.contains($('cb_type_several'))],
      [true, true]);
if (!$('cb_type_panel')) done();           // the code before #341: nothing more to press

// ------------------------------------------------ Civitai's list, combined
await waitFor("Civitai's list as rows", () => shown().includes('Poses'));
check("Civitai's types as rows, its kinds of LoRA one row with the setting on", shown(),
      ['Checkpoint', 'TextualInversion', 'Hypernetwork', 'LORA,LoCon,DoRA', 'Controlnet', 'Upscaler', 'VAE',
       'Poses', 'Other']);
check('Checkpoint still picked, as the page started', [row('Checkpoint')?.checked, $('cb_type_display').textContent],
      [true, 'Checkpoint']);
let asked = await search();
check('a search asks for Checkpoint', asked.get('types'), 'Checkpoint');

click(row('LORA,LoCon,DoRA'));
check('one type at a time: the LoRA row picked alone', [row('Checkpoint')?.checked, $('cb_type_display').textContent],
      [false, 'LoRA, every kind']);
check('Checkpoint Type greys without Checkpoint', $('cb_checkpoint_type').disabled, true);
asked = await search();
check('and a search asks for every kind of LoRA', asked.get('types'), 'LORA,LoCon,DoRA');

// ------------------------------------------------------ several types
click($('cb_type_several'));
click(row('Checkpoint'));
$('cb_checkpoint_type').value = 'Merge';
check('with Select several, Checkpoint beside the LoRA row makes Checkpoint Type usable',
      $('cb_checkpoint_type').disabled, false);
asked = await search();
check('a search asks for both, and Merge for the checkpoints',
      [asked.get('types'), asked.get('checkpoint_type')], ['Checkpoint,LORA,LoCon,DoRA', 'Merge']);

// ------------------------------------------------- the setting turned off
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', {
    detail: { changed: ['model_manager_combine_lora_kinds'],
              settings: { model_manager_combine_lora_kinds: { value: false } } } }));
check('turned off, a row for each of Civitai\'s kinds, all ticked with Select several',
      [shown().includes('LoCon'), shown().includes('LORA,LoCon,DoRA'),
       ['LORA', 'LoCon', 'DoRA'].map((v) => row(v)?.checked)], [true, false, [true, true, true]]);
check('the box counts the types', $('cb_type_display').textContent, '4 types');
click(row('LoCon'));
click(row('DoRA'));
click(row('Checkpoint'));
asked = await search();
check('a search asks for the one left, with no Checkpoint Type', [asked.get('types'), asked.has('checkpoint_type')],
      ['LORA', false]);

done();
