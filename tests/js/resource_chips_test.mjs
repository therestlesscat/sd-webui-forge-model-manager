// The rules behind the resource chips a send puts under the prompts.
//
// Most images list their LoRAs as resources without a tag in the prompt, so
// sending one meant finding each LoRA by hand. A chip per LoRA and embedding
// puts its tag in with a click, or takes it out. What goes in is the local
// file's name, which Forge always knows; what comes out is the tag at any
// weight, since a weight edited by hand is still that LoRA.
import { ROOT, checker } from './harness.mjs';

const { check, done } = checker();
const { collectResourceChips, toggleChip, promptHasChip, renameLoraTags, chipTag,
        DEFAULT_LORA_WEIGHT, resourceNames, promptLoras } = await import(`file:///${ROOT}/javascript/shared/chips.mjs`);

const lora = { kind: 'lora', name: 'add_detail', weight: 0.5 };
const embedding = { kind: 'embedding', name: 'easynegative' };

// ------------------------------------------------------------ the tags
check('a LoRA\'s tag names its file and weight', chipTag(lora), '<lora:add_detail:0.5>');
check('an embedding\'s is its name', chipTag(embedding), 'easynegative');
check('a LoRA is found at any weight, or none',
      [promptHasChip('a, <lora:add_detail:1.2>', lora), promptHasChip('<lora:add_detail>', lora),
       promptHasChip('<LORA:Add_Detail:0.3>', lora)], [true, true, true]);
check('but not a LoRA whose name only starts the same',
      promptHasChip('<lora:add_detail_xl:1>', lora), false);
check('an embedding as a word of its own, not inside another',
      [promptHasChip('x, easynegative, y', embedding), promptHasChip('easynegative_v2', embedding),
       promptHasChip('not-easynegative', embedding)], [true, false, false]);
check('a name with regex characters is taken literally',
      promptHasChip('<lora:a.b(c):1>', { kind: 'lora', name: 'a.b(c)' }), true);

// ---------------------------------------------------------- toggling
check('a click puts it at the end, after a comma', toggleChip('a cat', lora), 'a cat, <lora:add_detail:0.5>');
check('into an empty prompt, on its own', toggleChip('', lora), '<lora:add_detail:0.5>');
check('without doubling a trailing comma', toggleChip('a cat, ', lora), 'a cat, <lora:add_detail:0.5>');
check('a second click takes it out again, comma and all',
      toggleChip(toggleChip('a cat', lora), lora), 'a cat');
check('from the middle', toggleChip('a, <lora:add_detail:0.8>, b', lora), 'a, b');
check('from the start', toggleChip('<lora:add_detail:0.8>, b', lora), 'b');
check('at whatever weight it was given by hand', toggleChip('a, <lora:add_detail:1.3>', lora), 'a');
check('every copy of it', toggleChip('<lora:add_detail:1>, a, <lora:add_detail:0.2>', lora), 'a');
check('and nothing else', toggleChip('x, <lora:other:1>, <lora:add_detail:1>, y', lora),
      'x, <lora:other:1>, y');
check('an embedding the same way',
      [toggleChip('bad hands', embedding), toggleChip('bad hands, easynegative', embedding)],
      ['bad hands, easynegative', 'bad hands']);

// ---------------------------------------------------------- renaming
check('a LoRA the prompt names otherwise is renamed to the local file, weight kept',
      renameLoraTags('a, <lora:UploaderName_v2:0.8>', 'UploaderName_v2', 'add_detail'),
      'a, <lora:add_detail:0.8>');
check('and only that one', renameLoraTags('<lora:UploaderName_v2x:1>', 'UploaderName_v2', 'add_detail'),
      '<lora:UploaderName_v2x:1>');

// ---------------------------------------------------- an image's chips
const FILES = {
    versions: { 11: { version_id: 11, file_stem: 'add_detail', file_type: 'LORA' },
                12: { version_id: 12, file_stem: 'style_locon', file_type: 'LoCon' },
                13: { version_id: 13, file_stem: 'juggernaut', file_type: 'Checkpoint' } },
    hashes: { aaaa: { version_id: 11, file_stem: 'add_detail', file_type: 'LORA' },
              bbbb: { version_id: 14, file_stem: 'easynegative', file_type: 'TextualInversion' } },
};
const META = {
    prompt: 'a cat, <lora:UploaderName_v2:0.8>',
    negativePrompt: 'easynegative, blurry',
    civitaiResources: [
        { type: 'checkpoint', modelVersionId: 13, name: 'Juggernaut' },
        { type: 'lora', modelVersionId: 11, name: 'Detail Tweaker', weight: 0.8 },
        { type: 'LoCon', modelVersionId: 12, name: 'Style' },
        { type: 'lora', modelVersionId: 99, name: 'Not Here', modelVersionName: 'v1', weight: 0.7 },
    ],
    resources: [
        { type: 'lora', name: 'UploaderName_v2', hash: 'AAAA', weight: 0.8 },
        { type: 'embed', name: 'easynegative', hash: 'bbbb' },
    ],
};
const { chips, renames } = collectResourceChips(META, FILES);
const byName = Object.fromEntries(chips.map((c) => [c.name, c]));

check('one chip per LoRA and embedding; a checkpoint is none',
      chips.map((c) => c.name), ['add_detail', 'style_locon', 'Not Here - v1', 'easynegative']);
check('a LoRA named in both lists is one chip, by its local file',
      chips.filter((c) => c.name === 'add_detail').length, 1);
check('a LoCon is a LoRA to Forge', byName.style_locon.kind, 'lora');
check('the image\'s weight where it gives one', byName.add_detail.weight, 0.8);
check(`${DEFAULT_LORA_WEIGHT} where it does not`, byName.style_locon.weight, 0.5);
check('a resource with no file here is shown, but not installed',
      [byName['Not Here - v1'].installed, byName.add_detail.installed], [false, true]);
check('a missing one keeps what the image names it by, to be downloaded by',
      [byName['Not Here - v1'].versionId, byName.add_detail.versionId], [99, 11]);
const hashOnly = collectResourceChips({ resources: [{ type: 'lora', name: 'h', hash: 'ABCD' }] }, FILES)
    .chips[0];
check('one known only by a hash keeps the hash', [hashOnly.hash, hashOnly.versionId], ['abcd', null]);
check('an embedding the image used in its negative prompt goes there',
      [byName.easynegative.kind, byName.easynegative.where], ['embedding', 'negative']);
check('everything else the positive one', byName.add_detail.where, 'positive');
check('the prompt\'s other name for a LoRA is to be renamed to the file',
      renames, [{ from: 'UploaderName_v2', to: 'add_detail' }]);

const gallery = collectResourceChips({ prompt: 'a cat' }, { versions: {}, hashes: {} },
                                     { file_stem: 'my_lora', file_type: 'LORA' });
check('the gallery\'s own LoRA is a chip though the image does not list it',
      gallery.chips.map((c) => [c.name, c.installed, c.weight]), [['my_lora', true, 0.5]]);
check('and nothing listed, nothing shown',
      collectResourceChips({}, null).chips, []);

// ------------------------------------------------ found by the file's name
// Forge writes a LoRA's hash into the image's `hashes`, not its resources:
// one library's Ghibli_v6 was named {"type": "lora", "name": "Ghibli_v6"}
// with "lora:Ghibli_v6": "58549cc3d3" beside it. That hash is looked up, and
// sent with the name, for a file no id or hash finds.
const GHIBLI = { resources: [{ type: 'lora', name: 'Ghibli_v6', weight: 0.8 }, { type: 'model', name: 'ckpt' },
                             { type: 'embed', name: 'an12' }],
                 hashes: { 'lora:Ghibli_v6': '58549cc3d3', 'embed:an12': '1c6c72d33a', model: 'b0d25db787' } };
check('the names to look for: LoRAs and embeddings, each with the hash the image keeps for it',
      resourceNames(GHIBLI), [{ name: 'Ghibli_v6', hash: '58549cc3d3' }, { name: 'an12', hash: '1c6c72d33a' }]);
const file = { version_id: null, file_stem: 'Ghibli_v6', file_type: 'LORA' };
const found = collectResourceChips(GHIBLI, { versions: {}, hashes: {}, names: { ghibli_v6: file } }).chips;
check('a file found only by name is a chip you have, and says how it was found',
      found.filter((c) => c.name === 'Ghibli_v6').map((c) => [c.installed, c.byName]), [[true, true]]);
const both = collectResourceChips(GHIBLI, { versions: {}, hashes: { '58549cc3d3': file }, names: { ghibli_v6: file } }).chips;
check('found by the hash, it was not found by name', both.find((c) => c.name === 'Ghibli_v6').byName, false);
const twice = collectResourceChips({ resources: [{ type: 'lora', name: 'Ghibli_v6' },
                                                 { type: 'lora', name: 'ghibli-other-name', hash: '58549cc3d3' }] },
                                   { versions: {}, hashes: { '58549cc3d3': file }, names: { ghibli_v6: file } }).chips;
check('a file one entry finds by name and another by hash is one chip, found by hash',
      twice.map((c) => [c.name, c.byName]), [['Ghibli_v6', false]]);
check('and with no file by name, still missing', collectResourceChips(GHIBLI, { versions: {}, hashes: {} })
    .chips.find((c) => c.name === 'Ghibli_v6')?.installed, false);

// ------------------------------------------- one LoRA, named twice (#30)
// Image 84731975: Civitai's list names the LoRA by version, the infotext by
// its file's name, with its weight - and its hash is in `hashes`, keyed
// "LORA:" in capitals, as 5,561 keys in one library were (and 35 "EMBED:").
// The hash was looked for under "lora:" only, so the LoRA came out twice: a
// chip to download, and one with "no hash recorded".
const MESO = {
    civitaiResources: [{ type: 'LORA', name: 'MesoAmerican Outfit (Aztec/Mayan) [Illustrious]', modelId: 443711,
                         modelVersionId: 1904077, modelVersionName: 'Illustrious' }],
    resources: [{ type: 'lora', name: 'MesoamericaOutfit_IXL', weight: 0.8 }, { type: 'embed', name: 'an12' }],
    hashes: { 'LORA:MesoamericaOutfit_IXL': '06200f1e9e', 'EMBED:an12': '1c6c72d33a' },
};
const MESO_FUTURE = { file_stem: 'MesoamericaOutfit_IXL', file_type: 'LORA', model_id: 443711 };
check('a hash keyed in capitals is found, for a LoRA and an embedding',
      resourceNames(MESO), [{ name: 'MesoamericaOutfit_IXL', hash: '06200f1e9e' }, { name: 'an12', hash: '1c6c72d33a' }]);
const byHashToo = collectResourceChips(MESO, { versions: {}, hashes: {} },
    null, { hashes: { '06200f1e9e': 1904077 }, versions: { 1904077: MESO_FUTURE } }).chips.filter((c) => c.kind === 'lora');
check('so Civitai finds its version, and the LoRA is one chip, with the infotext\'s weight',
      byHashToo.map((c) => [c.name, c.versionId, c.weight, c.installed]), [['MesoamericaOutfit_IXL', 1904077, 0.8, false]]);

// No hash anywhere: the name alone. The file Civitai says the other chip's
// version is has exactly this name - the name Forge's <lora:name> loads - so
// it is the same LoRA: one chip, keeping the infotext's weight.
const NO_HASH = { ...MESO, hashes: {} };
const missingAnswer = { hashes: {}, versions: { 1904077: MESO_FUTURE } };
const byName2 = collectResourceChips(NO_HASH, { versions: {}, hashes: {} }, null, missingAnswer)
    .chips.filter((c) => c.kind === 'lora');
check('with no hash, a chip named as the file Civitai gives another\'s version is that chip',
      byName2.map((c) => [c.name, c.versionId, c.weight, c.hash]), [['MesoamericaOutfit_IXL', 1904077, 0.8, null]]);
check('ignoring case, as Forge\'s lookup of a name does', collectResourceChips(
      { ...NO_HASH, resources: [{ type: 'lora', name: 'mesoamericaoutfit_ixl', weight: 0.8 }] },
      { versions: {}, hashes: {} }, null, missingAnswer).chips.filter((c) => c.kind === 'lora').length, 1);
check('before Civitai has said what its file is called, there is nothing to match yet',
      collectResourceChips(NO_HASH, { versions: {}, hashes: {} }).chips.filter((c) => c.kind === 'lora').length, 2);
const installedMeso = collectResourceChips(NO_HASH,
    { versions: { 1904077: { version_id: 1904077, file_stem: 'MesoamericaOutfit_IXL', file_type: 'LORA' } }, hashes: {} })
    .chips.filter((c) => c.kind === 'lora');
check('the same with the file installed: one chip, the installed one',
      installedMeso.map((c) => [c.name, c.installed, c.weight]), [['MesoamericaOutfit_IXL', true, 0.8]]);
check('a name shared by a LoRA and an embedding is two things, and two chips', collectResourceChips(
      { ...NO_HASH, resources: [{ type: 'embed', name: 'MesoamericaOutfit_IXL' }] },
      { versions: {}, hashes: {} }, null, missingAnswer).chips.map((c) => c.kind).sort(), ['embedding', 'lora']);
check('and a chip the image names by hash is never merged by name', collectResourceChips(
      { ...NO_HASH, resources: [{ type: 'lora', name: 'MesoamericaOutfit_IXL', hash: 'ffff0000aa' }] },
      { versions: {}, hashes: {} }, null, missingAnswer).chips.filter((c) => c.kind === 'lora').length, 2);

// ------------------------------------------------ named only in the prompt (#179)
check('a prompt\'s LoRA tags as Forge reads them: lower-case tags, the name, the weight or 1, once each',
      promptLoras && promptLoras({ prompt: 'a, <lora:one:0.6>, <lora:two>, <LORA:three:1>, <lora:one:0.2>',
                    negativePrompt: '<lora:four:-1:0.5>' }),
      [{ name: 'one', weight: 0.6 }, { name: 'two', weight: 1 }, { name: 'four', weight: -1 }]);
check('asked of the library by name, after what the resources name, with none named twice',
      resourceNames({ prompt: '<lora:Listed:1>, <lora:tagged:0.5>',
                      resources: [{ type: 'lora', name: 'listed', hash: 'abcd' }] }),
      [{ name: 'listed', hash: 'abcd' }, { name: 'tagged', hash: '' }]);
check('with the hash Forge wrote for it, where it wrote one',
      resourceNames({ prompt: '<lora:tagged:0.5>', hashes: { 'lora:tagged': 'ffff00' } }),
      [{ name: 'tagged', hash: 'ffff00' }]);
const HASHED = { prompt: 'a, <lora:tagged:0.5>', hashes: { 'lora:tagged': 'FFFF00' } };
check('a tag with a hash in the image details: found by that hash, as a resource is',
      collectResourceChips(HASHED, { versions: {}, hashes: { ffff00: { version_id: 7, file_stem: 'local_name', file_type: 'LORA' } } })
          .chips.map((c) => [c.name, c.installed, c.weight]), [['local_name', true, 0.5]]);
check('and missing, it keeps the hash, for Civitai to say which it is and a download',
      collectResourceChips(HASHED, { versions: {}, hashes: {} }).chips.map((c) => [c.name, c.installed, c.hash]),
      [['tagged', false, 'ffff00']]);
const EMBEDDINGS = { versions: {}, hashes: {}, names: {},
                     embeddings: [{ version_id: 5, file_stem: 'easynegative', file_type: 'TextualInversion' }] };
check('a library embedding named only in the prompt, as a word: a chip, where the image had it',
      collectResourceChips({ negativePrompt: 'blurry, EasyNegative' }, EMBEDDINGS).chips
          .map((c) => [c.name, c.installed, c.where]), [['easynegative', true, 'negative']]);
check('inside a longer word it is no embedding to Forge, and no chip',
      collectResourceChips({ negativePrompt: 'easynegatives' }, EMBEDDINGS).chips, []);
check('a tag naming the LoRA a resource lists is that resource: one chip',
      collectResourceChips(META, FILES).chips.filter((c) => c.kind === 'lora').map((c) => c.name),
      ['add_detail', 'style_locon', 'Not Here - v1']);

done();
