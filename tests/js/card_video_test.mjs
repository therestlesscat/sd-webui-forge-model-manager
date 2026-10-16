// Model cards: a setting to stop videos playing by themselves (#220).
//
// A model card whose cover is a video drew <video ... autoplay>: every such
// card downloaded and played its video as the grid was drawn. With "Model
// cards: play videos" off, the card shows the video's still, with a play
// button in its corner: pressed, the video plays in the card, looped and
// muted; pressed again, the still. On, the card is today's, byte for byte.
// This suite: the shared card, its button, and the Civitai Browser's grid;
// card_video_mm_test the Model Manager's.
import { ROOT, checker, mountTab, press, sharedModule, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();
const { call } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);

const VIDEO = 'https://image.civitai.com/x/abc/width=450/1.mp4';
let playing = false;           // what ui-options says of the setting
const model = (id) => ({ id, name: `Model ${id}`, type: 'Checkpoint', stats: {}, creator: {},
                         modelVersions: [{ id: id * 10, files: [],
                                           images: [{ url: VIDEO.replace('1.mp4', `${id}.mp4`), type: 'video', nsfwLevel: 1, mm_level: 1 }] }] });
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({ success: true, card_videos_play: playing }) };
    }
    if (href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true, nextCursor: null, pageSize: 2, models: [model(1), model(2)] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const { renderModelCard, CARD_PLACEHOLDER } = await sharedModule('grid.mjs');
const { fallBack } = await sharedModule('media.mjs');
// The tab asked for ui-options at its start, saying off: what a page reads at a draw.
const { uiOptions, cardVideos = () => ({ play: true }) } = await sharedModule('ui_options.mjs');
await uiOptions();

const draw = (media, action = 'test.open') => {
    const box = document.createElement('div');
    box.innerHTML = renderModelCard({ index: 0, action, name: 'A model', media });
    document.body.appendChild(box);
    return box;
};
const opened = [];
globalThis.__mmOffered?.set('test.open', () => opened.push(1));

// ------------------------------------------------------------- the setting on
const on = draw({ src: VIDEO, video: true, original: 'https://image.civitai.com/x/abc/original=true/1.mp4', play: true,
                  poster: '/model-manager/video-still?url=x' });
check('on: today\'s card, its video playing - the tag byte for byte',
      on.innerHTML.includes('<video src="https://image.civitai.com/x/abc/width=450/1.mp4" loop muted autoplay playsinline '
                            + 'data-original="https://image.civitai.com/x/abc/original=true/1.mp4" data-placeholder=""></video>'),
      true);
check('and no button', Boolean(on.querySelector('.mm-card-play')), false);

// ----------------------------------------------------------- the setting off
const off = draw({ src: VIDEO, video: true, original: 'https://image.civitai.com/x/abc/original=true/1.mp4', play: false,
                  poster: '/model-manager/video-still?url=x' });
const still = () => off.querySelector('img.mm-card-still');
const button = () => off.querySelector('.mm-card-play');
check('off: no video in the card, until pressed', /<video/.test(off.innerHTML), false);
check('its still, through the server\'s check', still()?.getAttribute('src'), '/model-manager/video-still?url=x');
check('and a play button, saying what it does', [button()?.textContent, button()?.getAttribute('title')],
      ['▶', 'Play the video']);
if (button()) press(button());
check('pressed: today\'s video tag, playing, and the button says it stops',
      [Boolean(off.querySelector('video[autoplay][loop][muted]')), off.querySelector('video')?.getAttribute('src'),
       button()?.textContent, button()?.getAttribute('title')],
      [true, VIDEO, '■', 'Stop on the still']);
check('the press is the button\'s: the card does not open the model', opened, []);
if (button()) press(button());
check('pressed again: the still, the button back to play',
      [Boolean(off.querySelector('video')), Boolean(still()) && !still().hidden, button()?.textContent], [false, true, '▶']);

// ------------------------------------------------------- no still to show
const bare = draw({ src: VIDEO, video: true, original: '', play: false, poster: '' });
check('a video with no still: the placeholder from the start', bare.querySelector('img.mm-card-still')?.getAttribute('src'),
      CARD_PLACEHOLDER);
const failing = off.querySelector('img.mm-card-still');
// What the page's one error listener does with it (media.mjs).
if (failing) fallBack(failing);
check('a still that fails to load: the placeholder', failing?.getAttribute('src'), CARD_PLACEHOLDER);
const image = draw({ src: 'https://image.civitai.com/x/abc/width=450/3.jpeg', video: false, original: '', play: false });
check('an image cover, off: unchanged, no button',
      [Boolean(image.querySelector('img:not(.mm-card-still)')), Boolean(image.querySelector('.mm-card-play'))], [true, false]);

// ------------------------------------------------------- the Browser's grid
check('ui-options say off: the page reads it', cardVideos().play, false);
const html = await call('cardPreview.model_manager_civitai_card_size', 2);
check('the Civitai Browser\'s cards show the still and the button, no video',
      [(html.match(/mm-card-still/g) || []).length, (html.match(/mm-card-play/g) || []).length, /<video/.test(html)],
      [2, 2, false]);

done();
