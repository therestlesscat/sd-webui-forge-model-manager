/**
 * How explicit an image is, as the server judged it (nsfw.py): its level, its
 * badge, whether a work-safe view shows it, and the levels one can give an
 * image of one's own.
 */

/**
 * How explicit an image is, on Civitai's scale:
 *   PG 1 · PG-13 2 · R 4 · X 8 · XXX 16 · Blocked 32 · Unknown 64
 * The judging is the server's (nsfw.py); the page reads what it sends.
 */
export const NSFW_UNKNOWN = 64;
export const NSFW_SFW_MAX = 3;  // PG | PG-13

/**
 * How explicit an image is - as the server judged it. Every image the page
 * shows comes through the server, which stamps mm_level on it (stamp_levels()
 * in nsfw.py). The page used to judge for itself, with a copy of the rule and
 * the words fetched to feed it. An image without a stamp is Unknown - so
 * hidden where anything unsafe is - rather than judged here on less.
 */
export function nsfwImageLevel(image) {
    return typeof image?.mm_level === 'number' ? image.mm_level : NSFW_UNKNOWN;
}

/**
 * The NSFW badge's text for an image: "X · prompt" when its prompt is what
 * made it NSFW, so an image hidden or badged against its rating says why;
 * otherwise the rating label the gallery would show.
 */
export function nsfwBadgeLabel(image, ratingLabel) {
    return image?.mm_level_from_prompt ? 'X · prompt' : ratingLabel;
}

// The lowest level a Civitai image's card badges: what the work-safe view
// lets through (PG, PG-13) goes unmarked.
const NSFW_BADGE_MIN = 4;   // R

/**
 * The badge on a Civitai image's card, or '' for none: its level as the
 * server judged it (mm_level), from R up. Both galleries once badged
 * Civitai's own `nsfw` field, which on most images is a boolean - 64,903 of
 * one library's 95,810 showed "true", whatever their rating, and the 34,744
 * with false showed nothing.
 */
export function nsfwBadge(image) {
    const level = nsfwImageLevel(image);
    if (level < NSFW_BADGE_MIN || level >= NSFW_UNKNOWN) return '';
    const named = [...RATING_LEVELS, [32, 'Blocked']].filter(([value]) => value <= level).pop();
    return nsfwBadgeLabel(image, named[1]);
}

/** Is this image safe for a work-safe view? */
export function isImageSafe(image) {
    return nsfwImageLevel(image) <= NSFW_SFW_MAX;
}

// The NSFW levels one can give an image of one's own, as nsfw.USER_LEVELS on
// the server, which checks them: [value, name].
export const RATING_LEVELS = [[1, 'PG'], [2, 'PG-13'], [4, 'R'], [8, 'X'], [16, 'XXX']];
