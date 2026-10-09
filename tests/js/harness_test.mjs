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

rmSync(WORK, { recursive: true, force: true });
done();
