// The shared modules as one classic script, for the suites that run a tab's
// functions in a vm sandbox: what common.mjs was before it was split by job
// (#93). Each module's exports become plain declarations, and its imports of
// the others go - in one sandbox they are already there. In the order the
// modules need each other, so what runs at the top finds what it calls.
//
// .cjs, so the runner does not take it for a suite.
const fs = require('fs');
const path = require('path');

const SHARED = path.resolve(__dirname, '..', '..', 'javascript', 'shared');
const ORDER = ['core', 'calls', 'tabs', 'ui_options', 'nsfw', 'media', 'grid', 'gallery', 'filters', 'generations',
               'update_notice', 'notes', 'chips', 'wan', 'downloads', 'resources'];

module.exports = function sharedScript() {
    return ORDER.map((name) => fs.readFileSync(path.join(SHARED, `${name}.mjs`), 'utf8')
        .replace(/^const shared = .*\n/m, '')
        .replace(/^const \{[^}]*\} = await shared\('[^']+'\);\n/gm, '')
        .replace(/^export /gm, '')
        // Each module's start() (#182), named for it: in one script they would clash.
        .replace(/^(const|function) start\b/m, `$1 start_${name}`)).join('\n');
};
