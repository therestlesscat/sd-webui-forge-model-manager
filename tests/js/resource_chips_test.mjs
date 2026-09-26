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
        DEFAULT_LORA_WEIGHT } = await import(`file:///${ROOT}/javascript/shared/common.mjs`);

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

done();
