// Civitai's images load at most so many at once, the rest in turn (#213).
//
// Civitai makes copies at 10 to 16 a second whatever is asked, and queues the
// rest: 100 asked at once took 5.2 s each, and a Gallery part grouped by model
// asks for up to 400 - where images failed to load. So the loader every image
// grid uses holds a place for each image loading, as many as the setting
// says, and the rest wait in the order they came into view. An image frees
// its place once it has loaded or failed for good - a copy that fails asks
// for its upload on the same place. One that leaves the view while waiting is
// never asked for; one the grid takes away while it loads keeps its place
// until its download ends - the browser goes on with it - or 30 s (#240). A
// video holds a place until its still has loaded. Your generations are the
// WebUI's own files, and load as they come.
import { checker, mountTab, sharedModule, startServices } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_gallery.py');
const { check, waitFor, done } = checker();

let atOnce = 64;
globalThis.fetch = async (url) => {
    const body = String(url).includes('/model-manager/ui-options')
        ? { success: true, ...(atOnce === undefined ? {} : { images_at_once: atOnce }) } : { success: true };
    return { ok: true, status: 200, json: async () => body };
};

// What the browser does that linkedom does not: a still read by an image
// never put in the page, which only the suite can say has loaded.
const stills = [];
const createElement = document.createElement.bind(document);
document.createElement = (tag, ...rest) => {
    const element = createElement(tag, ...rest);
    if (String(tag).toLowerCase() === 'img') stills.push(element);
    return element;
};

const ui = await sharedModule('ui_options.mjs');
await ui.uiOptions();
const { setupLazyMedia } = await sharedModule('media.mjs');
// The limit on a place, run by the suite: what media.mjs leaves for 30 s.
const limits = [];
const setTimer = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...rest) => {
    if (ms === 30000) {
        limits.push(fn);
        return 0;
    }
    return setTimer(fn, ms, ...rest);
};
await startServices('media.mjs');

const C = 'https://image.civitai.com/acct';
const GIF = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
const PLACEHOLDER = 'data:image/svg+xml,unavailable';
const imageHtml = (n) => `<img data-n="${n}" data-src="${C}/width=450/${n}.jpeg" class="mm-lazy-media" src="${GIF}"
    loading="lazy" data-original="${C}/original=true/${n}.jpeg" data-placeholder="${PLACEHOLDER}">`;
let grids = 0;
function grid(count, html = imageHtml) {
    const box = document.createElement('div');
    box.id = `grid${++grids}`;
    box.innerHTML = Array.from({ length: count }, (_, i) => html(i + 1)).join('');
    document.body.appendChild(box);
    return box;
}
const images = (box) => [...box.querySelectorAll('img, video')];
const asked = (box) => images(box).filter((el) => /^https:\/\/image\.civitai\.com|^\/file=/.test(el.getAttribute('src') || ''))
    .map((el) => Number(el.dataset.n));
// A load's and an error's events do not bubble; a browser still hands them to
// the page's listeners on the way down. linkedom does that only for an event
// that bubbles.
const loaded = (el) => el.dispatchEvent(new window.Event('load', { bubbles: true }));
const failed = (el) => el.dispatchEvent(new window.Event('error', { bubbles: true }));
const nth = (box, n) => box.querySelector(`[data-n="${n}"]`);
const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i);

// ------------------------------------------------------------ no watcher
// A browser without one: every image waits for a place, in page order. The
// harness's stand-in, which watches nothing, taken away for it.
delete globalThis.IntersectionObserver;
check('the page has no watcher', 'IntersectionObserver' in window, false);
const plain = grid(100);
setupLazyMedia(plain);
check('no watcher: 64 of 100 asked for at once', asked(plain), range(1, 64));
loaded(nth(plain, 1));
check('and the 65th once one has loaded', asked(plain).length, 65);
check('one asked for now, whatever the browser\'s own lazy loading would wait for',
      [nth(plain, 2).hasAttribute('loading'), nth(plain, 90).getAttribute('loading')], [false, 'lazy']);
plain.remove();

// ------------------------------------------------------------ the watcher
// Says which images are in view, as the suite tells it.
let watcher = null;
class Watcher {
    constructor(callback) { this.callback = callback; this.watched = new Set(); watcher = this; }
    observe(el) { this.watched.add(el); }
    unobserve(el) { this.watched.delete(el); }
    disconnect() { this.watched.clear(); }
    show(els, inView = true) {
        this.callback(els.filter((el) => this.watched.has(el)).map((target) => ({ target, isIntersecting: inView })));
    }
}
globalThis.IntersectionObserver = Watcher;

const box = grid(100);
setupLazyMedia(box);
check('nothing asked for before it comes into view', asked(box), []);
watcher.show(images(box));
check('100 in view while the 64 taken away still download: none asked for - those go on, off the page',
      asked(box), []);
range(2, 65).forEach((n) => loaded(nth(plain, n)));
check('as those end, their places go to the new ones: the first 64', asked(box), range(1, 64));
loaded(nth(box, 1));
check('one loads: the 65th is asked for', asked(box).includes(65), true);
check('and no more', asked(box).length, 65);

failed(nth(box, 2));
check('a copy fails: its upload asked for, on the same place - nothing else starts',
      [nth(box, 2).getAttribute('src'), asked(box).length], [`${C}/original=true/2.jpeg`, 65]);
failed(nth(box, 2));
check('the upload fails too: "Image unavailable", and the next in line starts',
      [nth(box, 2).getAttribute('src'), asked(box).includes(66)], [PLACEHOLDER, true]);

watcher.show([nth(box, 67), nth(box, 68)], false);
[3, 4, 5].forEach((n) => loaded(nth(box, n)));
check('two waiting images leave the view: passed over, never asked for',
      [asked(box).includes(67), asked(box).includes(68), asked(box).includes(71)], [false, false, true]);
watcher.show([nth(box, 68)]);
range(6, 35).forEach((n) => loaded(nth(box, n)));
const order = asked(box);
check('back in view, one is asked for in its turn: after those that waited all along',
      [order.includes(68), order.includes(67), order.includes(100)], [true, false, true]);

// The order they came into view, not the page's.
const late = grid(3);
setupLazyMedia(late);
watcher.show([nth(late, 3), nth(late, 1), nth(late, 2)]);
check('places all taken: the new ones wait', asked(late), []);
loaded(nth(box, 36));
check('they start in the order they came into view: the third first', asked(late), [3]);
loaded(nth(box, 37));
check('then the first', asked(late), [1, 3]);

// A generation is the WebUI's own file: it waits for nothing.
const mine = grid(2, (n) => `<img data-n="${n}" data-src="/file=C:/outputs/${n}.png" class="mm-lazy-media" src="${GIF}"
    loading="lazy" data-original="" data-placeholder="${PLACEHOLDER}">`);
setupLazyMedia(mine);
watcher.show(images(mine));
check('your generations load at once while 64 of Civitai\'s do', asked(mine), [1, 2]);

// ------------------------------------------------------------ redrawn
box.remove();
late.remove();
const next = grid(10);
setupLazyMedia(next);
watcher.show(images(next));
check('the grid drawn again while 64 load: the new grid\'s images wait - the old downloads go on',
      asked(next), []);
// 38 to 43 were asked for, and have not ended.
range(38, 43).forEach((n) => loaded(nth(box, n)));
check('as six of them end, six of the new grid start', asked(next), range(1, 6));
const waiting = limits.length;
limits.splice(0).forEach((limit) => limit());
check('a download that never ends frees its place after 30 s: the rest start', [waiting > 0, asked(next)], [true, range(1, 10)]);
images(next).forEach(loaded);
next.remove();
// Taken away, then its copy fails: no upload is asked for an image no longer shown.
const gone = grid(1);
setupLazyMedia(gone);
watcher.show(images(gone));
const goneImage = nth(gone, 1);
gone.remove();
goneImage.dispatchEvent(new window.Event('error'));
check('an image taken away whose copy fails: its upload is not asked for', goneImage.getAttribute('src'), `${C}/width=450/1.jpeg`);

// ------------------------------------------------------------ a video
// Its still is all it loads before it is played; the server sends it on to Civitai.
atOnce = 1;
await ui.refreshUiOptions();
const videos = grid(2, (n) => `<video data-n="${n}" data-src="${C}/width=450/${n}.mp4"
    data-poster="/model-manager/video-still?url=${n}" class="mm-lazy-media" preload="none"></video>`);
videos.querySelectorAll('video').forEach((v) => { v.load = () => {}; });
stills.length = 0;
setupLazyMedia(videos);
watcher.show(images(videos));
check('a video holds a place until its still loads: the setting says 1, the second waits',
      [nth(videos, 1).getAttribute('poster'), nth(videos, 2).getAttribute('poster')],
      ['/model-manager/video-still?url=1', null]);
const still = stills.find((img) => img.getAttribute('src') === '/model-manager/video-still?url=1');
if (still) loaded(still);
check('its still loaded: the next starts', nth(videos, 2).getAttribute('poster'), '/model-manager/video-still?url=2');
// Each part below starts with nothing loading: what this one asked for ends first.
const second = stills.find((img) => img.getAttribute('src') === '/model-manager/video-still?url=2');
if (second) loaded(second);
videos.remove();

// ------------------------------------------------------------ the setting
atOnce = 2;
await ui.refreshUiOptions();
const two = grid(5);
setupLazyMedia(two);
watcher.show(images(two));
check('the setting says 2: 2 asked for at once', asked(two), [1, 2]);
images(two).forEach(loaded);
two.remove();

atOnce = 5;
await ui.refreshUiOptions();
const lower = grid(8);
setupLazyMedia(lower);
watcher.show(images(lower));
check('at 5, 5 load', asked(lower).length, 5);
atOnce = 2;
await ui.refreshUiOptions();
loaded(nth(lower, 1));
loaded(nth(lower, 2));
check('set lower while they load: none starts while 2 or more still load', asked(lower).length, 5);
[3, 4].forEach((n) => loaded(nth(lower, n)));
check('one starts once fewer than 2 load', asked(lower), [1, 2, 3, 4, 5, 6]);
lower.remove();

atOnce = 'many';
await ui.refreshUiOptions();
check('an answer that is not a whole number: 64', ui.imagesAtOnce?.(), 64);
atOnce = 3;
await ui.refreshUiOptions();
atOnce = undefined;
await ui.refreshUiOptions();
check('a server too old to say: 64', ui.imagesAtOnce?.(), 64);

await waitFor('nothing left to settle', () => true);
done();
