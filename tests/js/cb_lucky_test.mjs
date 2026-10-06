// "I'm feeling lucky" in the Civitai Browser (#102).
//
// Ticked, Search becomes Draw: a page of models drawn at random from those
// Civitai's own filters allow. What a draw cannot use - the text, the sort,
// the checks made here - is greyed out and not sent, and keeps what it holds
// for when the box is unticked. A draw is one page: no page strip.
import { ROOT, act, checker, mountTab, startTab, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const asked = [];
let drawn = null;           // what the next draw answers
let gate = null;            // held, the draw waits after its progress line
globalThis.fetch = async (url, options = {}) => {
    const href = String(url);
    if (!href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true }) };
    }
    asked.push({ url: new URL(href, 'http://webui'), signal: options.signal });
    const stream = (lines) => {
        const queue = lines.map((l) => new TextEncoder().encode(JSON.stringify(l) + '\n'));
        return { ok: true, body: { getReader: () => ({
            read: async () => {
                if (queue.length === 1 && gate) await gate.promise;
                if (options.signal?.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' });
                return queue.length ? { done: false, value: queue.shift() } : { done: true };
            },
            cancel: async () => {},
        }) } };
    };
    if (href.includes('/random')) {
        return stream([{ type: 'meta', pageSize: 20 },
                       { type: 'progress', asked: 3500, found: 7, requests: 2, listing: 0 },
                       { type: 'done', models: drawn.models, draw: drawn.draw }]);
    }
    if (href.includes('/stream')) {
        return stream([{ type: 'meta', pageSize: 20 }, { type: 'done', nextCursor: null, filterStats: {} }]);
    }
    return { ok: true, json: async () => ({ success: true, models: [], nextCursor: 'next', pageSize: 20 }) };
};

await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const status = () => $('cb_status').textContent;
const change = (id, on) => { $(id).checked = on; $(id).dispatchEvent(new window.Event('change', { bubbles: true })); };
const model = (n) => ({ id: n, name: `M${n}`, type: 'LORA', stats: {}, creator: {},
                        modelVersions: [{ id: n * 10, images: [], files: [] }] });
const cards = () => document.querySelectorAll('#cb_grid .model-card').length;
const pageStrip = () => document.querySelectorAll('#cb_grid .mm-page-num').length;

// ------------------------------------------------------------------ the box
const row = $('cb_save_search_btn').parentElement;
check('the box sits in the buttons row, before Save Search',
      Array.from(row.children).map((c) => c.id), ['cb_lucky_label', 'cb_save_search_btn', 'cb_search_btn']);
check('saying what it is', $('cb_lucky_label').textContent.replace(/\s+/g, ' ').trim(), "I'm feeling lucky");
check('unticked at first, Search a search', [$('cb_lucky').checked, $('cb_search_btn').textContent], [false, 'Search']);

// Set up a search a draw has to leave alone.
$('cb_search').value = 'cats';
$('cb_sort').value = 'Newest';
$('cb_min_size').value = '2';
$('cb_type').value = 'LORA';
$('cb_type').dispatchEvent(new window.Event('change', { bubbles: true }));
$('cb_base_model').value = 'Pony';
$('cb_period').value = 'Week';
change('cb_require_prompt', true);
change('cb_sfw_only', true);
check('the SFW banner shows while its box is in force', $('cb_sfw_only_banner').style.display, 'flex');

// ------------------------------------------------------------ ticked
tick('civitaiBrowser.feelingLucky', true);
check('Search becomes Draw', $('cb_search_btn').textContent, 'Draw');
const setAside = ['cb_search', 'cb_sort', 'cb_min_size', 'cb_max_size', 'cb_require_prompt', 'cb_sfw_only'];
check('what a draw cannot use is disabled', setAside.map((id) => $(id).disabled), setAside.map(() => true));
const greyed = (el) => el.classList.contains('filter-disabled');
check('and greyed out: the text, the sort, the size, both post-processing options',
      [greyed($('cb_search').closest('.filter-group')), greyed($('cb_sort').closest('.filter-group')),
       greyed($('cb_min_size').closest('.filter-group')), greyed($('cb_require_prompt').closest('label')),
       greyed($('cb_sfw_only_label'))], [true, true, true, true, true]);
check('saying why', $('cb_sort').closest('.filter-group').title.startsWith("Not used while I'm feeling lucky"), true);
check('keeping what they hold', [$('cb_search').value, $('cb_require_prompt').checked, $('cb_min_size').value],
      ['cats', true, '2']);
const used = ['cb_type', 'cb_base_model', 'cb_nsfw', 'cb_period', 'cb_tag_input'];
check('what Civitai filters on itself stays usable', used.map((id) => $(id).disabled), used.map(() => false));
check('Period, beside Sort, is not greyed with it', greyed($('cb_period').closest('.filter-group')), false);
check('the SFW banner goes: nothing it describes is in force', $('cb_sfw_only_banner').style.display, 'none');

// ------------------------------------------------------------- a draw
drawn = { models: [model(1), model(2)],
          draw: { asked: 250, requests: 2, listed: false, matches: 600000, rate_limited: false, stopped: false } };
let release;
gate = { promise: new Promise((resolve) => { release = resolve; }) };
asked.length = 0;
act('civitaiBrowser.search');
await waitFor('the draw to report progress', () => status().includes('3,500 ids'));
check('the status line follows the draw', status(),
      'Drawing models at random: asked Civitai about 3,500 ids, found 7 of 20...');
check('the grid says what it waits on', $('cb_grid').textContent.includes('Drawing models at random'), true);
gate = null;
release();
await waitFor('the draw to finish', () => status().startsWith('Drew'));
const sent = asked[0].url;
check('Draw asks for a draw', sent.pathname, '/model-manager/civitai/models/random');
check('with Civitai\'s own filters', [sent.searchParams.get('types'), sent.searchParams.get('base_models'),
                                      sent.searchParams.get('period')], ['LORA', 'Pony', 'Week']);
check('and nothing a draw cannot use',
      ['query', 'sort', 'require_prompt', 'sfw_only', 'min_size_gb', 'cursor'].filter((k) => sent.searchParams.has(k)), []);
check('the models drawn fill the grid', cards(), 2);
check('with no page strip: a draw is one page', pageStrip(), 0);
check('the status line says what it cost', status(),
      'Drew 2 models at random from about 600,000 that match - 250 ids asked in 2 requests');

async function drawWith(draw, models = []) {
    drawn = { models, draw: { asked: 0, requests: 1, listed: false, matches: null, rate_limited: false,
                              stopped: false, ...draw } };
    $('cb_status').textContent = '';
    act('civitaiBrowser.search');
    await waitFor('the draw', () => status() && !status().startsWith('Drawing'));
    return status();
}
check('a small set, drawn from all of it',
      await drawWith({ listed: true, matches: 150 }, [model(3)]), 'Drew 1 models at random from all 150 these filters match');
check('fewer than a page: all of them',
      await drawWith({ listed: true, matches: 2 }, [model(3), model(4)]), 'All 2 models these filters match, in random order');
check('none', await drawWith({ listed: true, matches: 0 }), 'No models match these filters.');
check('Civitai limiting requests says to wait, and press Draw again',
      (await drawWith({ asked: 3500, requests: 3, rate_limited: true }, [model(5)])).endsWith(
          'Civitai is limiting requests, so the draw stopped early; wait a moment, then press Draw again.'), true);

// ---------------------------------------------- a search supersedes a draw
gate = { promise: new Promise((resolve) => { release = resolve; }) };
asked.length = 0;
act('civitaiBrowser.search');
await waitFor('the draw to start', () => status().includes('3,500 ids'));
const pending = asked[0].signal;

// ------------------------------------------------------------ unticked
tick('civitaiBrowser.feelingLucky', false);
check('Draw is Search again', $('cb_search_btn').textContent, 'Search');
check('the text, the sort and the size come back',
      ['cb_search', 'cb_sort', 'cb_min_size', 'cb_max_size', 'cb_require_prompt'].map((id) => $(id).disabled),
      [false, false, false, false, false]);
check('with their tooltips as they were', $('cb_search').closest('.filter-group').title, '');
check('SFW images follows Include NSFW models again: usable while it is unticked', $('cb_sfw_only').disabled, false);
change('cb_nsfw', true);
check('and greyed while it is ticked', $('cb_sfw_only').disabled, true);
change('cb_nsfw', false);

act('civitaiBrowser.search');
gate = null;
release();
await waitFor('the search', () => status().startsWith('Showing'));
check('the draw still coming was called off', pending.aborted, true);
check('Search is a search again, with the text it kept',
      [asked[1].url.pathname.includes('/random'), asked[1].url.searchParams.get('query')], [false, 'cats']);

done();
