// The Model Manager's Type filter (#341): one type picked at a time, as a
// dropdown picks, unless Select several is ticked; Combine LoRA kinds folding
// the six kinds into one row, and changed with the tab open; Checkpoint Type
// usable while Checkpoint is among the ticked; and the saved search, which
// keeps several types comma-joined. The server's side: api_test.py.
import { checker, mountTab, startTab, act } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const listed = [];
const saves = [];
let savedOnServer = { type: 'Checkpoint,LORA' };
let uiAsked = 0;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/saved-search')) {
        if (init.method === 'POST') {
            saves.push(JSON.parse(init.body));
            savedOnServer = saves.at(-1).filters;
        }
        return { ok: true, json: async () => ({ success: true, filters: savedOnServer }) };
    }
    if (href.includes('/model-manager/ui-options')) {
        uiAsked += 1;
        return { ok: true, json: async () => ({ success: true, combine_lora_kinds: false }) };
    }
    if (href.includes('/model-manager/models?') || href.endsWith('/model-manager/models')) {
        listed.push(new URL(href, 'http://webui').searchParams);
    }
    return { ok: true, json: async () => ({ success: true, models: [], total: 0, page: 1, page_size: 20 }) };
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const load = async () => {
    const before = listed.length;
    $('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the grid request', () => listed.length > before);
    return listed.at(-1);
};
const row = (value) => document.querySelector(`#mm_type_panel input[value="${value}"]`);
const LORA_ROW = 'LORA,LoCon,LoHa,LoKr,DoRA,LyCORIS Full';
// A row a break left out is not clicked, so the checks after say so rather than the suite crash.
const click = (box) => {
    if (!box) return;
    box.checked = !box.checked;
    box.dispatchEvent(new window.Event('change', { bubbles: true }));
};
const ticked = () => [...document.querySelectorAll('#mm_type_panel input[type="checkbox"][value]')]
    .filter((box) => box.checked && box.value && !box.closest('[hidden]')).map((box) => box.value);
const shown = (value) => !row(value).closest('[hidden]');
const isOpen = () => $('mm_type_panel').classList.contains('open');
const usable = () => !$('mm_checkpoint_type').disabled;
const setting = (on) => window.dispatchEvent(new window.CustomEvent('mm-settings-saved', {
    detail: { changed: ['model_manager_combine_lora_kinds'],
              settings: { model_manager_combine_lora_kinds: { value: on } } } }));

check('Type is a list of rows with Select several at its bottom',
      [Boolean($('mm_type_panel')), $('mm_type_panel')?.lastElementChild?.contains($('mm_type_several'))],
      [true, true]);
if (!$('mm_type_panel')) done();           // the code before #341: nothing more to press

// ------------------------------------------------------- a saved search
await waitFor('the saved search', () => ticked().length === 2);
check('a search saved with two types ticks both, and Select several',
      [ticked(), $('mm_type_several').checked], [['Checkpoint', 'LORA'], true]);
check('the box names both', $('mm_type_display').textContent, 'Checkpoint, LORA');
check('Checkpoint Type is usable with Checkpoint among them', usable(), true);
let asked = await load();
check('Load Models asks for both, comma-joined', asked.get('type'), 'Checkpoint,LORA');

// ---------------------------------------------------- several types
click(row('Checkpoint'));
check('ticked off, Checkpoint Type greys', usable(), false);
click(row('TextualInversion'));
check('with Select several a click ticks one more, the list staying open as it was',
      [ticked(), isOpen()], [['LORA', 'TextualInversion'], false]);
asked = await load();
check('and Load Models asks for LORA and Embedding', asked.get('type'), 'LORA,TextualInversion');
click(row('VAE'));
check('past two, the box counts them', $('mm_type_display').textContent, '3 types');

act('modelManager.toggleTypeDropdown');
click(row('Checkpoint'));
check('in Select several the list stays open after a click', isOpen(), true);
check('and Checkpoint among others makes Checkpoint Type usable', usable(), true);

// Every row ticked is every type: no type asked, and no Trained or Merge, as
// the Civitai Browser does - Merge would otherwise narrow the grid to merges.
const all = [...document.querySelectorAll('#mm_type_panel input[type="checkbox"][value]')]
    .filter((box) => box.value && !box.closest('[hidden]'));
const wasTicked = all.filter((box) => box.checked);
all.forEach((box) => { if (!box.checked) click(box); });
check('every row ticked says All, and greys Checkpoint Type', [$('mm_type_display').textContent, usable()],
      ['All', false]);
asked = await load();
check('and asks for no type', asked.has('type') ? asked.get('type') : '', '');
all.forEach((box) => { if (box.checked !== wasTicked.includes(box)) click(box); });

// Unticked with several types ticked, the first in the list's order stays.
click($('mm_type_several'));
check('Select several unticked: the first ticked, in the list\'s order, stays',
      [ticked(), $('mm_type_display').textContent], [['Checkpoint'], 'Checkpoint']);

// --------------------------------------------------------- one type
click(row('LoKr'));
check('one type at a time: a click picks its row alone, and closes the list',
      [ticked(), isOpen(), $('mm_type_display').textContent], [['LoKr'], false, 'LoKr']);
check('the picked row is marked, and the list says it picks one',
      [row('LoKr').closest('label').classList.contains('tick-list-picked'),
       $('mm_type_panel').classList.contains('tick-list-one')], [true, true]);
click(row('LoKr'));
check('a click on the row already picked keeps it', ticked(), ['LoKr']);
asked = await load();
check('Load Models asks for it alone', asked.get('type'), 'LoKr');
click(row(''));
check('All unticks every row, and says All', [ticked(), row('').checked, $('mm_type_display').textContent],
      [[], true, 'All']);
asked = await load();
check('and asks for every type', asked.has('type') ? asked.get('type') : '', '');

// ---------------------------------------------------- the setting
click(row('LoKr'));
const before = listed.length;
setting(true);
check('turned on, the six kinds become one row, ticked for LoKr', [shown(LORA_ROW), shown('LoKr'), ticked()],
      [true, false, [LORA_ROW]]);
check('the box names the row', $('mm_type_display').textContent, 'LoRA, every kind');
await new Promise((resolve) => setImmediate(resolve));
check('the grid is not reloaded', listed.length, before);
asked = await load();
check('Load Models asks for every kind', asked.get('type'), LORA_ROW);

setting(false);
check('turned off with one type at a time: LORA alone, the first kind', [shown('LORA'), ticked()],
      [true, ['LORA']]);
setting(true);
click($('mm_type_several'));
click(row('Checkpoint'));
setting(false);
check('turned off with Select several: every kind ticked, with the rest', ticked(),
      ['Checkpoint', 'LORA', 'LoCon', 'LoHa', 'LoKr', 'DoRA', 'LyCORIS Full']);

// ------------------------------------------------------ Save Search
$('mm_save_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the save', () => saves.length > 0);
check('Save Search keeps the types comma-joined', saves.at(-1).filters.type,
      'Checkpoint,LORA,LoCon,LoHa,LoKr,DoRA,LyCORIS Full');

done();
