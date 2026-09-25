// What a Wan text-to-video send asks Forge for.
//
// Send to txt2img treated a video as a still: Forge Neo reads Batch size as
// Frames on the Wan preset, the paste never set it, and the preset's saved
// value - 1 by default - made a single frame. Civitai keeps neither a video's
// length nor its frame rate, so the frames come from the video's own
// duration at Wan's 16 a second, and the size from its own, in Wan's steps.
import { ROOT, checker } from './harness.mjs';

const { check, done } = checker();
const { videoFrames, videoSize, WAN_FPS, WAN_MAX_FRAMES } =
    await import(`file:///${ROOT}/javascript/shared/common.mjs`);

check('Wan makes 16 frames a second', WAN_FPS, 16);
check('and Neo\'s Frames slider stops at 241', WAN_MAX_FRAMES, 241);

check('Wan\'s usual 81 frames, played at 16 a second, are 81 frames', videoFrames(81 / 16), 81);
check('a five-second video is 81, the nearest 4n + 1', videoFrames(5), 81);
check('the same five seconds interpolated to 32 fps is still 81', videoFrames(160 / 32), 81);
check('every answer is 4n + 1',
      [0.3, 1, 2.2, 3.7, 7.9, 12.5].every((s) => (videoFrames(s) - 1) % 4 === 0), true);
check('a very short video is one frame, never zero', videoFrames(0.01), 1);
check('a long one stops where the slider does', videoFrames(60), 241);
check('an unknown length is null, not a guess',
      [videoFrames(NaN), videoFrames(Infinity), videoFrames(0), videoFrames(undefined)],
      [null, null, null, null]);

check('a size Wan can make is kept', videoSize(832, 480), { width: 832, height: 480 });
check('any other goes to the nearest 16', videoSize(1080, 1920), { width: 1088, height: 1920 });
check('never below 16', videoSize(3, 5), { width: 16, height: 16 });

done();
