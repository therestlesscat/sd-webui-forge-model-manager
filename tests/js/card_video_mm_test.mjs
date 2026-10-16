// Model cards: play videos (#220), in the Model Manager's grid: with the
// setting off, a library model whose preview is a video shows its still and
// the play button, not the video. card_video_test has the card itself and
// the Civitai Browser's grid.
import { ROOT, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, done } = checker();
const { call } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);

const model = (id, preview) => ({ id, civitai_model_id: id + 10, display_name: `Model ${id}`, model_type: 'LORA',
                                  preview_url: preview, has_civitai_data: true, nsfw_level: 1, local_version_count: 1,
                                  file_path: `C:/m/${id}.safetensors` });
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({ success: true, card_videos_play: false }) };
    }
    if (href.includes('/model-manager/models')) {
        return { ok: true, json: async () => ({ success: true, total: 2, page: 1, page_size: 20, models: [
            model(1, 'https://image.civitai.com/x/abc/original=true/1.mp4'),
            model(2, 'https://image.civitai.com/x/abc/original=true/2.jpeg')] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const html = await call('cardPreview.model_manager_card_size', 2);
check('off: the video card shows its still and the play button, no video',
      [(html.match(/mm-card-still/g) || []).length, (html.match(/mm-card-play/g) || []).length, /<video/.test(html)],
      [1, 1, false]);
check('its still through the server\'s check', /src="\/model-manager\/video-still\?url=/.test(html), true);
check('the image card is as before', (html.match(/<img /g) || []).length, 2);

done();
