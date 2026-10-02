/**
 * A send puts an image's LoRAs and embeddings under the prompts as chips: a
 * click puts the resource's tag in, or takes it out. Most images list their
 * LoRAs as resources without a tag in the prompt, which meant finding each
 * one by hand. The rules are here, apart from the page, so they can be tested.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml } = await shared('core.mjs');

// What Forge loads through <lora:...>, by the file's own type or Civitai's.
const LORA_TYPES = new Set(['lora', 'locon', 'loha', 'lokr', 'dora', 'lycoris', 'lycoris full']);
const EMBEDDING_TYPES = new Set(['textualinversion', 'embedding', 'embed']);

// A LoRA an image gives no weight gets this one.
export const DEFAULT_LORA_WEIGHT = 0.5;

function resourceKind(type) {
    const value = String(type || '').toLowerCase();
    if (LORA_TYPES.has(value)) return 'lora';
    if (EMBEDDING_TYPES.has(value)) return 'embedding';
    return null;
}

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** The text a chip puts in a prompt. */
export function chipTag(chip) {
    return chip.kind === 'lora' ? `<lora:${chip.name}:${chip.weight}>` : chip.name;
}

// A LoRA's tag at any weight - one edited by hand is still that LoRA's - and
// an embedding as a word of its own, not part of a longer one.
function chipPattern(chip) {
    const name = escapeRegExp(chip.name);
    return chip.kind === 'lora' ? `<lora:${name}(?::[^>]*)?>` : `(?<![\\w-])${name}(?![\\w-])`;
}

/** Whether a prompt holds a chip's resource. */
export function promptHasChip(prompt, chip) {
    return new RegExp(chipPattern(chip), 'i').test(prompt || '');
}

/**
 * A prompt with a chip's resource taken out if it is there - every copy, and
 * the comma that separated it - or put at the end if it is not.
 */
export function toggleChip(prompt, chip) {
    const text = prompt || '';
    if (!promptHasChip(text, chip)) {
        const kept = text.replace(/[\s,]+$/, '');
        return kept ? `${kept}, ${chipTag(chip)}` : chipTag(chip);
    }
    const tag = chipPattern(chip);
    return text
        .replace(new RegExp(`\\s*,\\s*${tag}`, 'gi'), '')
        .replace(new RegExp(`${tag}\\s*,?\\s*`, 'gi'), '');
}

/** A prompt with <lora:from...> tags naming the same file as <lora:to...>. */
export function renameLoraTags(prompt, from, to) {
    if (!prompt || !from || !to || from === to) return prompt;
    return prompt.replace(new RegExp(`<lora:${escapeRegExp(from)}(?=[:>])`, 'gi'), `<lora:${to}`);
}

/**
 * The chips for an image, and the LoRA tags its prompts use under a name
 * that is not the local file's.
 *
 * Its resources come twice: Civitai's list, by version id, and the
 * infotext's, by hash and under the name the prompt used. `files` is the
 * server's answer for both (/model-manager/image-resources); a resource with
 * no file there is shown, but cannot be put in. `gallery` is the file whose
 * gallery the image is in: an image often does not list the LoRA it was
 * posted to show. One chip per file, whichever list named it, with the
 * image's weight where either gives one.
 *
 * Returns { chips, renames }: a chip is { key, kind, name, weight,
 * installed, where, title, versionId, modelId, hash }, `name` being what goes
 * in the prompt - the file's stem, which Forge always knows it by. `where` is
 * the prompt the image had it in, else the positive one. versionId, modelId
 * and hash are what the image names it by, for downloading one that is not
 * installed; any may be null. renames: [{ from, to }].
 *
 * `missing` is what Civitai says of the ones the library lacks
 * (/model-manager/missing-resources), once it has answered: a missing one is
 * then named as its file will be once downloaded, so a download does not
 * rename it, and one the infotext knows only by hash is its version - one
 * chip with the same version from Civitai's list, not two. A hash Civitai
 * does not know, or a model it no longer has, is `notOnCivitai`.
 */
export function collectResourceChips(meta, files, gallery = null, missing = null) {
    const byVersion = (files && files.versions) || {};
    const byHash = (files && files.hashes) || {};
    // Found by the file's name, where no id or hash found it: see
    // resourceNames(). A chip found only so says so, under the chips.
    const byName = (files && files.names) || {};
    const chips = new Map();
    const renames = [];

    const add = ({ file, type, label, weight, versionId, modelId, hash, alias, named = false }) => {
        let notOnCivitai = false;
        let future = null;
        if (!file && missing) {
            const byHashAnswer = missing.hashes || {};
            if (!versionId && hash && Object.prototype.hasOwnProperty.call(byHashAnswer, hash)) {
                versionId = byHashAnswer[hash] || null;
                notOnCivitai = !versionId;
            }
            future = versionId ? (missing.versions || {})[String(versionId)] || null : null;
            if (future && future.gone) notOnCivitai = true;
            modelId = modelId || (future && future.model_id) || null;
        }
        const kind = resourceKind((file && file.file_type) || type || (future && future.file_type));
        if (!kind) return;
        const name = file ? file.file_stem : (future && future.file_stem) || label;
        if (!name) return;
        let key = file ? `file:${name.toLowerCase()}`
            : versionId ? `version:${versionId}` : `name:${name.toLowerCase()}`;
        // One version is one chip, whichever list found its file and
        // whichever did not: after a download the infotext's hash may not
        // lead to the file yet, while Civitai's version id does.
        const version = versionId || (file && file.version_id) || null;
        const sameVersion = !chips.has(key) && version
            && [...chips.values()].find((chip) => chip.versionId === version);
        if (sameVersion) key = sameVersion.key;
        const known = chips.get(key);
        if (known) {
            if (file && !known.installed) Object.assign(known, { installed: true, name, byName: named });
            if (file && !named) known.byName = false;
            if (known.weight === null && weight !== undefined && weight !== null) known.weight = weight;
            known.versionId = known.versionId || versionId || (file && file.version_id) || null;
            known.modelId = known.modelId || modelId || null;
            known.hash = known.hash || hash || null;
            known.notOnCivitai = known.notOnCivitai && notOnCivitai;
        } else {
            chips.set(key, { key, kind, name, weight: weight ?? null, installed: !!file,
                             aliases: new Set(), title: label || name,
                             versionId: versionId || (file && file.version_id) || null,
                             modelId: modelId || null, hash: hash || null, byName: !!file && named,
                             notOnCivitai });
        }
        if (file && alias && alias !== name) {
            chips.get(key).aliases.add(alias);
            if (kind === 'lora') renames.push({ from: alias, to: name });
        }
    };

    if (gallery && gallery.file_stem) {
        add({ file: gallery, type: gallery.file_type, label: gallery.file_stem });
    }
    for (const r of (meta && meta.civitaiResources) || []) {
        const id = r.modelVersionId;
        add({ file: id ? byVersion[String(id)] : null, type: r.type, versionId: id, modelId: r.modelId,
              label: [r.name || r.modelName, r.modelVersionName].filter(Boolean).join(' - '),
              weight: r.weight });
    }
    for (const r of (meta && meta.resources) || []) {
        const hash = String(r.hash || resourceHash(meta, r) || '').toLowerCase();
        const found = hash ? byHash[hash] : null;
        const named = !found && r.name ? byName[String(r.name).toLowerCase()] : null;
        add({ file: found || named, type: r.type, label: r.name, named: !!named,
              weight: r.weight, alias: r.name, hash: hash || null });
    }

    // A chip the infotext names by name alone - no hash, no version, no file -
    // is the same resource as another chip of its kind whose file has that
    // name, ignoring case: the file installed, or the one Civitai says the
    // other's version is. Forge's <lora:name> is the file's name, so the two
    // are one; merged, the chip keeps the weight only the infotext gave.
    for (const chip of [...chips.values()]) {
        if (chip.installed || chip.hash || chip.versionId) continue;
        const same = [...chips.values()].find((other) => other !== chip && other.kind === chip.kind
            && (other.installed || other.versionId) && other.name.toLowerCase() === chip.name.toLowerCase());
        if (!same) continue;
        if (same.weight === null) same.weight = chip.weight;
        chips.delete(chip.key);
    }

    let negative = (meta && meta.negativePrompt) || '';
    for (const { from, to } of renames) negative = renameLoraTags(negative, from, to);
    const result = [...chips.values()].map(({ aliases, ...chip }) => {
        chip.weight = chip.weight ?? (chip.kind === 'lora' ? DEFAULT_LORA_WEIGHT : null);
        const named = [chip.name, ...aliases].some((n) => promptHasChip(negative, { ...chip, name: n }));
        chip.where = named ? 'negative' : 'positive';
        return chip;
    });
    return { chips: result, renames };
}

/**
 * A resource's hash from the image's `hashes`, where its own entry has none:
 * Forge writes {"lora:Ghibli_v6": "58549cc3d3"} there and leaves the
 * resources list without them. Some write the kind in capitals - "LORA:",
 * "EMBED:", 5,561 and 35 keys in one library - so its case is ignored; the
 * name after it has to match as written.
 */
function resourceHash(meta, resource) {
    const hashes = (meta && meta.hashes) || {};
    const kind = resourceKind(resource.type);
    const prefixes = kind === 'lora' ? ['lora', 'lyco'] : kind === 'embedding' ? ['embed'] : [];
    for (const [key, hash] of Object.entries(hashes)) {
        const at = key.indexOf(':');
        if (hash && at > 0 && key.slice(at + 1) === resource.name
            && prefixes.includes(key.slice(0, at).toLowerCase())) return hash;
    }
    return '';
}

/**
 * What to ask the library to find by name: the image's LoRAs and embeddings,
 * each with the hash the image gives for it, which the file has to match.
 */
export function resourceNames(meta) {
    return ((meta && meta.resources) || [])
        .filter((r) => r.name && resourceKind(r.type))
        .map((r) => ({ name: r.name, hash: String(r.hash || resourceHash(meta, r) || '') }));
}

export function renderResource(resource) {
    const type = resource.type || 'unknown';
    const name = resource.name || 'Unknown';
    const weight = resource.weight !== undefined ? resource.weight : null;

    let typeClass = 'mm-resource-other';
    let typeLabel = type;

    if (type.toLowerCase() === 'lora') {
        typeClass = 'mm-resource-lora';
        typeLabel = 'LoRA';
    } else if (type.toLowerCase() === 'vae') {
        typeClass = 'mm-resource-vae';
        typeLabel = 'VAE';
    } else if (type.toLowerCase() === 'embedding' || type.toLowerCase() === 'ti') {
        typeClass = 'mm-resource-embed';
        typeLabel = 'Embed';
    }

    const weightStr = weight !== null ? ` (${escapeHtml(String(weight))})` : '';

    return `<span class="mm-resource ${typeClass}" title="${escapeHtml(type)}: ${escapeHtml(name)}${weightStr}">
              <span class="mm-resource-type">${escapeHtml(typeLabel)}</span>
              <span class="mm-resource-name">${escapeHtml(name)}${weightStr}</span>
            </span>`;
}
