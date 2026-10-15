// Every suite of the Generations and Civitai Images tabs, run again with the
// browser's grid (#240).
//
// Fast is the default, so the suites run on it. Classic is a setting away and
// has to keep working: each suite that mounts either tab runs again here, in
// a process of its own, with MM_TEST_GRID=Classic - ui-options says Classic
// for both grids, whatever the suite's stand-in answers (harness.mjs,
// gridLayout). The suites that switch the setting themselves are left out.
import { spawn } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OWN = new Set([basename(fileURLToPath(import.meta.url)), 'generations_grid_test.mjs', 'gallery_grid_test.mjs',
                     'tiles_placed_test.mjs']);
const suites = readdirSync(HERE)
    .filter((name) => name.endsWith('_test.mjs') && !OWN.has(name))
    .filter((name) => /tab_(generations|gallery)\.py/.test(readFileSync(join(HERE, name), 'utf8')));

function run(name) {
    return new Promise((resolve) => {
        const child = spawn(process.execPath, [join(HERE, name)], {
            cwd: HERE, env: { ...process.env, MM_TEST_GRID: 'Classic' },
        });
        let output = '';
        child.stdout.on('data', (chunk) => { output += chunk; });
        child.stderr.on('data', (chunk) => { output += chunk; });
        const timer = setTimeout(() => child.kill(), 60000);
        child.on('close', (code) => {
            clearTimeout(timer);
            resolve({ name, code, output });
        });
    });
}

// Four at a time: in a run this suite is one of the runner's twelve, and
// these come on top of them.
const results = [];
const queue = [...suites];
await Promise.all(Array.from({ length: 4 }, async () => {
    while (queue.length) results.push(await run(queue.shift()));
}));
const failed = results.filter((r) => r.code !== 0);
failed.forEach((r) => console.log(`FAIL ${r.name} with the Classic grid\n${r.output.split('\n').filter((l) => /FAIL|Error|got|want/.test(l)).slice(0, 12).join('\n')}`));
if (suites.length < 10) console.log(`FAIL only ${suites.length} suites found that mount either tab`);
console.log(failed.length || suites.length < 10 ? '' : `All checks passed: ${suites.length} suites with the Classic grid.`);
process.exit(failed.length || suites.length < 10 ? 1 : 0);
