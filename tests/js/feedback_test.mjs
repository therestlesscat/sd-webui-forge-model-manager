// Feedback in every tab's header (#443): a press opens a menu of two items,
// each opening its page in a new browser tab - GitHub's new issue, or the
// feedback form. The button shows its menu open (aria-expanded) until it
// closes, whichever way it closes; a second press closes it; and the last tab
// stopping takes it away. The header is the harness's, from ui/header.py, its
// two addresses filled as example.test ones.
import { checker, mountTab, sharedModule, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

// One tile, for its ⋯: the menu is one for the page, a tile's or Feedback's.
const tile = {
    kind: 'generation', matching_count: 1,
    generation: { id: 1, mode: 'txt2img', created_at: '2026-10-18T12:00:00', image_count: 1 },
    images: [{ id: 11, generation_id: 1, position: 0, width: 832, height: 1216, url: '/x/11/file', exists: true,
               meta: { prompt: 'a prompt' }, infotext: 'a prompt', mm_level: 1, prompt_level: 1, user_level: null }],
    checkpoint: { path: 'C:/models/Stable-diffusion/base.safetensors', name: 'base', in_library: true,
                  version_id: 7, model_id: 70, model_name: 'base' },
    loras: [],
};
globalThis.fetch = async (url) => {
    const reply = (body) => ({ ok: true, json: async () => body });
    if (String(url).includes('/model-manager/ui-options')) return reply({ success: true, gallery_hide_nsfw: true });
    if (String(url).includes('/generations/browse')) {
        return reply({ success: true, tiles: [tile], more: false,
                       state: { total: 1, filtered: 1, hidden_nsfw: 0, nsfw_count: 0, stored_generations: 1 },
                       scope: { count: 1 } });
    }
    return reply({ success: true });
};
const opened = [];
window.open = (...args) => { opened.push(args); return null; };

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const button = () => document.querySelector('.mm-feedback-btn');
const menuEl = () => document.querySelector('.gen-menu');
const expanded = () => button()?.getAttribute('aria-expanded');
// Safe on a page with no Feedback - the code before #443 - so each check fails rather than the suite.
const click = (el) => el?.dispatchEvent(new window.Event('click', { bubbles: true }));
const tick = () => new Promise((resolve) => setTimeout(resolve, 20));
// The menu listens for a click outside it only a moment after it opens.
const press = async () => { click(button()); await tick(); };

await waitFor('the header\'s Feedback', () => button());
check('the header holds Feedback, its menu shut', expanded(), 'false');

await press();
const items = () => [...(menuEl()?.querySelectorAll('[data-item]') || [])];
check('pressed, it opens a menu of two items, each saying what it is for',
      items().map((b) => [b.querySelector('.menu-label')?.textContent, b.querySelector('.menu-detail')?.textContent]),
      [['Create a GitHub issue', 'Report a bug or ask for a feature, in public. Needs a GitHub account.'],
       ['Send anonymous feedback', 'A short form, no account needed. Leave an email only if you want a reply.']]);
check('each with its icon and the ↗ of a page in a new tab',
      items().map((b) => [!!b.querySelector('.menu-icon svg'), !!b.querySelector('.menu-out svg')]),
      [[true, true], [true, true]]);
check('and the button shows it open', expanded(), 'true');

click(items()[0]);
await tick();
check('GitHub\'s item opens the button\'s new-issue address in a new tab, and the menu closes',
      [opened, menuEl(), expanded()],
      [[['https://example.test/repo/issues/new', '_blank', 'noopener']], null, 'false']);

opened.length = 0;
await press();
click(items()[1]);
await tick();
check('the form\'s item opens the form, in a new tab', [opened, menuEl(), expanded()],
      [[['https://example.test/form', '_blank', 'noopener']], null, 'false']);

await press();
await press();
check('Feedback pressed again: the menu closed, and stays closed', [menuEl(), expanded()], [null, 'false']);

const ways = {
    'Esc': () => document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }),
                                                            { key: 'Escape' })),
    'a click outside it': () => click(document.body),
    'a scroll of the page': () => window.dispatchEvent(new window.Event('scroll')),
    'a resize of the window': () => window.dispatchEvent(new window.Event('resize')),
};
for (const [way, close] of Object.entries(ways)) {
    await press();
    const open = [!!menuEl(), expanded()];
    close();
    await tick();
    check(`${way} closes it, and the button shows it shut`, [open, !!menuEl(), expanded()],
          [[true, 'true'], false, 'false']);
}

// A tile's ⋯ and Feedback share the one menu: either opening closes the other,
// though one is the tab's and the other the service's.
const tileButton = () => document.querySelector('#gen_grid .gen-menu-btn');
await waitFor('the tile and its ⋯', () => tileButton());
const menus = () => [...document.querySelectorAll('.gen-menu')].map((m) => (m.querySelector('.menu-rich') ? 'feedback' : 'tile'));
click(tileButton());
await tick();
await press();
check('a tile\'s ⋯ open, then Feedback: one menu, Feedback\'s, shown open', [menus(), expanded()], [['feedback'], 'true']);
click(tileButton());
await tick();
check('then the tile\'s ⋯: one menu, the tile\'s, Feedback shut', [menus(), expanded()], [['tile'], 'false']);
ways.Esc();
await tick();

// An address that is not a web page's opens nothing: the items go through
// safeUrl, as data-open-url does.
// Before #443 there is no such module: the check fails rather than the suite.
const { feedbackItems } = await sharedModule('feedback.mjs').catch(() => ({}));
opened.length = 0;
feedbackItems?.({ issues: 'javascript:alert(1)' }).forEach((item) => item.run());
check('an address of javascript:, or none, opens nothing', [typeof feedbackItems, opened], ['function', []]);

// The last tab stopping stops the service, whose menu goes with it - a tab's
// own stop closes only the menus it opened.
await press();
const { leaveServices } = await sharedModule('loading.mjs');
const shownBefore = !!menuEl();
leaveServices('generations');
check('the last tab stopped with the menu open: the menu gone, the button shut',
      [shownBefore, !!menuEl(), expanded()], [true, false, 'false']);

done();
