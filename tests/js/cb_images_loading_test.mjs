// The Civitai Browser while a model's images load (#28): they come from
// Civitai through the server and take seconds, and nothing used to show - the
// last model's images stayed up after a click, and a switch changed looked
// ignored until the new images arrived, or for good if the request failed.
// Now a bar shows at once: over an emptied gallery saying it is loading when
// a model is opened, over the current images - dimmed, their switches off -
// when a switch changes; and a failure is said.
import { ROOT, act, browserGalleryAnswer, call, checker, mountTab, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const image = (id) => ({ id, url: `https://example.invalid/${id}.jpeg`, nsfwLevel: 1, browsingLevel: 1,
    mm_level: 1, mm_level_from_prompt: false, meta: { prompt: 'a lighthouse by the sea' } });
const IMAGES = { 70: [image(1), image(2)], 80: [image(3)] };
// What a gallery waits on, as a server asked for a stream sends it (#132):
// its status lines, then - once the gate opens - its answer.
const streamed = (lines, gate) => new Response(new ReadableStream({
    async start(controller) {
        const encoder = new TextEncoder();
        for (const line of lines) {
            if (line === 'GATE') await gate;
            else controller.enqueue(encoder.encode(JSON.stringify(line) + '\n'));
        }
        controller.close();
    },
}), { headers: { 'content-type': 'application/x-ndjson' } });
const OVERLOADED = { type: 'status', text: 'Civitai: overloaded. Trying again (1 of 3)', wait: 3 };
let streamNext = null;     // a gate: the next answer comes as a stream, held there
const accepts = [];
let release = null;        // the images request, held back while a test looks
let failNext = false;
let moreNext = false;      // the next answer says Civitai has more
globalThis.fetch = async (url, init) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    const version = href.match(/versions\/(\d+)\/images/);
    if (version && streamNext) {
        const gate = streamNext;
        streamNext = null;
        accepts.push(init?.headers?.Accept);
        const more = moreNext;
        moreNext = false;
        return streamed([OVERLOADED, 'GATE', { type: 'result',
            result: browserGalleryAnswer(href, IMAGES[version[1]], {}, { more, size: 2 }) }], gate);
    }
    if (version) {
        await new Promise((resolve) => { release = resolve; });
        release = null;
        if (failNext) {
            failNext = false;
            return reply({ success: false, error: 'Civitai: temporarily overloaded (503)' });
        }
        return reply(browserGalleryAnswer(href, IMAGES[version[1]], {}, { more: false, size: 100 }));
    }
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, gallery_hide_nsfw: false, hide_promptless_images: false });
    }
    if (href.includes('/model-manager/civitai/models')) {
        return reply({ success: true, nextCursor: null, pageSize: 20, models: [
            { id: 7, name: 'Model 7', type: 'LORA', stats: {}, creator: {}, modelVersions: [{ id: 70, files: [] }] },
            { id: 8, name: 'Model 8', type: 'LORA', stats: {}, creator: {}, modelVersions: [{ id: 80, files: [] }] }] });
    }
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const gallery = () => $('cb_images');
const bar = () => gallery()?.querySelector(':scope > .mm-loading-bar');
const cards = () => Array.from(gallery()?.querySelectorAll('.mm-image-card') || []);
const switches = () => Array.from(gallery()?.querySelectorAll('input[type="checkbox"]') || []);
const held = () => waitFor('the images request', () => release !== null);

$('cb_status').textContent = '';
act('civitaiBrowser.search');
await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));

// ------------------------------------------------------- opening a model
const opening = act('civitaiBrowser.openModel', { index: 0 });
check('opening a model shows the bar at once, over a gallery saying it is loading',
      [!!bar(), gallery()?.querySelector('.mm-images-loading')?.textContent, cards().length],
      [true, 'Loading images...', 0]);
await held();
release();
await opening;
await waitFor('the images', () => cards().length === 2);
check('and the bar goes when the images are drawn', [!!bar(), gallery().classList.contains('mm-gallery-loading')],
      [false, false]);

// ------------------------------------------------------ changing a switch
const toggling = tick('civitaiBrowser.showAllImages', false);
await held();
check('changing a switch keeps the images, dimmed under the bar, the switches off until the answer',
      [!!bar(), gallery().classList.contains('mm-gallery-loading'), cards().length,
       switches().length > 0 && switches().every((box) => box.disabled)],
      [true, true, 2, true]);
release();
await toggling;
check('then the new images, undimmed, the switches on again',
      [!!bar(), gallery().classList.contains('mm-gallery-loading'), switches().some((box) => box.disabled)],
      [false, false, false]);

// ---------------------------------------------------------- a failure said
failNext = true;
// The switch is not drawn now - nothing hidden for it to show - so its action is called.
const failing = call('civitaiBrowser.showAllImages', {}, { checked: true });
await held();
release();
await failing;
check('a request that fails says so, and gives the images back as they were',
      [gallery().querySelector('.mm-images-error')?.textContent.includes('temporarily overloaded'),
       gallery().classList.contains('mm-gallery-loading'), !!bar(), cards().length,
       switches().some((box) => box.disabled)],
      [true, false, false, 2, false]);

// ------------------------------------------------- another model, at once
const another = act('civitaiBrowser.openModel', { index: 1 });
check('opening another model clears the last one\'s images at once', [cards().length, !!bar()], [0, true]);
await held();
release();
await another;
await waitFor('its images', () => cards().length === 1);

// ---------------------------------------------- what it waits on (#132)
const line = () => gallery().querySelector(':scope > .mm-images-loading')?.textContent;
let open;
streamNext = new Promise((resolve) => { open = resolve; });
moreNext = true;
const opened = act('civitaiBrowser.openModel', { index: 0 });
await waitFor('what it waits on', () => line()?.includes('overloaded'));
check('opening a model whose images wait on Civitai says why, in its words, counting down',
      line(), 'Civitai: overloaded. Trying again (1 of 3) · 3 s');
check('having asked for a stream', accepts.at(-1), 'application/x-ndjson');
open();
await opened;
await waitFor('the images', () => cards().length === 2);

const status = () => gallery().querySelector('.mm-images-footer .mm-images-status')?.textContent;
streamNext = new Promise((resolve) => { open = resolve; });
const more = act('civitaiBrowser.loadMoreImages');
await waitFor('what Load More waits on', () => status()?.includes('overloaded'));
check('Load More says what it waits on under its button',
      [status(), gallery().querySelector('.mm-images-footer button')?.textContent.trim()],
      ['Civitai: overloaded. Trying again (1 of 3) · 3 s', 'Loading...']);
open();
await more;
check('and the line goes with the page, the button back',
      [status() === undefined, gallery().querySelector('.mm-images-footer button')?.textContent.trim() ?? 'no more'],
      [true, 'no more']);

done();
