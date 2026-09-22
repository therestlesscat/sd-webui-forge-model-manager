// renderThumbs, plus the browser image list's NSFW filtering and toggle.
const fs = require('fs');
const vm = require('vm');
const { execSync } = require('child_process');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');
const common = fs.readFileSync(REPO + '/javascript/shared/common.mjs', 'utf8');
const browser = fs.readFileSync(REPO + '/javascript/civitai_browser.mjs', 'utf8');
const manager = fs.readFileSync(REPO + '/javascript/model_manager.mjs', 'utf8');

const sandbox = {
    console: { log() {}, warn() {} },
    Number, Math, String,
    document: {
        createElement: () => {
            const el = { _t: '' };
            Object.defineProperty(el, 'textContent', { set(v) { el._t = String(v); }, get: () => el._t });
            Object.defineProperty(el, 'innerHTML', {
                get: () => el._t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
            });
            return el;
        },
    },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(common.replace(/^export /gm, ''), sandbox);
const { renderThumbs, formatNumber } = sandbox;

let failures = 0;
const check = (label, cond, extra) => {
    if (!cond) { failures++; console.log('FAIL ' + label + (extra ? '\n  ' + extra : '')); }
};

// ------------------------------------------------------------- renderThumbs
check('no votes renders nothing', renderThumbs(0, 0) === '');
check('undefined renders nothing', renderThumbs(undefined, undefined) === '');
check('null renders nothing', renderThumbs(null, null) === '');

const both = renderThumbs(52870, 96);
check('shows the up count', both.includes('52.9K'), both);
check('shows the down count', both.includes('96'), both);
check('carries a percentage', /100% positive|99% positive/.test(both), both);
check('has both classes', both.includes('mm-thumbs-up') && both.includes('mm-thumbs-down'));

check('zero downs still renders once there are ups',
      renderThumbs(10, 0).includes('▼ 0'), renderThumbs(10, 0));
check('zero ups still renders once there are downs',
      renderThumbs(0, 5).includes('▲ 0'), renderThumbs(0, 5));
check('all-negative is 0%', renderThumbs(0, 5).includes('0% positive'), renderThumbs(0, 5));
check('half and half is 50%', renderThumbs(50, 50).includes('50% positive'));
check('string inputs coerce', renderThumbs('10', '2').includes('▲ 10'));
check('title is escaped', !renderThumbs(1, 0).includes('<script'));

// Against the live payload the browser card actually receives.
const items = JSON.parse(execSync(
    'curl -s --max-time 40 "https://civitai.com/api/v1/models?limit=20&types=Checkpoint&sort=Most%20Downloaded"',
    { encoding: 'buffer', maxBuffer: 32 * 1024 * 1024 }).toString('utf8')).items;
let rendered = 0;
for (const m of items) {
    const html = renderThumbs(m.stats?.thumbsUpCount, m.stats?.thumbsDownCount);
    if (html) rendered++;
    check('no NaN for ' + m.id, !html.includes('NaN'), html);
}
check('live payload renders thumbs for every model', rendered === items.length,
      rendered + ' of ' + items.length);
check('stats.rating really is gone', items.every(m => m.stats?.rating === undefined));

// ------------------------------------- browser image list: filter and toggle
function lift(src, name, ctx) {
    const m = src.match(new RegExp('^[ \\t]*(async )?function ' + name + '\\s*\\(', 'm'));
    if (!m) throw new Error('not found: ' + name);
    const isAsync = !!m[1];
    let i = src.indexOf('(', m.index + m[0].length - 1), depth = 0;
    for (;; i++) { if (src[i] === '(') depth++; else if (src[i] === ')' && --depth === 0) break; }
    i = src.indexOf('{', i);
    const start = i; depth = 0;
    for (;; i++) { if (src[i] === '{') depth++; else if (src[i] === '}' && --depth === 0) break; }
    return vm.runInContext('(' + (isAsync ? 'async ' : '') + 'function'
        + src.slice(src.indexOf('(', m.index), start) + src.slice(start, i + 1) + ')', ctx);
}

const bctx = { console: sandbox.console, Number, Math, String };
bctx.window = bctx;
vm.createContext(bctx);
const isImageSafe = sandbox.isImageSafe;

// Paired the way Civitai actually pairs them, measured over 67,458 images:
//   None->1   Soft->2   Mature->4   X->16 or 8
const IMAGES = [
    { id: 1, browsingLevel: 1, nsfwLevel: 'None', nsfw: false },
    { id: 2, browsingLevel: 2, nsfwLevel: 'Soft', nsfw: true },
    { id: 3, browsingLevel: 4, nsfwLevel: 'Mature', nsfw: true },
    { id: 4, browsingLevel: 16, nsfwLevel: 'X', nsfw: true },
    { id: 5, browsingLevel: 1 },              // integer alone is enough
    { id: 6, nsfwLevel: 'Soft' },             // string alone, no integer
    { id: 7 },                                // nothing to go on
];
const safe = IMAGES.filter(isImageSafe);
check('SFW view keeps PG and PG-13', safe.map(i => i.id).join() === '1,2,5,6',
      JSON.stringify(safe.map(i => i.id)));
check('hides R and XXX', !safe.some(i => i.id === 3 || i.id === 4));
check('an image with nothing to go on is not assumed safe', !safe.some(i => i.id === 7));
check('browsingLevel alone is enough to classify', safe.some(i => i.id === 5));
check('a Soft image is PG-13, not R', sandbox.nsfwImageLevel({ nsfwLevel: 'Soft' }) === 2);
check('a Mature image is R, not X', sandbox.nsfwImageLevel({ nsfwLevel: 'Mature' }) === 4);
check('the integer outranks the string',
      sandbox.nsfwImageLevel({ browsingLevel: 16, nsfwLevel: 'None' }) === 16);

// The filter must now key off the toggle alone, not the search checkbox.
const renderSrc = browser.slice(browser.indexOf('function renderImages'),
                                browser.indexOf('function renderImages') + 6000);
check('filter no longer consults cb_nsfw', !/!nsfwEnabled && !showAllNsfwImages/.test(renderSrc));
check('filter keys off the toggle', /if \(!showAllNsfwImages\)/.test(renderSrc), 'condition not found');
check('toggle markup is unconditional', /const nsfwToggleHtml = `/.test(renderSrc));
check('toggle is in the header',
      /\$\{nsfwToggleHtml\}/.test(browser.slice(browser.indexOf('mm-images-header'),
                                                browser.indexOf('mm-images-header') + 900)));
check('toggle keeps its element id', /id="cb_show_all_images"/.test(renderSrc));
check('toggle still calls the handler', /window\.cbToggleShowAllImages/.test(renderSrc));

// Opening a model seeds the toggle from the search box.
const openSrc = browser.slice(browser.indexOf('function openModel'),
                              browser.indexOf('function openModel') + 700);
check('openModel seeds from cb_nsfw',
      /showAllNsfwImages = document\.getElementById\('cb_nsfw'\)\?\.checked/.test(openSrc), openSrc);

// ------------------------------------------------------ cards use the helper
check('browser card calls renderThumbs',
      /renderThumbs\(model\.stats\?\.thumbsUpCount, model\.stats\?\.thumbsDownCount\)/.test(browser));
check('browser card dropped the dead rating var', !/const rating = \(model\.stats\?\.rating/.test(browser));
check('manager card calls renderThumbs',
      /renderThumbs\(model\.thumbs_up, model\.thumbs_down\)/.test(manager));
// Only the CARD changed; the details panel keeps its derived Rating row.
const mgrCard = manager.slice(manager.indexOf('function renderModelCard'),
                              manager.indexOf('function renderModelGrid'));
check('manager card dropped the derived star', !/model\.rating\.toFixed/.test(mgrCard));
check('manager details still has its Rating row', /<td>Rating<\/td>/.test(manager));
for (const [name, src] of [['browser', browser], ['manager', manager]]) {
    check(name + ' imports renderThumbs from the shared module',
          /^\s*renderThumbs,$/m.test(src.slice(0, src.indexOf('} = window.MMCommon;'))));
}

console.log(failures === 0 ? 'All checks passed.' : failures + ' check(s) failed.');
process.exit(failures ? 1 : 0);
