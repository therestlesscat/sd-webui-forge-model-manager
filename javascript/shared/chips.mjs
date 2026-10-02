/**
 * A send puts an image's LoRAs and embeddings under the prompts as chips: a
 * click puts the resource's tag in, or takes it out. Most images list their
 * LoRAs as resources without a tag in the prompt, which meant finding each
 * one by hand. The rules come first, apart from the page, so they can be
 * tested; then which local files and Civitai versions an image's resources
 * are, from resources.mjs, which the Resources dialog uses too - and the chips
 * on the page.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { apiCall, escapeHtml } = await shared('core.mjs');
const {
    resolveResourceHashes, knownHashes, imageResourceHashes, resourceDownloads, downloadResource,
} = await shared('resources.mjs');

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


// ------------------------------------------------------------ resource chips
// A send puts the image's LoRAs and embeddings under the target tab's
// negative prompt as chips; a click puts a resource's tag in, or takes it
// out. The rules are collectResourceChips() and toggleChip(), above.

// Per tab, the chips the last send left there, the row that shows them, and
// the image and model they came from - a download from the Resources dialog
// looks them up again.
const resourceChips = {};

const resourceChipRows = {};

export const resourceChipSources = {};

// Per tab, the send whose missing resources Civitai is being asked about:
// until it answers, the row shows what the library has and says it is
// looking for the rest.
const resourceChipsPending = {};

/**
 * What a chip for a resource not in the library says: that it is missing and
 * a click downloads it, or how the download is going. A download is shared
 * with the Resources dialog, by the version id the image names.
 *
 * The chip itself shows only its mark and a fill for a download's progress;
 * the words (`note`) go on the line under the chips, unless `quiet` - a chip
 * merely missing is said by its mark and the key. A download used to write
 * its progress on the chip - "missing LoRA, click to download", "queued",
 * "5%", "37%", "adding to library..." - and each change resized it, moving
 * the chips after it, and a click meant for one landed on another.
 */
function missingChipState(chip) {
    const what = chip.kind === 'lora' ? 'LoRA' : 'embedding';
    if (!chip.versionId && !chip.hash) {
        return { busy: true, unavailable: true, note: 'no hash recorded',
                 title: `${chip.title}: the image names it without a hash or a version, so it cannot be found` };
    }
    const job = chip.versionId ? resourceDownloads[chip.versionId] : chip.lookup;
    if (chip.notOnCivitai && !job) {
        return { busy: true, unavailable: true, note: 'not on Civitai',
                 title: `${chip.title}: Civitai does not have it` };
    }
    if (job && job.state === 'checking') {
        return { busy: true, mark: CHIP_MARKS.busy, note: 'checking Civitai...',
                 title: `Asking Civitai what ${chip.title} is` };
    }
    if (job && job.state === 'unavailable') {
        return { busy: true, unavailable: true, note: 'not on Civitai',
                 title: `${chip.title}: ${job.error || 'Civitai does not have it'}` };
    }
    if (job && job.state === 'downloading') {
        const percent = job.finishing ? 100 : Number(job.percent) || 0;
        return { busy: true, mark: job.finishing || !percent ? CHIP_MARKS.busy : CHIP_MARKS.download,
                 progress: percent,
                 note: job.finishing ? 'adding to library...' : job.paused ? `paused, ${percent}%`
                     : percent ? `downloading, ${job.percent}%` : 'queued',
                 title: `Downloading the missing ${what} ${chip.title}` };
    }
    if (job && job.state === 'installed' && job.substituted) {
        return { busy: true, mark: CHIP_MARKS.have, note: `got ${job.versionName || 'a newer version'} instead`,
                 title: `The image's version of ${chip.title} is gone from Civitai; the newest was downloaded` };
    }
    if (job && job.state === 'error') {
        // Why, in words - it was only in the tooltip - cut short; the
        // tooltip keeps all of it.
        const why = String(job.error || '');
        const short = why.length > CHIP_REASON_LENGTH ? `${why.slice(0, CHIP_REASON_LENGTH)}...` : why;
        return { busy: false, mark: CHIP_MARKS.failed, note: `download failed${short ? `: ${short}` : ''}, click to retry`,
                 title: `${chip.title}: ${why || 'the download failed'}` };
    }
    return { busy: false, quiet: true, note: `missing ${what}, click to download`,
             title: `${chip.title} is not in the library: click to download it` };
}

/** Redraw every tab's chips, to show a download's progress. */
export function redrawResourceChips() {
    for (const tab of Object.keys(resourceChips)) {
        if (resourceChips[tab]) showResourceChips(tab, resourceChips[tab]);
    }
}

/**
 * Download a chip's missing resource, as the Resources dialog would. A chip
 * from the infotext's list knows only a hash: that is looked up first.
 */
async function downloadChip(chip) {
    if (!chip.versionId && chip.hash) {
        chip.lookup = { state: 'downloading', percent: 0 };
        redrawResourceChips();
        const answer = (await resolveResourceHashes([chip.hash]))[chip.hash];
        chip.versionId = (answer && answer.version_id) || null;
        chip.modelId = chip.modelId || (answer && answer.model_id) || null;
        chip.lookup = chip.versionId ? null
            : answer ? { state: 'unavailable', error: 'Civitai does not know this file' }
            : { state: 'error', error: 'Civitai could not be asked' };
    }
    if (!chip.versionId) {
        chip.lookup = chip.lookup || { state: 'error', error: 'the image does not say which version it is' };
        redrawResourceChips();
        return;
    }
    await downloadResource(chip.versionId, chip.modelId);
}

/**
 * Find out which of a tab's missing chips can be downloaded at all. One the
 * image names by version id can; one it names only by hash is asked about,
 * as the Resources dialog asks - and a hash Civitai has never heard of is a
 * file that cannot be downloaded, which the chip should say before a click
 * rather than after it.
 */
async function checkMissingChips(tab) {
    const waiting = (resourceChips[tab] || [])
        .filter((c) => !c.installed && !c.versionId && c.hash && !c.notOnCivitai);
    if (!waiting.length) return;
    const settle = (answers) => {
        for (const chip of waiting) {
            if (!Object.prototype.hasOwnProperty.call(answers, chip.hash)) continue;
            const answer = answers[chip.hash];
            chip.versionId = (answer && answer.version_id) || null;
            chip.modelId = chip.modelId || (answer && answer.model_id) || null;
            chip.lookup = chip.versionId ? null
                : { state: 'unavailable', error: 'Civitai does not know this file' };
        }
        redrawResourceChips();
    };
    for (const chip of waiting) chip.lookup = { state: 'checking' };
    settle(knownHashes);
    const unasked = waiting.filter((c) => c.lookup && c.lookup.state === 'checking').map((c) => c.hash);
    if (!unasked.length) return;
    redrawResourceChips();
    const resolved = await resolveResourceHashes([...new Set(unasked)], (partial) => settle(partial));
    Object.assign(knownHashes, resolved);
    settle(resolved);
    for (const chip of waiting) {
        if (chip.lookup && chip.lookup.state === 'checking') {
            chip.lookup = { state: 'error', error: 'Civitai could not be asked' };
        }
    }
    redrawResourceChips();
}

/** A chip's place in its row, kept through a download: its version, else its key. */
const chipIdentity = (chip) => (chip.versionId ? `version:${chip.versionId}` : chip.key);

/**
 * A send's chips in the order they stay in: what the library has first, then
 * what it lacks - so the missing ones, arriving later, never move the rest -
 * fixed the first time, so a download leaves its chip where it was.
 */
export function arrangeChips(chips, source) {
    if (!source.order) {
        source.order = [...chips.filter((c) => c.installed), ...chips.filter((c) => !c.installed)]
            .map(chipIdentity);
    }
    const place = (chip) => {
        const at = source.order.indexOf(chipIdentity(chip));
        return at < 0 ? source.order.length : at;
    };
    return [...chips].sort((a, b) => place(a) - place(b));
}

/**
 * After a send, ask - without the send waiting - what the missing resources'
 * files will be called, and draw them once the answer is in: named as a
 * download names them, so a download renames and resizes nothing. Until then
 * the row shows the chips the library has, and says it is looking. A later
 * send, or Clear, drops the answer. With no answer at all the missing chips
 * are drawn as they were before, by Civitai's titles.
 */
export async function lookUpMissingChips(tab) {
    const source = resourceChipSources[tab];
    const chips = resourceChips[tab] || [];
    const lacking = chips.filter((c) => !c.installed);
    if (!source || !lacking.length) return;
    resourceChipsPending[tab] = source;
    showResourceChips(tab, chips);
    const versions = lacking.filter((c) => c.versionId)
        .map((c) => ({ version_id: c.versionId, model_id: c.modelId || null }));
    const hashes = [...new Set(lacking.filter((c) => !c.versionId && c.hash).map((c) => c.hash))];
    let answer = null;
    try {
        const response = await fetch('/model-manager/missing-resources', {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ versions: JSON.stringify(versions), hashes: hashes.join(',') }) });
        const data = await response.json();
        if (data && data.success) answer = data;
    } catch (error) {
        console.warn('[ModelManager] Could not ask what the missing resources are:', error);
    }
    if (resourceChipSources[tab] !== source || resourceChipsPending[tab] !== source) return;
    delete resourceChipsPending[tab];
    if (!resourceChips[tab]) return;                 // cleared meanwhile
    if (!answer) {
        showResourceChips(tab, arrangeChips(chips, source));
        checkMissingChips(tab);
        return;
    }
    source.missing = answer;
    const { chips: named } = collectResourceChips(source.img.meta, source.files, source.gallery, answer);
    // A chip known by hash alone now has its version: the order is fixed anew,
    // the library's chips first as they are shown.
    source.order = null;
    showResourceChips(tab, arrangeChips(named, source));
    // A hash the answer leaves out could not be asked about: asked as before.
    checkMissingChips(tab);
}

/** Look each tab's chips up again, after a download. */
export async function refreshResourceChips() {
    for (const [tab, source] of Object.entries(resourceChipSources)) {
        if (!resourceChips[tab] || resourceChipsPending[tab]) continue;
        source.files = await fetchImageFiles(source.img);
        const { chips } = collectResourceChips(source.img.meta, source.files, source.gallery, source.missing);
        showResourceChips(tab, arrangeChips(chips, source));
        checkMissingChips(tab);
    }
}

/** The local file of each of an image's resources, from the library alone. */
export async function fetchImageFiles(img) {
    const none = { versions: {}, hashes: {} };
    const ids = ((img.meta || {}).civitaiResources || []).map((r) => r.modelVersionId).filter(Boolean);
    const named = resourceNames(img.meta);
    // The resources' own hashes, and those the image keeps apart from them.
    const hashes = [...new Set([...imageResourceHashes(img),
                                ...named.map((n) => n.hash.toLowerCase()).filter(Boolean)])];
    if (!ids.length && !hashes.length && !named.length) return none;
    try {
        const data = await apiCall({ endpoint: '/model-manager/image-resources',
                                     params: { version_ids: ids.join(','), hashes: hashes.join(','),
                                               names: named.length ? JSON.stringify(named) : '' } });
        return data && data.success ? data : none;
    } catch (error) {
        console.warn('[ModelManager] Could not look up the image\'s resources:', error);
        return none;
    }
}

function promptBoxes(tab) {
    return { positive: gradioApp().querySelector(`#${tab}_prompt textarea`),
             negative: gradioApp().querySelector(`#${tab}_neg_prompt textarea`) };
}

// A failed download's reason is shown on its chip up to this many characters.
const CHIP_REASON_LENGTH = 60;

// Each chip's mark, beside its colour: whether it is here, can be
// downloaded, or cannot - so it reads without telling the colours apart -
// and, while a download is under way or has failed, how it is going.
const CHIP_MARKS = { have: '✓', download: '↓', unavailable: '⊘', busy: '…', failed: '!' };

export function showResourceChips(tab, chips) {
    resourceChips[tab] = chips && chips.length ? chips : null;
    const row = resourceChipRows[tab];
    if (!resourceChips[tab]) {
        row?.remove();
        return;
    }
    const element = row || document.createElement('div');
    resourceChipRows[tab] = element;
    element.id = `mm_resource_chips_${tab}`;
    element.className = 'mm-resource-chips';
    const pending = !!resourceChipsPending[tab];
    const chipsHtml = resourceChips[tab].map((chip, index) => {
        if (pending && !chip.installed) return '';
        const notes = [chip.kind === 'lora' ? `weight ${chip.weight}` : 'embedding',
                       chip.where === 'negative' ? 'negative prompt' : ''].filter(Boolean);
        const missing = chip.installed ? null : missingChipState(chip);
        const title = missing ? missing.title : `${chip.title} (${notes.join(', ')})`;
        // Whether it can be used is said by colour and a mark; whether a
        // prompt holds it, by filled or outlined (updateResourceChipStates).
        const state = !missing ? 'have' : missing.unavailable ? 'unavailable' : 'download';
        const classes = missing ? (missing.unavailable ? ' missing unavailable' : ' missing') : '';
        // A download's progress fills the chip, rather than widening it.
        const progress = missing && missing.progress !== undefined
            ? ` data-progress style="--mm-chip-progress: ${Math.max(0, Math.min(100, Number(missing.progress)))}%"` : '';
        return `<button type="button" class="mm-resource-chip${classes}" data-state="${state}"
                        data-chip="${index}" ${missing && missing.busy ? 'disabled' : ''}${progress}
                        title="${escapeHtml(title)}">`
             + `<span class="mm-resource-chip-mark" aria-hidden="true">${missing?.mark || CHIP_MARKS[state]}</span>`
             + `<span class="mm-resource-chip-name">${escapeHtml(chip.name)}</span>`
             + '</button>';
    }).join('');
    // What each missing chip is doing, in words, on a line of its own under
    // the chips: it can grow and shrink without moving one of them.
    const statuses = pending ? '' : resourceChips[tab].map((chip, index) => {
        const missing = chip.installed ? null : missingChipState(chip);
        if (!missing || missing.quiet) return '';
        return `<span class="mm-resource-chip-status" data-status-chip="${index}"
                      data-state="${missing.unavailable ? 'unavailable' : 'download'}"><b>${escapeHtml(chip.name)}</b>: `
             + `${escapeHtml(missing.note)}</span>`;
    }).join('');
    element.innerHTML = chipsHtml
        + (pending ? '<span class="mm-resource-chips-loading">Loading missing resources...</span>' : '')
        + '<button type="button" class="mm-btn secondary mm-btn-small" data-chips-clear>Clear</button>'
        + (statuses ? `<div class="mm-resource-chips-status">${statuses}</div>` : '')
        + '<div class="mm-resource-chips-key">'
        + `<span data-state="have">${CHIP_MARKS.have} in library</span>`
        + `<span data-state="download">${CHIP_MARKS.download} click to download</span>`
        + `<span data-state="unavailable">${CHIP_MARKS.unavailable} not available</span>`
        + '<span>filled: in the prompt</span>'
        + (resourceChips[tab].some((chip) => chip.installed && chip.byName)
            ? '<span class="mm-resource-chips-note">Some LoRAs and embeddings are matched by name, not by hash.</span>'
            : '')
        + '</div>';
    if (!row) element.addEventListener('click', (event) => onResourceChipClick(tab, event));
    keepResourceChips();
}

function onResourceChipClick(tab, event) {
    if (event.target.closest('[data-chips-clear]')) {
        delete resourceChipsPending[tab];
        showResourceChips(tab, null);
        return;
    }
    const button = event.target.closest('[data-chip]');
    const chip = button && !button.disabled && resourceChips[tab]?.[Number(button.dataset.chip)];
    if (!chip) return;
    if (!chip.installed) {
        downloadChip(chip);
        return;
    }
    // Out of whichever prompt has it - it may have been moved by hand -
    // else into the one the image had it in.
    const { positive, negative } = promptBoxes(tab);
    const box = promptHasChip(positive?.value, chip) ? positive
        : promptHasChip(negative?.value, chip) ? negative
        : chip.where === 'negative' ? negative : positive;
    if (!box) return;
    box.value = toggleChip(box.value, chip);
    box.dispatchEvent(new Event('input', { bubbles: true }));
    updateResourceChipStates(tab);
}

/** Light each chip whose resource either prompt holds. */
export function updateResourceChipStates(tab) {
    const row = resourceChipRows[tab];
    const chips = resourceChips[tab];
    if (!row || !chips) return;
    const { positive, negative } = promptBoxes(tab);
    row.querySelectorAll('[data-chip]').forEach((button) => {
        const chip = chips[Number(button.dataset.chip)];
        const held = promptHasChip(positive?.value, chip) || promptHasChip(negative?.value, chip);
        button.classList.toggle('active', !!held);
    });
}

/**
 * Keep each tab's chips under its negative prompt, and lit to match. Run
 * after every UI update: Gradio can re-render the prompt column, and a paste
 * changes the prompts without an input event.
 */
function keepResourceChips() {
    for (const tab of Object.keys(resourceChips)) {
        if (!resourceChips[tab]) continue;
        const anchor = gradioApp().querySelector(`#${tab}_neg_prompt_row`);
        const row = resourceChipRows[tab];
        if (anchor && row && anchor.nextElementSibling !== row) anchor.after(row);
        for (const box of Object.values(promptBoxes(tab))) {
            if (box && !box.dataset.mmChipsWatched) {
                box.dataset.mmChipsWatched = '1';
                box.addEventListener('input', () => updateResourceChipStates(tab));
            }
        }
        updateResourceChipStates(tab);
    }
}

if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(keepResourceChips);

// The Resources dialog's downloads (resources.mjs): each step redraws the
// chips, and one in the library has them look again.
if (typeof window !== 'undefined') {
    window.addEventListener?.('mm-resource-downloads', (event) => {
        if (event.detail?.installed) refreshResourceChips();
        else redrawResourceChips();
    });
}
