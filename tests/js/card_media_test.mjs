// Where a card loads its image or video from: a copy the size it is drawn.
//
// The segment before a Civitai image URL's file name says what to send:
// original=true is the upload as it was, width=N a copy Civitai makes. Its
// server has fixed widths - asked for one in between, it sends the next one
// up - and enlarges as readily, so an image is never asked for wider than it
// was uploaded. Images were loaded as uploaded until 0.30.1, lest Civitai
// throttle so many copies: a gallery page of originals was up to 100 files
// of 0.1 to 2.9 MB, where a 450-wide copy was 86 KB, and 130 copies asked for
// at five a second met no limit. A copy that fails falls back to the upload.
//
// A video is always a copy: an animated upload stays the GIF it was even
// under a .mp4 name, so a card asking for the original got 17 MB of GIF,
// read it as video by its name, could not play it, and stayed blank (model
// 11718). A copy is a real MP4.
import { ROOT, checker, mountTab, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const mediaModule = await import(`file:///${ROOT}/javascript/shared/media.mjs`);
const { nsfwBadge } = await import(`file:///${ROOT}/javascript/shared/nsfw.mjs`);
const { cardMediaUrl, sizedMediaUrl, videoStillUrl, civitaiWidth, CIVITAI_WIDTHS,
        galleryImageWidth, GALLERY_IMAGE_WIDTH, mediaShape } = mediaModule;
const C = 'https://image.civitai.com/acct/1234-abcd';

// ----------------------------------------------------------------- the widths
check('Civitai\'s widths, as its server makes them',
      CIVITAI_WIDTHS, [320, 450, 512, 800, 1200, 1600, 2200]);
check('a width is rounded up to the next of them',
      [1, 320, 321, 460, 600, 1201, 5000].map(civitaiWidth), [320, 320, 450, 512, 800, 1600, 2200]);

// ------------------------------------------------------------------ the helper
check('an image drawn 200 wide is asked for as the copy that covers it',
      cardMediaUrl(`${C}/original=true/a.jpeg`), `${C}/width=320/a.jpeg`);
window.devicePixelRatio = 2;
check('with twice as many pixels on a 2x screen',
      cardMediaUrl(`${C}/original=true/a.jpeg`), `${C}/width=450/a.jpeg`);
check('but a fixed number of pixels is that, whatever the screen',
      sizedMediaUrl(`${C}/original=true/a.mp4`, { pixels: 450, type: 'video' }), `${C}/width=450/a.mp4`);
window.devicePixelRatio = 1;
check('the card\'s own width decides, as the settings set it',
      cardMediaUrl(`${C}/original=true/a.jpeg`, 'image', 300), `${C}/width=320/a.jpeg`);
check('never wider than it was uploaded: Civitai would enlarge it - the upload instead',
      cardMediaUrl(`${C}/width=450/a.jpeg`, 'image', 200, 300), `${C}/original=true/a.jpeg`);
check('a video is always asked for as a copy, which is a real MP4',
      cardMediaUrl(`${C}/original=true/293422.mp4`, null, 200, 100), `${C}/width=320/293422.mp4`);
check('as is one Civitai says is a video, whatever its name',
      cardMediaUrl(`${C}/original=true/a.jpeg`, 'video'), `${C}/width=320/a.jpeg`);
check('a video\'s still is its first frame, as a JPEG',
      videoStillUrl(`${C}/original=true/293422.mp4`), `${C}/anim=false/293422.mp4`);
check('anything not from Civitai\'s image server is left as it is',
      cardMediaUrl('https://example.invalid/width=9/a.mp4'), 'https://example.invalid/width=9/a.mp4');
check('as is a Civitai URL with no options segment', cardMediaUrl(`${C}/a.jpeg`), `${C}/a.jpeg`);
check('and nothing stays nothing', [cardMediaUrl(''), cardMediaUrl(null)], ['', '']);
check('a gallery\'s image width, where nothing can be measured, is the stylesheet\'s default',
      galleryImageWidth(null), GALLERY_IMAGE_WIDTH);

// ------------------------------------------------------------ falling back
// A copy that does not load falls back to the upload, and that to the
// placeholder. The placeholder is an attribute: written into onerror's
// string, its SVG's quotes ended the string, and it never showed.
const img = document.createElement('img');
img.setAttribute('src', `${C}/width=320/a.jpeg`);
img.setAttribute('data-original', `${C}/original=true/a.jpeg`);
img.setAttribute('data-placeholder', 'data:image/svg+xml,placeholder');
window.mmMediaFallback(img);
check('a copy that fails falls back to the upload', img.getAttribute('src'), `${C}/original=true/a.jpeg`);
window.mmMediaFallback(img);
check('and an upload that fails to the placeholder', img.getAttribute('src'), 'data:image/svg+xml,placeholder');

// ------------------------------------------------------- the Model Manager card
const MODEL = {
    id: 20937, model_id: 11718, name: 'Animated cover', display_name: 'Animated cover',
    version_name: 'v1', base_model: 'SD 1.5', model_type: 'Checkpoint',
    file_path: 'C:/m/a.safetensors', file_name: 'a.safetensors', file_size: 1, nsfw_level: 1,
    has_civitai_data: true, local_version_count: 1, trained_words: [], tags: [],
    preview_url: `${C}/original=true/293422.mp4`,
};
// Its gallery: an image uploaded 1024 wide, and a video.
const GALLERY = [
    { id: 1, url: `${C}/original=true/still.jpeg`, width: 1024, height: 1536, type: 'image',
      nsfw: true, mm_level: 1, meta: { prompt: 'a lighthouse by the sea' } },
    { id: 2, url: `${C}/original=true/moving.mp4`, width: 720, height: 1280, type: 'video',
      nsfw: false, mm_level: 4, meta: { prompt: 'waves roll in on a beach' } },
];
globalThis.fetch = withGalleryPages(async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...MODEL, images: GALLERY, generations_count: 0,
            images_state: { version_id: 20937, total_count: 2, filtered_count: 2, offset: 0,
                            hide_nsfw_images: false, hide_promptless_images: false } } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MODEL] });
    }
    return reply({ success: true });
});

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the card', () => document.querySelector('#mm_grid .model-card'));
const media = document.querySelector('#mm_grid .model-card video, #mm_grid .model-card img');
check('the Model Manager card asks for a video as the copy for its width, which it can play',
      [media?.tagName.toLowerCase(), media?.getAttribute('src')],
      ['video', `${C}/width=320/293422.mp4`]);
check('falling back to the upload',
      [media?.getAttribute('data-original'), media?.getAttribute('onerror')],
      [`${C}/original=true/293422.mp4`, 'window.mmMediaFallback(this)']);

// ------------------------------------------------------------ the gallery
await window.mmSelectModel(0);
await waitFor('the gallery', () => document.querySelector('#mm_images .mm-image-card'));
const galleryImage = document.querySelector('#mm_images .mm-image-card img');
check('a gallery image loads the copy its card draws, and the viewer shows the upload',
      [galleryImage?.getAttribute('data-src'),
       galleryImage?.closest('.mm-image-left')?.getAttribute('data-viewer-url'),
       galleryImage?.getAttribute('data-original'), galleryImage?.hasAttribute('data-view-index')],
      [`${C}/width=320/still.jpeg`, `${C}/original=true/still.jpeg`, `${C}/original=true/still.jpeg`, true]);
const galleryVideo = document.querySelector('#mm_images .mm-image-card video');
check('a gallery video plays a copy, showing its still until played - through the server\'s check that it is one',
      [galleryVideo?.getAttribute('data-src'), galleryVideo?.getAttribute('data-poster')],
      [`${C}/width=320/moving.mp4`, `/model-manager/video-still?url=${encodeURIComponent(`${C}/anim=false/moving.mp4`)}`]);
// Loaded lazily, from a 1x1 placeholder: without its shape each started
// square, grew when it loaded, and a scroll to a card below stopped short.
check('each holds its own shape before it loads, from the size Civitai gives',
      [galleryImage?.style?.aspectRatio || galleryImage?.getAttribute('style'),
       galleryVideo?.style?.aspectRatio || galleryVideo?.getAttribute('style')],
      ['1024 / 1536', '720 / 1280']);
check('and none it does not know', [mediaShape({ width: 1024 }), mediaShape(null)], ['', '']);

// ------------------------------------------------------- the viewer's video
// The viewer plays a copy, not the upload: an upload often keeps its index at
// the end of the file - about three of Civitai's answers before a frame - and
// every copy keeps it at the start. As wide as the frame shows it on this
// screen, at one of Civitai's widths, never past the video's own.
const { viewerVideoUrl } = mediaModule;
const UP = `${C}/original=true/moving.mp4`;
const V = { width: 960, height: 1440 };
check('a frame narrower than the video: a copy that wide, at the next of Civitai\'s widths',
      viewerVideoUrl(UP, V, { width: 500, height: 2000 }), `${C}/width=512/moving.mp4`);
check('a short frame: as wide as the video is drawn at its height',
      viewerVideoUrl(UP, V, { width: 2000, height: 600 }), `${C}/width=450/moving.mp4`);
check('a frame wider than the video: the video\'s own width - never enlarged',
      viewerVideoUrl(UP, V, { width: 3000, height: 3000 }), `${C}/width=960/moving.mp4`);
window.devicePixelRatio = 2;
check('twice the pixels on a 2x screen', viewerVideoUrl(UP, V, { width: 300, height: 2000 }), `${C}/width=800/moving.mp4`);
window.devicePixelRatio = 1;
check('nothing measured: the video\'s own width', viewerVideoUrl(UP, V, {}), `${C}/width=960/moving.mp4`);
check('your own generation, not Civitai\'s: as it is',
      viewerVideoUrl('/model-manager/generations/images/7/file', V, { width: 500 }), '/model-manager/generations/images/7/file');

galleryVideo.closest('.mm-image-card').querySelector('[data-view-index]')
    .dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the viewer', () => document.querySelector('.mm-viewer video'));
check('the viewer plays the gallery video from a copy, the upload kept as the card\'s own',
      [document.querySelector('.mm-viewer video')?.getAttribute('src'),
       galleryVideo.closest('.mm-image-left').getAttribute('data-viewer-url')],
      [`${C}/width=720/moving.mp4`, UP]);
document.querySelector('.mm-viewer [data-close]')?.dispatchEvent(new window.Event('click', { bubbles: true }));

// The badge is the level the server judged, from R up - never Civitai's own
// `nsfw`, a boolean on most images, which the badge once printed as "true".
const badges = () => Array.from(document.querySelectorAll('#mm_images .mm-image-card'))
    .map((c) => c.querySelector('.mm-nsfw-badge')?.textContent.trim() ?? '');
check('a card badges its level from R up, whatever Civitai\'s nsfw flag says', badges(), ['', 'R']);
check('each level named, the prompt\'s said as such, and nothing below R or unknown',
      [1, 2, 4, 8, 16, 32, 64].map((mm_level) => nsfwBadge({ mm_level, nsfw: true }))
          .concat(nsfwBadge({ mm_level: 8, mm_level_from_prompt: true }), nsfwBadge({ nsfw: true })),
      ['', '', 'R', 'X', 'XXX', 'Blocked', '', 'X · prompt', '']);

done();
