// Versions Civitai allows only for generating on its site, in the Civitai
// Browser (#229): with the setting on, a page of cards asks the server once,
// after the grid is drawn - each card's version and its file's SHA-256 - and
// a card answered so says "On-site only". A panel asks once for the versions
// the page has no answer for; such a version's pill shows ☁, and picked, its
// Download is disabled, saying why. An answer that comes after a newer search
// marks nothing; a failed one marks nothing either. With the setting off,
// nothing is asked. The server's side: version_records_test.py.
import { act, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const ON_SITE = 'The creator allows this version only for generating on Civitai.';
const sha = (n) => n.toString(16).toUpperCase().padStart(64, '0');
const version = (id) => ({ id, name: `v${id}`, images: [], baseModel: 'SDXL 1.0',
                           files: [{ id: id * 10, name: `f${id}.safetensors`, primary: true, sizeKB: 1024,
                                     hashes: { SHA256: sha(id) } }] });
// A page of 20; the first model has three versions, its newest first.
const page = () => Array.from({ length: 20 }, (_, i) => ({
    id: i + 1, name: `M${i + 1}`, type: 'LORA', stats: {}, creator: {},
    modelVersions: i === 0 ? [version(10), version(11), version(12)] : [version((i + 1) * 10)],
}));

let marksOn = true;
let usage = () => ({ success: true, versions: {} });   // the server's answer to an ask
let hold = null;                                       // a promise the next answer waits for
const asks = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) return reply({ success: true, civitai_on_site_marks: marksOn });
    if (href.includes('/civitai/usage')) {
        const pairs = new URL(href, 'http://webui').searchParams.get('versions').split(',');
        asks.push(pairs);
        const answer = usage(pairs);
        if (hold) await hold;
        return reply(answer);
    }
    if (href.includes('/civitai/owned')) return reply({ success: true, models: {}, versions: {} });
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: [] });
    if (href.includes('/model-manager/civitai/models')) {
        return reply({ success: true, nextCursor: null, pageSize: 20, models: page() });
    }
    if (href.includes('/versions/') || href.includes('/images')) {
        return reply({ success: true, images: [], page: { number: 1, size: 20, count: 0, shown: 0, more: false } });
    }
    return reply({ success: true });
};

await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (selector) => document.querySelector(selector);
const badges = () => Array.from(document.querySelectorAll('#cb_grid .cb-onsite-badge'));
const searched = async () => {
    const before = asks.length;
    act('civitaiBrowser.search');
    await waitFor('the page', () => document.querySelectorAll('#cb_grid .model-card').length === 20);
    return before;
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));
const details = () => $('#cb_details');
const pill = (name) => Array.from(details()?.querySelectorAll('.mm-version-pill') || [])
    .find((p) => p.textContent.trim().startsWith(name));
const onSiteButton = () => Array.from(details()?.querySelectorAll('button') || [])
    .find((b) => b.textContent.trim() === 'On-site only');

// ------------------------------------------------------------ a page of cards
usage = () => ({ success: true, versions: { 10: true, 20: false } });
let before = await searched();
await waitFor('the ask', () => asks.length > before);
check('setting on: a search of 20 cards asks once, with each card\'s version and its SHA-256',
      [asks.length - before, asks.at(-1)?.length, asks.at(-1)?.[0], asks.at(-1)?.[1]],
      [1, 20, `10:${sha(10)}`, `20:${sha(20)}`]);
await waitFor('the badge', () => badges().length > 0);
check('the card answered on-site only says so, with why; the others nothing',
      badges().map((b) => [b.closest('.model-card') === document.querySelectorAll('#cb_grid .model-card')[0],
                           b.textContent.trim(), b.title]),
      [[true, 'On-site only', ON_SITE]]);

// ------------------------------------------------------------ the panel
usage = () => ({ success: true, versions: { 11: true, 12: false } });
before = asks.length;
act('civitaiBrowser.openModel', { index: 0 });
await waitFor('the panel\'s ask', () => asks.length > before);
check('opening a card asks once, for the versions the page has no answer for',
      asks.slice(before), [[`11:${sha(11)}`, `12:${sha(12)}`]]);
await waitFor('the pill\'s sign', () => pill('v11')?.textContent.includes('☁'));
check('the on-site-only version\'s pill has ☁, and says why', [pill('v11')?.textContent.trim(),
      pill('v11')?.title.includes(`On-site only: the creator allows`), pill('v12')?.textContent.trim()],
      ['v11 ☁︎', true, 'v12']);
act('civitaiBrowser.selectVersion', { index: 1 });
await settle();
check('picked, its Download reads On-site only, disabled, saying why',
      [onSiteButton()?.disabled, onSiteButton()?.title.startsWith(ON_SITE),
       Boolean(details()?.querySelector('[data-action="civitaiBrowser.download"]'))], [true, true, false]);
act('civitaiBrowser.selectVersion', { index: 2 });
await settle();
check('one that allows downloads offers Download', [Boolean(onSiteButton()),
      Boolean(details().querySelector('[data-action="civitaiBrowser.download"]'))], [false, true]);

// ------------------------------------------------------------ a late answer
let release;
hold = new Promise((resolve) => { release = resolve; });
usage = () => ({ success: true, versions: { 10: true } });
before = await searched();
await waitFor('the first ask', () => asks.length > before);
usage = () => ({ success: true, versions: {} });
await searched();
release();
hold = null;
await settle();
check('an answer that comes after a newer search marks nothing', badges().length, 0);
act('civitaiBrowser.openModel', { index: 0 });
await waitFor('the newer page\'s panel', () => pill('v10'));
await settle();
check('nor the newer page\'s own copy of that version: its pill has no sign',
      pill('v10')?.textContent.includes('\u2601'), false);

// ------------------------------------------------------------ a failure
usage = () => ({ success: false, error: 'Civitai is down' });
before = await searched();
await waitFor('the ask', () => asks.length > before);
await settle();
check('a failed ask marks nothing', badges().length, 0);
act('civitaiBrowser.openModel', { index: 0 });
await waitFor('the panel', () => pill('v11'));
act('civitaiBrowser.selectVersion', { index: 1 });
await settle();
check('and Download is offered as today', [Boolean(onSiteButton()),
      Boolean(details().querySelector('[data-action="civitaiBrowser.download"]'))], [false, true]);

// ------------------------------------------------------------ the setting off
marksOn = false;
await import('./harness.mjs').then(({ sharedModule }) => sharedModule('ui_options.mjs'))
    .then(({ refreshUiOptions }) => refreshUiOptions());
before = asks.length;
await searched();
act('civitaiBrowser.openModel', { index: 0 });
await waitFor('the panel', () => pill('v11'));
await settle();
check('setting off: no ask after a search, nor a panel opened', asks.length - before, 0);

done();
