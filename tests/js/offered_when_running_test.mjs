// What is offered only while what it needs runs (#182): a download, while the
// downloads list runs. The Model Manager and the Civitai Browser start it,
// and a tab without them - Generations, the Queue - sends without it. The
// Resources dialog and the chips then offer no Download. A note's Sync,
// while the Model Manager is available: tab_links_test.mjs (#184).
import { checker, mountTab, sharedModule, startServices } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('beforeend', '<div id="txt2img_neg_prompt_row"></div>');

globalThis.fetch = async () => ({ ok: true, status: 200,
    json: async () => ({ success: true, versions: {}, hashes: {}, downloads: [], resources: {} }) });

// As the Generations tab starts them: Send, and with it the Resources dialog
// and the chips - not the downloads list.
await startServices('core.mjs', 'calls.mjs', 'send.mjs');
const resources = await sharedModule('resources.mjs');
const chips = await sharedModule('chips.mjs');

// ------------------------------------------------------------ a download
const IMAGE = { id: 1, meta: { prompt: 'a prompt',
    civitaiResources: [{ type: 'LORA', name: 'Some LoRA', modelVersionId: 6001, modelId: 4001 }] } };
const CHIP = { kind: 'lora', name: 'some_lora', title: 'Some LoRA', weight: 1, versionId: 6001, modelId: 4001,
               installed: false };
const cell = () => document.querySelector('.mm-resources-modal [data-res-download="6001"]')?.innerHTML || '';
const chip = () => document.querySelector('#mm_resource_chips_txt2img [data-chip="0"]');

await resources.showImageResources(IMAGE, null);
await waitFor('the Resources dialog', () => cell());
check('downloads off: the dialog says it is not in the library, and offers no Download',
      [cell().includes('Not in the library'), cell().includes('resources.download')], [true, false]);
chips.showResourceChips('txt2img', [{ ...CHIP }]);
check('nor does its chip: it cannot be pressed, and says it is not available',
      [chip()?.disabled, chip()?.dataset.state], [true, 'unavailable']);
let asked = 0;
const realFetch = globalThis.fetch;
globalThis.fetch = (url) => { if (String(url).includes('/civitai/download')) asked += 1; return realFetch(url); };
await resources.downloadResource(6001, 4001);
check('and a download asked for all the same asks for nothing', asked, 0);

await startServices('downloads.mjs');   // as the Model Manager or the Civitai Browser starts it
await resources.showImageResources(IMAGE, null);
await waitFor('the dialog again', () => cell().includes('resources.download'));
check('downloads on: the dialog offers Download', cell().includes('data-action="resources.download"'), true);
chips.showResourceChips('txt2img', [{ ...CHIP }]);
check('and so does the chip', [chip()?.disabled, chip()?.dataset.state], [false, 'download']);

done();
