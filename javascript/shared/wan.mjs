/**
 * A video as Wan makes it - its frames - for the Model Manager's Send of a
 * video. Its size as Wan makes it is the server's (send.video_size, #302).
 */

// Wan generates at 16 frames a second, and Forge Neo's Frames slider stops at
// fifteen seconds of them (modules_forge/presets.py).
export const WAN_FPS = 16;
export const WAN_MAX_FRAMES = WAN_FPS * 15 + 1;

/**
 * How many frames Wan needs for a video this many seconds long, or null if
 * the length is unknown. By length rather than by frame count: an uploader
 * who interpolated to 32 frames a second kept the length, not the count.
 * Wan's latent packs four frames to one after the first, so it takes 4n + 1
 * and would round anything else itself (processing.py).
 */
export function videoFrames(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return null;
    const frames = 4 * Math.round((seconds * WAN_FPS - 1) / 4) + 1;
    return Math.min(Math.max(frames, 1), WAN_MAX_FRAMES);
}
