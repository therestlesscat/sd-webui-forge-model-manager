// The Model Manager's two lists of checkboxes, NSFW Levels and Commercial
// Use: opened and closed by their box, closed by a click outside, their text,
// and what Load Models asks with them. Written before #341 moved both onto the
// shared tick list (shared/tick_list.mjs), and run on the code before it, so
// the move is shown to change none of it.
import { checker, mountTab, startTab, act } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const listed = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/saved-search')) {
        return { ok: true, json: async () => ({ success: true, filters: null }) };
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
const clickBox = (box) => {
    box.checked = !box.checked;
    box.dispatchEvent(new window.Event('change', { bubbles: true }));
};
const level = (value) => document.querySelector(`#mm_nsfw_panel input[value="${value}"]`);
const ticked = (panel) => [...document.querySelectorAll(`#${panel} input[type="checkbox"][value]`)]
    .filter((box) => box.checked).map((box) => box.value);
const isOpen = (panel) => $(panel).classList.contains('open');

// ------------------------------------------------------------ NSFW Levels
check('NSFW Levels starts with every level, up to the highest', [$('mm_nsfw_display').textContent,
      ticked('mm_nsfw_panel').length], ['Max: Unknown', 7]);
act('modelManager.toggleNsfwDropdown');
check('its box opens the list', isOpen('mm_nsfw_panel'), true);
act('modelManager.toggleNsfwDropdown');
check('and closes it again', isOpen('mm_nsfw_panel'), false);
act('modelManager.toggleNsfwDropdown');
level('PG').dispatchEvent(new window.Event('click', { bubbles: true }));
check('a click inside leaves it open', isOpen('mm_nsfw_panel'), true);
document.body.dispatchEvent(new window.Event('click', { bubbles: true }));
check('a click outside closes it', isOpen('mm_nsfw_panel'), false);

clickBox(level('R'));
await waitFor('Use max level to tick every level up to R', () => ticked('mm_nsfw_panel').join() === 'PG,PG-13,R');
check('with Use max level, a level ticks every one below it, and the box says the highest',
      [ticked('mm_nsfw_panel'), $('mm_nsfw_display').textContent], [['PG', 'PG-13', 'R'], 'Max: R']);
let asked = await load();
check('Load Models asks up to it', [asked.get('nsfw_levels'), asked.get('nsfw_mode')], ['R', 'max']);

clickBox($('mm_nsfw_use_max'));
clickBox(level('PG-13'));
check('without it, levels tick one by one, and the box names each',
      [ticked('mm_nsfw_panel'), $('mm_nsfw_display').textContent], [['PG', 'R'], 'PG, R']);
asked = await load();
check('Load Models asks for those', [asked.get('nsfw_levels'), asked.get('nsfw_mode')], ['PG,R', 'contains']);

// ---------------------------------------------------------- Commercial Use
const use = (value) => document.querySelector(`#mm_commercial_panel input[value="${value}"]`);
check('Commercial Use starts with every use, and says All', [$('mm_commercial_display').textContent,
      ticked('mm_commercial_panel').length], ['All', 5]);
act('modelManager.toggleCommercialDropdown');
check('its box opens the list', isOpen('mm_commercial_panel'), true);
document.body.dispatchEvent(new window.Event('click', { bubbles: true }));
check('a click outside closes it', isOpen('mm_commercial_panel'), false);
asked = await load();
check('every use ticked asks nothing', asked.has('commercial_use'), false);
clickBox(use('Rent'));
clickBox(use('Sell'));
check('unticked ones leave the rest named', $('mm_commercial_display').textContent, 'None, Image, RentCivit');
asked = await load();
check('and Load Models asks for those', asked.get('commercial_use'), 'None,Image,RentCivit');
clickBox(use('None')); clickBox(use('Image')); clickBox(use('RentCivit'));
check('none ticked says All', $('mm_commercial_display').textContent, 'All');
asked = await load();
check('and asks nothing', asked.has('commercial_use'), false);

done();
