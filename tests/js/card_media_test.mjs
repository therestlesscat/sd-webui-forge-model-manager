// Where a card loads its image or video from.
//
// The segment before a Civitai image URL's file name says what to send:
// original=true is the upload as it was, width=N a copy Civitai makes. An
// animated upload stays the GIF it was even under a .mp4 name, so a card
// asking for the original got 17 MB of GIF, read it as video by its name,
// could not play it, and stayed blank (model 11718). A video is therefore
// asked for as a 450-wide copy, which is a real MP4. An image is asked for
// as uploaded: resizing is Civitai making a file on request, and cards would
// ask it for a great many.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const shared = await import(`file:///${ROOT}/javascript/shared/common.mjs`);
const { cardMediaUrl, CARD_VIDEO_WIDTH } = shared;
const C = 'https://image.civitai.com/acct/1234-abcd';

// ------------------------------------------------------------------ the helper
check('a card asks for a video 450 wide', CARD_VIDEO_WIDTH, 450);
check('a video named as one is asked for as a resized copy, which is a real MP4',
      cardMediaUrl(`${C}/original=true/293422.mp4`), `${C}/width=450/293422.mp4`);
check('as is one Civitai says is a video, whatever its name',
      cardMediaUrl(`${C}/original=true/a.jpeg`, 'video'), `${C}/width=450/a.jpeg`);
check('an image is asked for as uploaded',
      cardMediaUrl(`${C}/original=true/a.jpeg`), `${C}/original=true/a.jpeg`);
check('even when the URL it came with asked for a resized copy',
      cardMediaUrl(`${C}/width=1024,anim=false/a.jpeg`, 'image'), `${C}/original=true/a.jpeg`);
check('anything not from Civitai\'s image server is left as it is',
      cardMediaUrl('https://example.invalid/width=9/a.mp4'), 'https://example.invalid/width=9/a.mp4');
check('as is a Civitai URL with no options segment', cardMediaUrl(`${C}/a.jpeg`), `${C}/a.jpeg`);
check('and nothing stays nothing', [cardMediaUrl(''), cardMediaUrl(null)], ['', '']);

// ------------------------------------------------------- the Model Manager card
const MODEL = {
    id: 20937, model_id: 11718, name: 'Animated cover', display_name: 'Animated cover',
    version_name: 'v1', base_model: 'SD 1.5', model_type: 'Checkpoint',
    file_path: 'C:/m/a.safetensors', file_name: 'a.safetensors', file_size: 1, nsfw_level: 1,
    has_civitai_data: true, local_version_count: 1, trained_words: [], tags: [],
    preview_url: `${C}/original=true/293422.mp4`,
};
globalThis.fetch = async (url) => ({ ok: true, json: async () => (
    String(url).includes('/model-manager/models')
        ? { success: true, total: 1, page: 1, page_size: 20, models: [MODEL] }
        : { success: true }) });

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the card', () => document.querySelector('#mm_grid .model-card'));
const media = document.querySelector('#mm_grid .model-card video, #mm_grid .model-card img');
check('the Model Manager card asks for a video as the resized copy, which it can play',
      [media?.tagName.toLowerCase(), media?.getAttribute('src')],
      ['video', `${C}/width=450/293422.mp4`]);

done();
