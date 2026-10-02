// Your generations, as a model's gallery and the Generations tab both show
// them (#89). The two keep different things - a card per generation, tiles at
// three levels - but did four of the same jobs in copies of their own: the
// thumbnail, the rating request, the request deleting one image or one
// generation, and a shift-click's range. Each is written once now, in
// shared/generations.mjs, and both tabs use it.
import { readdirSync, readFileSync } from 'node:fs';
import { ROOT, checker, mountTab } from './harness.mjs';

mountTab('model_manager/ui/tab_generations.py');
const { check, done } = checker();
const files = [...readdirSync(`${ROOT}/javascript`).filter((f) => f.endsWith('.mjs')),
               ...readdirSync(`${ROOT}/javascript/shared`).filter((f) => f.endsWith('.mjs')).map((f) => `shared/${f}`)];
const code = (f) => readFileSync(`${ROOT}/javascript/${f}`, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
const writing = (pattern) => files.filter((f) => pattern.test(code(f))).sort();

check('a thumbnail of your generations is drawn in one place', writing(/alt="Generated image"/),
      ['shared/generations.mjs']);
check('a rating is asked for in one place', writing(/'\/model-manager\/generations\/rate'/), ['shared/generations.mjs']);
check('and a deletion of one image or one generation',
      writing(/\/model-manager\/generations\/(images\/)?\$\{[^}]*\}\/delete/), ['shared/generations.mjs']);
check('a shift-click\'s range is worked out in one place', writing(/\[Math\.min\(\w+, \w+\), Math\.max\(\w+, \w+\)\]/),
      ['shared/generations.mjs']);

// One badge rule (#89): a thumbnail of yours is badged as a Civitai image's
// card is - from R up, what the work-safe view hides - and "X · prompt" where
// its prompt raised it. It used to badge only the prompt's.
const { generationImageHtml } = await import(`file:///${ROOT}/javascript/shared/generations.mjs`);
const badge = (img) => {
    const box = document.createElement('div');
    box.innerHTML = generationImageHtml({ id: 1, url: '/x.png', exists: true, ...img });
    return box.querySelector('.mm-nsfw-badge')?.textContent ?? '';
};
check('a thumbnail of yours is badged from R up, as a Civitai image\'s card is',
      [badge({ mm_level: 1 }), badge({ mm_level: 2 }), badge({ mm_level: 4 }), badge({ mm_level: 8 }),
       badge({ mm_level: 16 }), badge({ mm_level: 8, mm_level_from_prompt: true })],
      ['', '', 'R', 'X', 'XXX', 'X · prompt']);

done();
