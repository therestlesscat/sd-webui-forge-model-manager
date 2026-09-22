// vaeFromMeta: every spelling Civitai uses for a VAE, and every placeholder
// that only looks like one. Counts come from 67,458 stored images.
const fs = require('fs');
const vm = require('vm');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');
const src = fs.readFileSync(REPO + '/javascript/model_manager.mjs', 'utf8');

const sb = {};
vm.createContext(sb);

function lift(name) {
    const m = src.match(new RegExp('^(?:export )?function ' + name + '\\s*\\(', 'm'));
    if (!m) throw new Error('not found: ' + name);
    let i = src.indexOf('(', m.index + m[0].length - 1), depth = 0;
    for (;; i++) { if (src[i] === '(') depth++; else if (src[i] === ')' && --depth === 0) break; }
    i = src.indexOf('{', i);
    const start = i;
    depth = 0;
    for (;; i++) { if (src[i] === '{') depth++; else if (src[i] === '}' && --depth === 0) break; }
    return vm.runInContext('(function' + src.slice(src.indexOf('(', m.index), start)
        + src.slice(start, i + 1) + ')', sb);
}

sb.isVaeFileName = lift('isVaeFileName');
const vaeFromMeta = lift('vaeFromMeta');

let failures = 0;
const check = (label, got, want) => {
    if (got !== want) {
        failures++;
        console.log('FAIL ' + label + '\n  got  ' + JSON.stringify(got) + '\n  want ' + JSON.stringify(want));
    }
};

// --- the spellings that name a real file ------------------------------------
check('VAE, the usual field (11,304 images)',
      vaeFromMeta({ VAE: 'blessed2.vae' }), 'blessed2.vae');
check('vaes, a ComfyUI list (2,392 images, none of which have VAE)',
      vaeFromMeta({ vaes: ['qwen_image_vae.safetensors'] }), 'qwen_image_vae.safetensors');
check('vaes, the reported Qwen image',
      vaeFromMeta({ vaes: ['qwen_image_vae.safetensors'], prompt: { 5: { class_type: 'VAELoader' } } }),
      'qwen_image_vae.safetensors');
check('vae, lowercase', vaeFromMeta({ vae: 'aaaAnimeSDXLVAE_v15' }), 'aaaAnimeSDXLVAE_v15');
check('vae_name, a real one', vaeFromMeta({ vae_name: 'sdxl_vae.safetensors' }), 'sdxl_vae.safetensors');
check('resources, the existing path',
      vaeFromMeta({ resources: [{ type: 'vae', name: 'x.safetensors' }] }), 'x.safetensors');

// --- placeholders that mean "the checkpoint's own" --------------------------
check('Default (model), 131 images', vaeFromMeta({ VAE: 'Default (model)' }), null);
check('Default, 14 images', vaeFromMeta({ VAE: 'Default' }), null);
check('Baked VAE, 5 images', vaeFromMeta({ VAE: 'Baked VAE' }), null);
check('Baked VAE under Vae', vaeFromMeta({ Vae: 'Baked VAE' }), null);
check('automatic, 30 images', vaeFromMeta({ vae_name: 'automatic' }), null);
check('None', vaeFromMeta({ VAE: 'None' }), null);
check('a placeholder inside the list', vaeFromMeta({ vaes: ['automatic'] }), null);

// --- not a name -------------------------------------------------------------
check('VAE hash alone is not a name', vaeFromMeta({ 'VAE hash': '235745af8d' }), null);
check('empty meta', vaeFromMeta({}), null);
check('no meta at all', vaeFromMeta(null), null);
check('empty list', vaeFromMeta({ vaes: [] }), null);
check('blank string', vaeFromMeta({ VAE: '   ' }), null);
check('ADetailer fields are not the main VAE',
      vaeFromMeta({ 'ADetailer VAE': 'vae-ft-mse-840000-ema-pruned.ckpt' }), null);

// --- precedence -------------------------------------------------------------
check('VAE outranks the list',
      vaeFromMeta({ VAE: 'a.safetensors', vaes: ['b.safetensors'] }), 'a.safetensors');
check('a placeholder in VAE falls through to the list',
      vaeFromMeta({ VAE: 'Default', vaes: ['b.safetensors'] }), 'b.safetensors');
check('surrounding whitespace is trimmed',
      vaeFromMeta({ VAE: '  c.safetensors  ' }), 'c.safetensors');

console.log(failures === 0 ? 'All checks passed.' : failures + ' check(s) failed.');
process.exit(failures ? 1 : 0);
