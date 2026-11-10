// What an image's data says is shown as text, whatever characters it holds
// (S2). The image card's settings, Hires and ADetailer lines (imageTextHtml)
// put the image's own values into markup - Civitai's generation data, or a
// file Sync images read - and escaped only the prompts. Every card, the
// Civitai Images tab's viewer and your generations' cards and viewer draw it.
// The counts and sizes the page formats (formatNumber, formatBytes) passed a
// value that was not a number through as it was.
//
// A marker element in a value shows a fault: drawn as markup it becomes an
// element; escaped, it reads as its characters. Nothing in it runs.
import { ROOT, checker, mountTab } from './harness.mjs';

const { document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, done } = checker();
const { imageTextHtml, imageDetailsHtml } = await import(`file:///${ROOT}/javascript/shared/image_card.mjs`);
const { formatNumber, formatBytes } = await import(`file:///${ROOT}/javascript/shared/core.mjs`);

const MARKER = '<i data-mm-marker></i>';
const markers = (box) => box.querySelectorAll('[data-mm-marker]').length;

function drawn(html) {
    const box = document.createElement('div');
    box.innerHTML = html;
    return box;
}

// ------------------------------------------------- the card's three lines
// Each of the 18 values the lines show, holding the marker.
const FIELDS = ['steps', 'cfgScale', 'seed', 'VAE', 'Clip skip', 'Denoising strength', 'Size',
                'Hires upscaler', 'Hires upscale', 'Hires steps',
                'ADetailer model', 'ADetailer confidence', 'ADetailer dilate erode', 'ADetailer mask blur',
                'ADetailer denoising strength', 'ADetailer inpaint only masked'];
const meta = Object.fromEntries(FIELDS.map((key) => [key, `${key} ${MARKER}`]));
const image = { id: 7, meta, mm_sampler: `sampler ${MARKER}`, mm_scheduler: `scheduler ${MARKER}` };

const lines = drawn(imageTextHtml(image));
check('no value of the settings, Hires or ADetailer lines is drawn as markup', markers(lines), 0);
const text = lines.textContent;
const shown = [...FIELDS.map((key) => `${key} ${MARKER}`), `sampler ${MARKER}`, `scheduler ${MARKER}`]
    .filter((value) => !text.includes(value));
check('and each of the 18 reads as written', shown, []);
check('the lines keep their places',
      ['.mm-image-params', '.mm-image-hires', '.mm-image-adetailer'].map((s) => !!lines.querySelector(s)),
      [true, true, true]);

// The card as a whole: the same lines, and the image's id.
const card = drawn(imageDetailsHtml({ ...image, id: `9 ${MARKER}` }));
check('the card draws no value as markup, its id included', markers(card), 0);
check('an id that is not a number reads Unknown, never null',
      card.querySelector('.mm-image-id span:last-child')?.textContent, 'Unknown');
check('a number id reads as itself',
      drawn(imageDetailsHtml({ id: 12345, meta: {} })).querySelector('.mm-image-id span:last-child')?.textContent,
      '12345');

// Guard: one escape a line, not one a value as well - "R&B 'v2'" shows once,
// never as &amp;.
const plain = drawn(imageTextHtml({ meta: { VAE: `R&B 'v2' "x"`, 'ADetailer model': 'face & hands' } }));
check('a value holding & and quotes reads as written',
      [plain.querySelector('.mm-image-params')?.textContent.includes(`VAE: R&B 'v2' "x"`),
       plain.querySelector('.mm-image-adetailer')?.textContent.includes('Model: face & hands')],
      [true, true]);
check('and is never shown escaped twice', plain.textContent.includes('&amp;'), false);

// ------------------------------------------------- counts and sizes
check('a count that is not a number says 0', formatNumber(`5 ${MARKER}`), '0');
check('counts read as before',
      [formatNumber(0), formatNumber(999), formatNumber('1500'), formatNumber(1500), formatNumber(2000000)],
      ['0', '999', '1.5K', '1.5K', '2.0M']);
check('a size that is not a number says Unknown', formatBytes(`512 ${MARKER}`), 'Unknown');
check('sizes read as before, a number given as text included',
      [formatBytes('512'), formatBytes(2048), formatBytes(0), formatBytes(1073741824 * 2)],
      ['512 B', '2.00 KB', 'Unknown', '2.00 GB']);

done();
