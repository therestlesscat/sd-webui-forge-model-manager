// The Model Manager's gallery while it loads (#28), as the Civitai Browser's
// (cb_images_loading_test.mjs): a bar at once - over an emptied gallery when
// a model is opened, over the current images, dimmed with their switches off,
// when a switch changes - and a first page that fails is said in the gallery,
// where it was the console's alone.
import { ROOT, act, call, checker, mountTab, startTab, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model', version_name: 'v1',
    base_model: 'SDXL 1.0', model_type: 'LORA', file_path: 'C:/m/a.safetensors', file_name: 'a.safetensors',
    file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1, trained_words: [], tags: [],
};
const image = (id) => ({ id, url: `https://example.invalid/${id}.jpeg`, mm_level: 1, meta: { prompt: 'a lighthouse' } });
const STATE = { version_id: 5001, total_count: 2, filtered_count: 2, hide_nsfw_images: false,
                hide_promptless_images: false };
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
const syncs = [];          // the model's Sync, as posted
const estimates = [];      // what was asked of the estimate
let release = null;
let failNext = false;
let syncAnswer = { success: true, synced_count: 1, total_versions: 1 };
globalThis.fetch = async (url, init) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/models/force-sync')) {
        syncs.push(new URLSearchParams(String(init?.body || '')));
        return reply(syncAnswer);
    }
    if (href.includes('/sync/estimate')) {
        estimates.push(new URL(href).searchParams);
        // This model's gallery, refetched either way (#103).
        return reply({ success: true, estimate: { versions: 1, image_options: {
            page: 100, first: { requests: 1, prompts: 4, images: 100 },
            kept: { requests: 4, prompts: 12, images: 350 }, deletes: { images: 250, versions: 1 } } } });
    }
    if (streamNext && href.includes('/images/gallery-page')) {
        const gate = streamNext;
        streamNext = null;
        accepts.push(init?.headers?.Accept);
        const answer = { success: true, images: [image(1), image(2)], images_state: STATE,
                         page: { number: 1, count: 2, shown: 2, more: false } };
        return streamed([OVERLOADED, 'GATE', { type: 'result', result: answer }], gate);
    }
    if (href.includes('/images/gallery-page')) {
        await new Promise((resolve) => { release = resolve; });
        release = null;
        if (failNext) {
            failNext = false;
            return reply({ success: false, error: 'Civitai: temporarily overloaded (503)' });
        }
        return reply({ success: true, images: [image(1), image(2)], images_state: STATE,
                       page: { number: 1, count: 2, shown: 2, more: false } });
    }
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...MODEL, generations_count: 0, images_state: STATE } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MODEL] });
    }
    return reply({ success: true });
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const gallery = () => $('mm_images');
const bar = () => gallery()?.querySelector(':scope > .mm-loading-bar');
const cards = () => Array.from(gallery()?.querySelectorAll('.mm-image-card') || []);
const switches = () => Array.from(gallery()?.querySelectorAll('input[type="checkbox"]') || []);
const held = () => waitFor('the gallery page', () => release !== null);

$('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelector('#mm_grid .model-card'));

const opening = act('modelManager.selectModel', { index: 0 });
check('opening a model shows the bar at once, over a gallery saying it is loading',
      [!!bar(), gallery()?.querySelector('.mm-images-loading')?.textContent, gallery()?.style.display],
      [true, 'Loading images...', 'block']);
await held();
release();
await opening;
await waitFor('the images', () => cards().length === 2);
check('and it goes when the images are drawn', [!!bar(), gallery().classList.contains('mm-gallery-loading')],
      [false, false]);

const toggling = tick('modelManager.showNsfwImages', false);
await held();
check('changing a switch keeps the images, dimmed under the bar, the switches off',
      [!!bar(), gallery().classList.contains('mm-gallery-loading'), cards().length,
       switches().length > 0 && switches().every((box) => box.disabled)],
      [true, true, 2, true]);
release();
await toggling;
check('then the new page, undimmed, the switches on again',
      [!!bar(), gallery().classList.contains('mm-gallery-loading'), switches().some((box) => box.disabled)],
      [false, false, false]);

failNext = true;
// The switch is not drawn now - nothing hidden for it to show - so its action is called.
const failing = call('modelManager.showNsfwImages', {}, { checked: true });
await held();
release();
await failing;
check('a first page that fails is said in the gallery, which is undimmed again',
      [gallery().querySelector('.mm-images-error')?.textContent.includes('temporarily overloaded'),
       gallery().classList.contains('mm-gallery-loading'), !!bar()],
      [true, false, false]);

// ---------------------------------------------- what it waits on (#132)
// Civitai overloaded: the page used to say nothing but wait. Now the gallery
// says what it waits on, in Civitai's words, and counts the seconds down.
const line = () => gallery().querySelector(':scope > .mm-images-loading')?.textContent;
let open;
streamNext = new Promise((resolve) => { open = resolve; });
const waiting = call('modelManager.showNsfwImages', {}, { checked: false });
await waitFor('what it waits on', () => line()?.includes('overloaded'));
check('a switch\'s page that waits on Civitai says why over the dimmed images, counting down',
      [line(), gallery().classList.contains('mm-gallery-loading')],
      ['Civitai: overloaded. Trying again (1 of 3) · 3 s', true]);
check('having asked for a stream', accepts.at(-1), 'application/x-ndjson');
open();
await waiting;
await waitFor('the images', () => cards().length === 2);
check('then its images, and the line is gone', line() === undefined, true);

// The model's Sync asks first how many images come back (#103): as many as
// each version has, by default, or the first page - which deletes the rest,
// and says so, and that they can still be seen. Either may bring other
// images. (Resync Images, which asked it of one version, is gone.)
const question = () => document.querySelector('.mm-image-count-dialog');
const choice = (value) => question()?.querySelector(`input[value="${value}"]`);
const said = () => question()?.querySelector('.mm-dialog-notice')?.textContent || '';
check('no Resync Images button any more', !!document.querySelector('[data-action="modelManager.resyncImages"]'), false);
let asking = act('modelManager.syncModel');
await waitFor('the question', () => !!question());
check('Sync asks how many images come back, each way costed, as many as each has chosen',
      [choice('kept')?.checked, Array.from(question().querySelectorAll('.mm-dialog-cost')).map((c) => c.textContent),
       question().querySelector('[data-confirm]')?.textContent.trim()],
      [true, ['~16 req', '~5 req'], 'Sync']);
check('over the model\'s files', estimates.at(-1)?.get('paths'), 'C:/m/a.safetensors');
check('saying the images may not be these, and deleting nothing',
      [said().includes('won\'t necessarily be the ones you have now'), said().includes('deletes')], [true, false]);
choice('first').checked = true;
choice('first').dispatchEvent(new window.Event('change', { bubbles: true }));
check('the first page says how many of the model\'s stored images go, and that they can still be seen',
      [said().includes('This deletes 250 of this model\'s stored images'),
       said().includes('Load More fetches them from Civitai again')], [true, true]);
question().querySelector('[data-close]').dispatchEvent(new window.Event('click', { bubbles: true }));
await asking;
check('Cancel syncs nothing', [!!question(), syncs.length], [false, 0]);

const syncing = act('modelManager.syncModel');
await waitFor('the question', () => !!question());
question().querySelector('[data-confirm]').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the sync', () => syncs.length === 1);
check('Sync syncs the model, as many images as each has',
      [syncs[0].get('model_id'), syncs[0].get('keep_image_count')], ['4001', 'true']);
await waitFor('the page after it', () => release !== null);
release();
await syncing;
const statusLine = () => document.getElementById('mm_status')?.textContent.trim();
check('and says how many of its files it synced', statusLine(), 'Synced 1 of 1 files from Civitai');

// One of two failing is said, with which and why: it said "Synced 1/2 files
// successfully" (#208).
syncAnswer = { success: true, synced_count: 1, total_versions: 2,
               errors: ['b.safetensors: Civitai could not be asked: Server error: 503'] };
release = null;
const again = act('modelManager.syncModel');
await waitFor('the question', () => !!question());
question().querySelector('[data-confirm]').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the second sync', () => syncs.length === 2);
await waitFor('the page after it', () => release !== null);
release();
await again;
check('one of two failed: it says so, which, and why', statusLine(),
      'Synced 1 of 2 files from Civitai; 1 failed: b.safetensors: Civitai could not be asked: Server error: 503');

done();
