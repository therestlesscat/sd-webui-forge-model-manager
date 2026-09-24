// The Civitai Browser's tag filter: suggestions, then a chip.
//
// Typing still brings up Civitai's matching tags. Choosing one - a click, or
// Enter on a highlighted one - turns it into a rounded chip with an x in the
// box's place, so a tag in force reads as a filter, not as text half typed.
// The x takes it out and gives the empty box back. Text typed and never
// chosen still counts, as it always did, and becomes a chip on Enter or at
// Search, so what the search is filtered by is always on show.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const searched = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    const params = new URL(href, 'http://webui').searchParams;
    if (href.includes('/model-manager/civitai/tags')) {
        const q = params.get('query');
        return { ok: true, json: async () => ({ success: true,
            tags: ['anime', 'animal', '<b>anim</b>'].filter((t) => t.includes(q)) }) };
    }
    if (href.includes('/model-manager/civitai/models')) {
        searched.push(params.get('tag'));
        return { ok: true, json: async () => ({ success: true, models: [], nextCursor: null }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const input = $('cb_tag_input');
const chipShown = () => $('cb_tag_selected').style.display !== 'none';
const inputShown = () => input.style.display !== 'none';
const suggestions = () => Array.from(document.querySelectorAll('#cb_tag_dropdown .cb-tag-dropdown-item'))
    .map((i) => i.textContent);
const key = (k) => input.dispatchEvent(Object.assign(new window.Event('keydown'), { key: k, preventDefault() {} }));
const type = (text) => { input.value = text; input.dispatchEvent(new window.Event('input')); };
// One search, run to the end: another while it is loading would be ignored.
async function search() {
    const before = searched.length;
    $('cb_status').textContent = '';
    window.cbSearch();
    await waitFor('the search', () => searched.length > before
        && $('cb_status').textContent.startsWith('Showing'));
    return searched[searched.length - 1];
}

check('nothing chosen: the box, and no chip', [inputShown(), chipShown()], [true, false]);
check('the caption says Civitai takes only one tag',
      input.closest('.filter-group').querySelector('label').textContent,
      'Tag (only a single tag is allowed by the Civitai API)');

// ------------------------------------------------------- no wait, no stale list
// Suggestions are asked for on every keystroke, with no pause first...
const asked = [];
const realFetch = globalThis.fetch;
let holdAni = null;
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/civitai/tags')) {
        const q = new URL(href, 'http://webui').searchParams.get('query');
        asked.push(q);
        // ...so the answer for "ani" is held back until after "anime" has been answered.
        if (q === 'ani') await new Promise((r) => { holdAni = r; });
        return { ok: true, json: async () => ({ success: true, tags: [`${q}-tag`] }) };
    }
    return realFetch(url);
};
type('ani');
type('anime');
await waitFor('both lookups', () => asked.length === 2, 10);
check('each keystroke asks at once, without a wait', asked, ['ani', 'anime']);
await waitFor('the newer answer', () => suggestions().length === 1);
holdAni?.();
await new Promise((r) => setTimeout(r, 50));
check('and an older answer arriving late does not replace a newer one', suggestions(), ['anime-tag']);
key('Escape');
type('');
globalThis.fetch = realFetch;

// ------------------------------------------------ suggestions, then a chip
type('anim');
await waitFor('the suggestions', () => suggestions().length === 3);
check('typing still brings up Civitai\'s matching tags', suggestions(),
      ['anime', 'animal', '<b>anim</b>']);
key('ArrowDown');
key('Enter');
check('Enter on a highlighted one makes it a chip', $('cb_tag_chip_name').textContent, 'anime');
check('in the box\'s place', [chipShown(), inputShown()], [true, false]);
check('and the suggestions close', suggestions().length === 0
      || !$('cb_tag_dropdown').classList.contains('show'), true);
check('the chip has its x', $('cb_tag_chip_remove')?.getAttribute('aria-label'), 'Remove tag');
check('the search is filtered by it', await search(), 'anime');

$('cb_tag_chip_remove').dispatchEvent(new window.Event('click', { bubbles: true }));
check('the x takes it out and gives the empty box back',
      [chipShown(), inputShown(), input.value], [false, true, '']);
check('and the search is no longer filtered by a tag', await search(), null);

// A click on a suggestion does the same; and a tag's name is text, not markup.
type('anim');
await waitFor('the suggestions', () => suggestions().length === 3);
document.querySelectorAll('#cb_tag_dropdown .cb-tag-dropdown-item')[2]
    .dispatchEvent(new window.Event('click', { bubbles: true }));
check('clicking a suggestion makes it a chip, shown as text',
      [$('cb_tag_chip_name').textContent, $('cb_tag_chip_name').querySelector('b')],
      ['<b>anim</b>', null]);
$('cb_tag_chip_remove').dispatchEvent(new window.Event('click', { bubbles: true }));

// ----------------------------------------------------------- typed, not chosen
type('cats');
key('Enter');
check('Enter with nothing highlighted makes a chip of what was typed',
      [$('cb_tag_chip_name').textContent, chipShown()], ['cats', true]);
$('cb_tag_chip_remove').dispatchEvent(new window.Event('click', { bubbles: true }));

type('dogs');
check('text typed and never chosen still filters the search', await search(), 'dogs');
check('and is shown as a chip once it does', [$('cb_tag_chip_name').textContent, chipShown()],
      ['dogs', true]);

done();
