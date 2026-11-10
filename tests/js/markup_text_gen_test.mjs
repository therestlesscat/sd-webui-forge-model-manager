// The Generations tab's tiles put the server's counts into markup - in a
// tile's title and its text (S2). The server works them out as numbers; the
// tile now draws them as numbers, so nothing else can be drawn as markup.
//
// A marker shows a fault: inside an attribute, a value that closes the quote
// and adds one; between tags, an element. Nothing in it runs.
import { checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const ODD = '2" data-mm-marker="1 <i data-mm-marker></i>';
const img = (id) => ({
    id, generation_id: 1, position: id, seed: id, width: 832, height: 1216,
    meta: { prompt: `prompt ${id}` }, infotext: `prompt ${id}\nSteps: 20`,
    url: `/model-manager/generations/images/${id}/file`, exists: true,
    mm_level: 1, mm_level_from_prompt: false, user_level: null, prompt_level: 1,
});
const GENERATION = { id: 1, mode: 'txt2img', created_at: '2026-09-28T20:00:00', image_count: 2 };
const TILE = {
    kind: 'group', generation: GENERATION, matching_count: ODD, images: [img(1), img(2)],
    checkpoint_path: null, checkpoint: null, loras: [], level: 1, user_level: null,
    group: { id: '832×1216', value: '832×1216', by: 'size', latest: GENERATION.created_at, generations: ODD },
};

globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, gallery_hide_nsfw: false, hide_promptless_images: false });
    }
    if (href.includes('/generations/browse')) {
        return reply({ success: true, tiles: [TILE], more: false,
                       state: { total: 2, filtered: 2, hidden_nsfw: 0, nsfw_count: 0, nsfw_images: 'all',
                                stored_generations: 1 },
                       scope: { count: 2, first: GENERATION.created_at, last: GENERATION.created_at } });
    }
    return reply({ success: true });
};

const sentinel = document.getElementById('gen_sentinel');
sentinel.getBoundingClientRect = () => ({ top: 100000 });
window.innerHeight = 900;

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const tile = () => document.querySelector('#gen_grid .gen-tile');
await waitFor('the tile', () => tile()?.querySelector('.gen-group-facts'));

check('no count is drawn as markup: no element, no attribute added',
      document.querySelectorAll('#gen_grid [data-mm-marker]').length, 0);

done();
