// The gallery's second tab: your own generations with the open model.
//
// Each model opens on its Civitai images; the tab beside them says how many
// generations there are, and opened, shows a card per generation - one image
// filling the card's image column, as most are, two to four sharing it, and
// "Show images (N)" for the rest. An image opens full size by its record's address;
// one whose file is gone says so and opens nothing. Send pastes the
// generation's own infotext, as Forge's PNG Info does, and Delete removes the
// record - and the files only with the box beside it ticked.
import { ROOT, act, checker, mountTab, startTab, tick, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// What a press opens, through the page's one click listener (#144).
function opens(element) {
    const opened = [];
    const before = window.open;
    window.open = (...args) => { opened.push(args); return null; };
    element?.dispatchEvent(new window.Event('click', { bubbles: true }));
    window.open = before;
    return opened;
}

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'Checkpoint',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1,
    trained_words: [], tags: [],
};
const OTHER = { ...MODEL, id: 5002, model_id: 4002, display_name: 'B Model',
                file_path: 'C:/models/b.safetensors', file_name: 'b.safetensors' };

const image = (id, generation, extra = {}) => ({
    id, generation_id: generation, position: 0, seed: 1000 + id, width: 832, height: 1216,
    meta: { prompt: `a lighthouse ${id}`, negativePrompt: 'blurry', steps: '30',
            sampler: 'DPM++ 2M', 'Schedule type': 'Karras', seed: String(1000 + id) },
    infotext: `a lighthouse ${id}`, url: `/model-manager/generations/images/${id}/file`,
    exists: true, mm_level: 1, mm_level_from_prompt: false, ...extra,
});
const CARDS = [
    { id: 1, created_at: '2026-09-28T15:30:13', mode: 'txt2img', image_count: 1, matching_count: 1,
      infotext: 'a lighthouse 1\nSteps: 30, Sampler: DPM++ 2M, Schedule type: Karras',
      images: [image(11, 1)] },
    { id: 2, created_at: '2026-09-28T15:40:00', mode: 'img2img', image_count: 6, matching_count: 6,
      infotext: 'a harbour\nSteps: 30',
      images: [image(21, 2), image(22, 2, { exists: false }), image(23, 2), image(24, 2)] },
];
// The first generation used a LoRA: its images list it, as a Civitai image lists its resources.
CARDS[0].images[0].meta.resources = [{ type: 'lora', name: 'add_detail', weight: 0.6, hash: 'aaaa1111' }];
const STATE = { offset: 0, generation_count: 2, total: 7, filtered: 7, hidden_nsfw: 0,
                hidden_promptless: 0, hidden: 0, nsfw_count: 0, promptless_count: 0 };

const asked = [];
const ratings = [];
let deleteBody = null;
globalThis.fetch = withGalleryPages(async (url, init = {}) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], has_api_key: true,
                       image_browsing: 'continuous' });
    }
    if (href.includes('/model-manager/generations/page')) {
        const cards = CARDS.filter((c) => !c.deleted);
        const shown = cards.reduce((n, c) => n + c.matching_count, 0);
        return reply({ success: true, generations: cards,
                       page: { number: 1, size: 100, generations: cards.length, count: shown, shown,
                               hidden_nsfw: 0, hidden_promptless: 0, more: false, error: null },
                       state: { ...STATE, generation_count: cards.length, stored_generations: cards.length } });
    }
    if (href.match(/\/model-manager\/generations\/2\/images/)) {
        return reply({ success: true, images: [21, 22, 23, 24, 25, 26].map((id) => image(id, 2)) });
    }
    if (href.includes('/model-manager/resolve-hashes')) {
        return reply({ success: true, deferred: [], resolved: {
            aaaa1111: { version_id: 11, model_id: 10, name: 'Add Detail', model_type: 'LORA', version_name: 'v1' } } });
    }
    if (href.includes('/model-manager/generations/rate')) {
        const form = Object.fromEntries(new URLSearchParams(String(init.body)));
        ratings.push(form);
        const level = form.level ? Number(form.level) : null;
        if (form.image_id) {
            return reply({ success: true, rated: 1, visible: !(level > 3),
                           image: image(Number(form.image_id), 2, { mm_level: level ?? 1, user_level: level }) });
        }
        Object.assign(CARDS[1], { level, user_level: level });
        return reply({ success: true, rated: 6 });
    }
    if (href.includes('/model-manager/generations/1/delete')) {
        deleteBody = String(init.body || '');
        CARDS[0].deleted = true;
        return reply({ success: true, deleted_files: 1, failed: [] });
    }
    if (href.includes('/models/details')) {
        const path = new URL(href, 'http://webui').searchParams.get('path');
        return reply({ success: true, model: { ...MODEL, file_path: path,
            images: [{ id: 99, url: 'https://example.invalid/99.jpeg', browsingLevel: 1, mm_level: 1,
                       meta: { prompt: 'a civitai image' } }],
            images_state: { version_id: 5001, total_count: 1, filtered_count: 1, offset: 0,
                            hide_nsfw_images: true, hide_promptless_images: true },
            generations_count: path.endsWith('a.safetensors') ? 2 : 0 } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 2, page: 1, page_size: 20, models: [MODEL, OTHER] });
    }
    return reply({ success: true });
});
window.confirm = globalThis.confirm = () => true;

// Each generation tab's prompt and paste button, for Send.
document.body.insertAdjacentHTML('beforeend', `
    <div id="txt2img_prompt"><textarea></textarea></div>
    <div id="txt2img_tools"><button id="paste"></button></div>
    <div id="img2img_prompt"><textarea></textarea></div>
    <div id="img2img_tools"><button id="paste"></button></div>`);
const pasted = { txt2img: 0, img2img: 0 };
for (const tab of ['txt2img', 'img2img']) {
    document.querySelector(`#${tab}_tools #paste`).addEventListener('click', () => { pasted[tab] += 1; });
}

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await act('modelManager.selectModel', { index: 0 });
await waitFor('the gallery', () => document.querySelector('#mm_images .mm-gallery-tab'));

const tabs = () => Array.from(document.querySelectorAll('#mm_images .mm-gallery-tab'))
    .map((t) => [t.textContent.trim(), t.classList.contains('active')]);
const cards = () => document.querySelectorAll('#mm_images .mm-generation-card');

check('the model opens on its Civitai images, the tab beside them counting its generations',
      tabs(), [['Civitai images', true], ['Your generations (2)', false]]);

await act('modelManager.showGalleryTab', { tab: 'generations' });
await waitFor('the cards', () => cards().length === 2);
check('opened, it asks for the open model\'s generations',
      asked.some((u) => u.includes('/generations/page') && u.includes('a.safetensors')), true);
check('and draws a card per generation', cards().length, 2);
check('page 1 of them, ending with its note - which says nothing of Civitai, as none come from it',
      Array.from(document.querySelectorAll('#mm_images .mm-page-note')).map((n) => n.textContent.trim()),
      ['Displaying 7 images for page 1']);
check('and, the last page, no Load More', !!document.getElementById('mm_show_more_generations_btn'), false);
check('one image fills the card\'s image column, as most generations are one',
      cards()[0].querySelector('.mm-generation-preview').className.includes('preview-1'), true);
check('four share it', cards()[1].querySelector('.mm-generation-preview').className.includes('preview-4'), true);

const firstImage = cards()[0].querySelector('img');
check('an image opens in the viewer, by its record',
      firstImage.getAttribute('data-view-generation-image'), '11');
const missing = cards()[1].querySelectorAll('.mm-generation-tile img')[1];
check('one whose file is gone says so, and opens nothing',
      [missing.getAttribute('alt'), missing.hasAttribute('data-view-generation-image')], ['Image unavailable', false]);
check('the card says when, how, and how many',
      cards()[1].querySelector('.mm-generation-when').textContent.includes('img2img · 6 images'), true);
check('with the settings as a Civitai image\'s card shows them',
      cards()[0].querySelector('.mm-image-params').textContent.includes('Sampler: DPM++ 2M'), true);

const buttons = (card) => Array.from(card.querySelectorAll('.mm-image-actions button'))
    .map((b) => b.textContent.trim());
check('a generation shown whole has no "Show images"', buttons(cards()[0]).some((b) => b.startsWith('Show images')), false);
check('one with more than its preview has, with how many', buttons(cards()[1]).includes('Show images (6)'), true);
const firstGeneration = cards()[0];
await act('modelManager.showAllGeneration', { generation: 2 });
check('only that card is drawn again: the others stay as they were',
      [cards()[0] === firstGeneration, firstGeneration.isConnected], [true, true]);
check('which shows all of them, in the card',
      cards()[1].querySelectorAll('.mm-generation-all img').length, 6);
check('and then offers to hide them again', buttons(cards()[1]).includes('Hide images (6)'), true);

// Resources: what a generation used, as a Civitai image's card offers it.
await waitFor('the Resources button', () => buttons(cards()[0]).includes('Resources (1)'));
check('a card whose images used a LoRA offers Resources, counting it; one that used none, nothing',
      [buttons(cards()[0]).includes('Resources (1)'), buttons(cards()[1]).some((b) => b.startsWith('Resources'))],
      [true, false]);
await act('modelManager.showGenerationResources', { generation: 1 });
const modal = document.querySelector('.mm-resources-modal');
check('which opens the Resources dialog on them, as a Civitai image\'s does',
      Array.from(modal?.querySelectorAll('.mm-res-name') || []).map((n) => n.textContent.trim()), ['Add Detail v1']);
document.querySelectorAll('.mm-modal-overlay').forEach((overlay) => overlay.remove());

// The viewer: a click on an image opens it on the images the cards show, each
// with its own Send, Resources, Delete and rating.
const viewer = () => document.querySelector('.mm-viewer');
cards()[0].querySelector('img[data-view-generation-image]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('a click on an image opens the viewer on it',
      [!!viewer(), viewer()?.querySelector('.mm-viewer-image')?.getAttribute('src')],
      [true, 'http://localhost:7860/model-manager/generations/images/11/file']);
check('with its own Send, Resources and Delete, and its rating row, below it',
      [Array.from(viewer().querySelectorAll('.mm-viewer-actions > button')).map((b) => b.textContent.trim()),
       viewer().querySelectorAll('.mm-viewer-actions .mm-rate-chip').length],
      [['Send to txt2img', 'Resources (1)', 'Delete'], 5]);
// Its id, to name one image when reporting what it did.
check('its details say the image\'s id',
      viewer().querySelector('.mm-viewer-info .mm-generation-when')?.textContent.trim().endsWith('Image ID 11'), true);
const fullSize = Array.from(viewer().querySelectorAll('.mm-viewer-info .mm-dialog-buttons > *'))
    .find((e) => e.textContent.trim() === 'Open full size');
check('Open full size is a button, and opens the file (#144)',
      [fullSize?.tagName, opens(fullSize)],
      ['BUTTON', [['http://localhost:7860/model-manager/generations/images/11/file', '_blank', 'noopener']]]);
document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'ArrowRight' }));
check('→ the next card\'s images', viewer()?.querySelector('.mm-viewer-where')?.textContent, '1 of 6 in this generation');
document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'Escape' }));
check('and Esc closes it', viewer(), null);
// Its Send saves where the gallery was when the viewer opened, for "Previous
// Position": while it is open the page is held still.
Object.defineProperty(window, 'scrollY', { value: 1234, configurable: true });
cards()[0].querySelector('img[data-view-generation-image]').dispatchEvent(new window.Event('click', { bubbles: true }));
Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
localStorage.removeItem('mm_scroll_position');
document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'ArrowRight' }));
const sentId = viewer()?.querySelector('.mm-viewer-image')?.getAttribute('src').match(/images\/(\d+)\//)?.[1];
viewer().querySelector('[data-gen-send]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('a Send from the viewer saves where the gallery was, and closes it',
      [localStorage.getItem('mm_scroll_position'), viewer()], ['1234', null]);
const intoView = [];
window.HTMLElement.prototype.scrollIntoView = function() { intoView.push(this); };
act('modelManager.restoreScrollPosition');
check('and Previous Position brings back the image sent, not the one the viewer opened on',
      [sentId !== '11', intoView.map((el) => el.getAttribute('data-view-generation-image'))], [true, [sentId]]);
Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
await new Promise((resolve) => setTimeout(resolve, 50));
pasted.txt2img = 0;
pasted.img2img = 0;

check('a card sends back to the tab its generation was made in',
      [buttons(cards()[0])[0], buttons(cards()[1])[0]], ['Send to txt2img', 'Send to img2img']);
await act('modelManager.sendGeneration', { generation: 1 });
check('Send pastes the generation\'s own infotext, and presses paste',
      [document.querySelector('#txt2img_prompt textarea').value, pasted.txt2img],
      ['a lighthouse 1\nSteps: 30, Sampler: DPM++ 2M, Schedule type: Karras', 1]);
await act('modelManager.sendGeneration', { generation: 2 });
check('an img2img generation\'s goes to img2img', [document.querySelector('#img2img_prompt textarea').value,
      pasted.img2img], ['a harbour\nSteps: 30', 1]);
check('saying its source image is not kept',
      document.querySelector('.mm-notice')?.textContent.includes('drop an image in'), true);
check('and coming back from txt2img or img2img, the gallery is still on your generations, as left',
      [tabs()[1][1], cards().length], [true, 2]);

// Generated meanwhile: Refresh shows it, and the label counts it.
CARDS.push({ id: 3, created_at: '2026-09-28T16:00:00', mode: 'txt2img', image_count: 1,
             matching_count: 1, infotext: 'a pier', images: [image(31, 3)] });
check('the header offers Refresh on your generations',
      !!document.querySelector('#mm_images .mm-refresh-generations'), true);
await act('modelManager.refreshGenerations');
check('which shows what was generated since, and counts it in the tab\'s label',
      [cards().length, tabs()[1][0]], [3, 'Your generations (3)']);
CARDS.pop();
const askedBefore = asked.length;
await act('modelManager.showGalleryTab', { tab: 'civitai' });
check('Civitai\'s tab has no Refresh', !!document.querySelector('#mm_images .mm-refresh-generations'), false);
await act('modelManager.showGalleryTab', { tab: 'generations' });
check('and opening your generations again fetches them again',
      asked.slice(askedBefore).some((u) => u.includes('/generations/page')), true);
await waitFor('the cards again', () => cards().length === 2);

cards()[0].querySelector('input[type="checkbox"]').checked = true;
const remaining = cards()[1];
await act('modelManager.deleteGeneration', { generation: 1 });
check('Delete, with the box ticked, asks for the files to go too', deleteBody, 'delete_files=true');
await waitFor('the card gone', () => cards().length === 1);
check('and its card goes where it was: the rest are not drawn again, and the tab counts one fewer',
      [cards()[0] === remaining, tabs()[1][0]], [true, 'Your generations (1)']);
check('the card left still names its own generation, not its old place',
      ['action', 'generation'].map((key) => cards()[0].querySelector('.mm-send-btn').dataset[key]),
      ['modelManager.sendGeneration', '2']);

// "Rate": a row of NSFW levels on each card, and on each image "Show images"
// shows - a card's rates every image of it this gallery shows.
check('the tab offers "Rate", unticked', document.getElementById('mm_rate_generations')?.checked, false);
tick('modelManager.rateGenerations', true);
const cardRow = () => cards()[0].querySelector('.mm-image-left .mm-rate');
check('ticked, a card has a row of levels under its images',
      Array.from(cardRow()?.querySelectorAll('.mm-rate-chip') || []).map((c) => c.textContent.trim()),
      ['PG', 'PG-13', 'R', 'X', 'XXX']);
const pagesBefore = asked.filter((u) => u.includes('/generations/page')).length;
await act('modelManager.rateGeneration', { generation: 2, level: 4 });
check('a card rated: every image of it the gallery shows, by the model\'s file and the generation',
      [ratings.at(-1).path, ratings.at(-1).generation, ratings.at(-1).level, ratings.at(-1).hide_promptless_images],
      ['C:/models/a.safetensors', '2', '4', 'true']);
check('and the cards loaded again, the rating marked as yours',
      [asked.filter((u) => u.includes('/generations/page')).length > pagesBefore,
       cardRow()?.querySelector('.mm-rate-mine')?.textContent.trim()], [true, 'R']);
// (The stand-in hands back the same card objects, so it may still be open from above.)
if (!cards()[0].querySelector('.mm-generation-all')) await act('modelManager.showAllGeneration', { generation: 2 });
const imageRows = () => cards()[0].querySelectorAll('.mm-generation-rated .mm-rate');
check('each image "Show images" shows has its own row', imageRows().length, 6);
await act('modelManager.rateGeneration', { generation: 2, level: 8, image: 23 });
check('an image rated X there, with NSFW hidden, leaves the card at once',
      [ratings.at(-1).image_id, ratings.at(-1).level, imageRows().length], ['23', '8', 5]);
tick('modelManager.rateGenerations', false);
check('unticked, the rows go', [!!cardRow(), imageRows().length], [false, 0]);

await act('modelManager.selectModel', { index: 1 });
await waitFor('the next model', () => tabs().length === 2 && tabs()[0][1]);
check('the next model opens on its Civitai images again', tabs(),
      [['Civitai images', true], ['Your generations (0)', false]]);

done();
