// The browser suites' harness itself (harness.mjs): a wait may ask for no
// more than MAX_WAIT_TRIES. Seven waits once asked for 4,000-6,000 tries, up
// to 300 s each, and a broken one held a run for minutes before it said
// anything (#145). Two made-up suites, run as the runner runs one.
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import * as harness from './harness.mjs';

const { ROOT, checker } = harness;
const { check, done } = checker();
// Read by name, so a harness without it fails the checks, not the import.
const MAX_WAIT_TRIES = harness.MAX_WAIT_TRIES ?? 400;
const WORK = `${ROOT}/tests/work/harness_test`;
rmSync(WORK, { recursive: true, force: true });
mkdirSync(WORK, { recursive: true });

// A suite with one wait, which waits for something there from the start.
function suite(tries) {
    const path = `${WORK}/wait_${tries}.mjs`;
    writeFileSync(path, `import { checker } from 'file:///${ROOT}/tests/js/harness.mjs';\n`
        + 'const { waitFor, done } = checker();\n'
        + `await waitFor('the page', () => true, ${tries});\n`
        + 'done();\n');
    const started = Date.now();
    try {
        const said = execFileSync(process.execPath, [path], { encoding: 'utf8' });
        return { failed: false, said, seconds: (Date.now() - started) / 1000 };
    } catch (e) {
        return { failed: true, said: String(e.stdout), seconds: (Date.now() - started) / 1000 };
    }
}

const long = suite(5000);
check('a wait asking for 5,000 tries fails its suite, naming it',
      [long.failed, long.said.includes(`waits for the page: 5000 tries is more than ${MAX_WAIT_TRIES}`)],
      [true, true]);
check('and at once, not after 250 seconds', long.seconds < 10, true);
check(`a wait asking for ${MAX_WAIT_TRIES} is allowed`, suite(MAX_WAIT_TRIES).failed, false);

// A wait looks often (#271): at one look every 50 ms, a wait slept out the
// rest of it once the page was ready - 32 s summed over the suites. Its
// budget is still counted in tries of 50 ms, and never got shorter.
const probe = checker();
let looks = 0;
let ready = false;
setTimeout(() => { ready = true; }, 200);
await probe.waitFor('the page', () => { looks += 1; return ready; });
check('a wait for something that comes true after 200 ms looks at least 8 times meanwhile', looks >= 8, true);
const started = Date.now();
await probe.waitFor('nothing', () => false, 2);
check('a wait of 2 tries that never comes true lasts at least 100 ms, 2 tries of 50 ms',
      Date.now() - started >= 100, true);
check('   and then fails, naming what it waited for', probe.fails.at(-1)?.includes('timed out waiting for nothing'), true);
// A promise is true: a condition that awaits passed at once, whatever it
// would have answered. generations_grid_test's loaded() was one, unused.
const failed = probe.fails.length;
await probe.waitFor('the tiles', async () => false);
check('a wait whose condition answers with a promise fails, naming the wait',
      probe.fails.length === failed + 1 && probe.fails.at(-1).includes('the tiles'), true);

// The stand-in page starts at the top, as a browser's does (#271). Without
// a position, a gallery going back to its top worked out NaN, asked for a
// scroll, and waited out the half second for one that never came.
const { window, document } = harness.mountTab('model_manager/ui/tab_model_manager.py');
check('the stand-in page is scrolled to 0, as a browser\'s starts', [window.scrollY, window.pageYOffset], [0, 0]);
const { scrollToImagesTop } = await harness.sharedModule('gallery.mjs');
const gallery = document.createElement('div');
gallery.id = 'harness_test_gallery';
gallery.innerHTML = '<div class="model-images-list"></div>';
document.body.appendChild(gallery);
const asked = Date.now();
await scrollToImagesTop('harness_test_gallery');
check('so a gallery already at the top goes back to it at once, not after half a second',
      Date.now() - asked < 100, true);

rmSync(WORK, { recursive: true, force: true });
done();
