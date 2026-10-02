/**
 * Forge's samplers and schedulers, from the page's one ui-options answer, and
 * an image's sampler text read by them: "Euler a Karras" is the sampler
 * "Euler a" and the scheduler "Karras" (#88). Send sets Forge up with it, and
 * an image's card shows it - the same reading in every tab. The Civitai
 * Browser once kept a copy that looked for six schedulers anywhere in the
 * text, and read some images differently.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { uiOptions } = await shared('ui_options.mjs');

// Cache for samplers and schedulers loaded from API
let cachedSamplers = null;

let cachedSchedulers = null;

// Load samplers and schedulers from API (called once on init): the page's one
// ui-options answer (ui_options.mjs), which is null if it could not be had.
async function loadUIOptionsFromAPI() {
    try {
        const data = await uiOptions();
        if (!data) throw new Error('ui-options did not answer');

        if (data.success) {
            if (data.schedulers) {
                cachedSchedulers = data.schedulers.filter(s => s && s !== 'Automatic');
                console.log('[ModelManager] Loaded schedulers from API:', cachedSchedulers);
            }
            if (data.samplers) {
                cachedSamplers = data.samplers;
                console.log('[ModelManager] Loaded samplers from API:', cachedSamplers);
            }
        }
    } catch (error) {
        console.error('[ModelManager] Failed to load UI options:', error);
        cachedSchedulers = [];
        cachedSamplers = [];
    }
}

// Get scheduler options (from cache)
function getSchedulerOptions() {
    if (cachedSchedulers === null) {
        console.log('[ModelManager] Schedulers not loaded yet');
        return [];
    }
    return cachedSchedulers;
}

// Get sampler options (from cache)
function getSamplerOptions() {
    if (cachedSamplers === null) {
        console.log('[ModelManager] Samplers not loaded yet');
        return [];
    }
    return cachedSamplers;
}

// Normalize string for comparison (lowercase, remove special chars, collapse spaces)
function normalizeForMatch(str) {
    if (!str) return '';
    return str.toLowerCase()
        .replace(/[_\-+]/g, ' ')  // Replace underscores, dashes, plus with space
        .replace(/\s+/g, ' ')      // Collapse multiple spaces
        .trim();
}

// Match sampler name from metadata to known sampler
// Handles variations like "Euler_Max" -> "Euler Max", case differences, etc.
function matchSamplerName(samplerName) {
    if (!samplerName) return samplerName;

    const samplers = getSamplerOptions();
    if (!samplers.length) return samplerName;

    // Try exact match first
    if (samplers.includes(samplerName)) {
        return samplerName;
    }

    // Normalize and match
    const normalizedInput = normalizeForMatch(samplerName);
    for (const sampler of samplers) {
        if (normalizeForMatch(sampler) === normalizedInput) {
            console.log('[ModelManager] Matched sampler:', samplerName, '->', sampler);
            return sampler;
        }
    }

    // Try partial match (input might have scheduler appended)
    for (const sampler of samplers) {
        if (normalizedInput.startsWith(normalizeForMatch(sampler) + ' ')) {
            console.log('[ModelManager] Partial sampler match:', samplerName, '-> starts with', sampler);
            // Don't return here - let splitSamplerScheduler handle it
            break;
        }
    }

    // Return original with basic normalization (underscore -> space)
    return samplerName.replace(/_/g, ' ');
}

// Load UI options on init
if (typeof window !== 'undefined') loadUIOptionsFromAPI();

// Split combined "Sampler Scheduler" format into separate parts
// e.g., "Euler a Karras" -> { sampler: "Euler a", scheduler: "Karras" }
// Also handles variations like "Euler_a_Karras"
export function splitSamplerScheduler(samplerString) {
    if (!samplerString) return { sampler: null, scheduler: null };

    // Normalize underscores to spaces for matching
    const normalized = samplerString.replace(/_/g, ' ');

    const schedulers = getSchedulerOptions();

    // Check if the normalized string ends with a known scheduler
    for (const scheduler of schedulers) {
        // Check both exact and case-insensitive
        if (normalized.endsWith(' ' + scheduler) ||
            normalized.toLowerCase().endsWith(' ' + scheduler.toLowerCase())) {
            const sampler = normalized.slice(0, -(scheduler.length + 1));
            // Match the sampler to known samplers
            const matchedSampler = matchSamplerName(sampler);
            console.log('[ModelManager] Split sampler+scheduler:', samplerString, '->', matchedSampler, '+', scheduler);
            return { sampler: matchedSampler, scheduler };
        }
    }

    // No scheduler suffix found - just match the sampler
    const matchedSampler = matchSamplerName(normalized);
    return { sampler: matchedSampler, scheduler: null };
}
