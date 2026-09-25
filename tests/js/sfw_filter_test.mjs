// "Only Show Models with SFW images", from the browser's side, and the box it sits beside.
//
// "Include NSFW models" asks Civitai; "Only Show Models with SFW images" checks each
// model's first images here. The second means nothing while NSFW models are
// included, so it is greyed out then, keeps its tick for later, and is not
// sent as on. When it is on, the search streams - it checks models one at a time -
// and the status line says what it left out, and when Civitai's rate limit
// cut a page short.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const asked = [];
let summary = null;
let progress = null;
globalThis.fetch = async (url) => {
    const href = String(url);
    if (!href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true }) };
    }
    asked.push(new URL(href, 'http://webui'));
    if (!href.includes('/stream')) {
        return { ok: true, json: async () => ({ success: true, models: [], nextCursor: null,
            pageSize: 20, filterStats: null }) };
    }
    const lines = [{ type: 'meta', pageSize: 20 }, ...(progress ? [progress] : []),
                   { type: 'done', nextCursor: null, filterStats: summary }];
    const queue = lines.map((l) => new TextEncoder().encode(JSON.stringify(l) + '\n'));
    return { ok: true, body: { getReader: () => ({
        read: async () => (queue.length ? { done: false, value: queue.shift() } : { done: true }),
        cancel: async () => {},
    }) } };
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const status = () => $('cb_status').textContent;
const labelText = (id) => $(id).closest('label').textContent.replace(/\s+/g, ' ').trim();
const toggle = (id, on) => { $(id).checked = on; $(id).dispatchEvent(new window.Event('change')); };

async function search() {
    asked.length = 0;
    $('cb_status').textContent = '';
    window.cbSearch();
    await waitFor('the search to finish', () => status().startsWith('Showing'));
}

// ----------------------------------------------------------------- the boxes
check('Include NSFW says it is about models', labelText('cb_nsfw'), 'Include NSFW models');
check('the new box is beside it', labelText('cb_sfw_only'), 'Only Show Models with SFW images');
// Split by who acts on them: Civitai, in the search, or this extension,
// checking what the search returned.
const caption = (id) => $(id).closest('.filter-group').querySelector(':scope > label').textContent;
check('Include NSFW models is an API option',
      caption('cb_nsfw'), 'API Options');
check('the two checked here are post-processing options',
      [caption('cb_sfw_only'), caption('cb_require_prompt')],
      ['Post-processing Options', 'Post-processing Options']);
check('in two groups, not one',
      $('cb_nsfw').closest('.filter-group') !== $('cb_sfw_only').closest('.filter-group'), true);
check('each taking a smaller share of the row than a full group: half, and three quarters',
      [$('cb_nsfw').closest('.filter-group').classList.contains('filter-grow-half'),
       $('cb_sfw_only').closest('.filter-group').classList.contains('filter-grow-three-quarters')],
      [true, true]);
const nsfwTip = $('cb_nsfw').closest('label').title;
const sfwTip = $('cb_sfw_only_label').title;
check('Include NSFW models explains that Civitai decides, and what it still lets through',
      [nsfwTip.includes('Civitai'), nsfwTip.includes('most of the models it still lists')],
      [true, true]);
check('Only Show Models with SFW images explains what it checks and what it costs',
      [sfwTip.includes('first 20'), sfwTip.includes('above PG-13'),
       sfwTip.includes('models with no images'),
       sfwTip.includes('one request per model'), sfwTip.includes('comes back short')],
      [true, true, true, true, true]);

// ------------------------------------------- the banner while it is on
// Its pages come back short, which without a word reads as something broken.
const banner = () => $('cb_sfw_only_banner');
const bannerShown = () => banner().style.display !== 'none';
check('with it unticked there is no banner', bannerShown(), false);
toggle('cb_sfw_only', true);
check('ticking it puts up a banner', bannerShown(), true);
check('above the status line, where the short page is reported',
      banner().nextElementSibling === $('cb_status'), true);
check('saying what the tooltip says, word for word',
      $('cb_sfw_only_banner_text').textContent, sfwTip);
const settingNote = $('cb_sfw_only_banner_setting')?.textContent.replace(/\s+/g, ' ') || '';
check('and where to find the setting that fills every page, and that it is not recommended',
      [settingNote.includes("Fill every page with 'Only Show Models with SFW images'"),
       settingNote.includes('Settings → Model Manager'), settingNote.includes('not recommended')],
      [true, true, true]);
toggle('cb_sfw_only', false);
check('unticking it takes the banner down', bannerShown(), false);

// ------------------------------------------------------- greyed out, and why
check('with NSFW models excluded it can be used', $('cb_sfw_only').disabled, false);
toggle('cb_sfw_only', true);
toggle('cb_nsfw', true);
check('including NSFW models greys it out',
      [$('cb_sfw_only').disabled, $('cb_sfw_only_label').classList.contains('cb-filter-disabled')],
      [true, true]);
check('saying why, ahead of what it does',
      $('cb_sfw_only_label').title.startsWith('Only applies while Include NSFW models is unticked. '),
      true);
check('it keeps its tick for when it applies again', $('cb_sfw_only').checked, true);
check('but while greyed out it is not in force, so there is no banner', bannerShown(), false);

await search();
check('while greyed out it is sent as off, and the search does not stream',
      [asked[0]?.pathname, asked[0]?.searchParams.get('sfw_only')],
      ['/model-manager/civitai/models', 'false']);

toggle('cb_nsfw', false);
check('unticking NSFW models brings it back as it was',
      [$('cb_sfw_only').disabled, $('cb_sfw_only_label').title], [false, sfwTip]);
check('banner and all', bannerShown(), true);

// --------------------------------------------------------------- searching
progress = { type: 'progress', checked: 8, dropped: 0, unsafe: 6, failed: 1, rejected: 0, found: 1 };
summary = { checked: 30, dropped: 0, unsafe: 24, failed: 0, rejected: 0,
            promptFilter: false, sfwFilter: true, sizeFilter: false,
            budgetReached: true, rateLimited: false };
asked.length = 0;
$('cb_status').textContent = '';
window.cbSearch();
await waitFor('the stream', () => asked.length === 1);
check('with it on, the search streams and says so',
      [asked[0].pathname, asked[0].searchParams.get('sfw_only'),
       asked[0].searchParams.get('require_prompt')],
      ['/model-manager/civitai/models/stream', 'true', 'false']);
await waitFor('the summary', () => status().startsWith('Showing'));
check('the summary says how many had NSFW images', status(),
      'Showing 0 models (page 1) - checked 30, skipped 24 with NSFW images. '
      + 'Stopped early to avoid a long wait; press Next to keep looking.');

summary = { ...summary, rateLimited: true };
await search();
check('when Civitai cut the page short, it says that instead', status(),
      'Showing 0 models (page 1) - checked 30, skipped 24 with NSFW images. '
      + 'Civitai is limiting requests, so this page stopped early; wait a moment, then press Next.');

// ------------------------------------------------ jumping from the Model Manager
toggle('cb_nsfw', false);
await window.cbShowModel('model:12345');
check('a jump from the Model Manager includes NSFW models, and greys the box out with it',
      [$('cb_nsfw').checked, $('cb_sfw_only').disabled, bannerShown()], [true, true, false]);

done();
