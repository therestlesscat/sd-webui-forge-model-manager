/**
 * Group by and search, for the tabs of tiles - the Generations tab and the
 * Civitai Images tab alike (#283): what a Group by value groups by, one
 * grouping or two; its menu, each grouping with what to group its groups by
 * then; and the search box. Each tab says its own groupings and what a choice
 * does; neither imports the other's script.
 */
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml, setText } = await shared('core.mjs');

/**
 * What a Group by value groups by, in order: one grouping, or two joined by
 * ">" ("model>day"), a group of the first opening onto groups of the second.
 * Anything not in `names` is no grouping - grouping_chain() on the server.
 */
export function groupChain(value, names) {
    const keys = String(value || '').split('>');
    return keys.length <= 2 && keys.every((key) => names[key]) ? keys : [];
}

/** What the Group by button says: the chain's names, or Nothing. */
export function groupLabel(value, names) {
    const chain = groupChain(value, names);
    return chain.length ? chain.map((key) => names[key]).join(' › ') : 'Nothing';
}

/**
 * A tab's Group by menu: a menu rather than a list - the groupings, a click
 * grouping by one, and beside each, on hover, what to group its groups by
 * then: any other. Built from `names` into the tab's empty list each time it
 * opens. Its listeners go through the tab's `work`, so they stop with it.
 *
 * @param work      the tab's tabWork()
 * @param options   app: the tab's root selector; button: the Group by button's id;
 *                  names: grouping -> its name; current(): the value chosen;
 *                  choose(value): what a pick does
 * @returns {showChoice, close}: the button made to say the choice, the menu closed
 */
export function groupMenu(work, { app, button, names, current, choose }) {
    const byId = (id) => document.getElementById(id);
    const list = () => document.querySelector(`${app} .gen-group-list`);

    function html() {
        const keys = Object.keys(names);
        const value = current();
        const chain = groupChain(value, names);
        const pick = (choice, text) => `<button type="button" data-group-pick="${escapeHtml(choice)}"
            class="${choice === value ? 'gen-group-chosen' : ''}">${escapeHtml(text)}</button>`;
        return pick('', 'Nothing') + keys.map((first) => `
            <div class="gen-group-item" data-group-first="${first}">
                <button type="button" data-group-pick="${first}" class="${chain[0] === first ? 'gen-group-chosen' : ''}"
                        aria-haspopup="true">${escapeHtml(names[first])}<span>▸</span></button>
                <div class="gen-group-sub gen-menu-panel" hidden>
                    <div class="gen-group-sub-title">then by</div>
                    ${keys.filter((key) => key !== first).map((key) => pick(`${first}>${key}`, names[key])).join('')}
                </div>
            </div>`).join('');
    }

    /** The "then by" list of one grouping open, any other closed. */
    function openItem(item) {
        list()?.querySelectorAll('.gen-group-item').forEach((other) => {
            const open = other === item;
            other.classList.toggle('gen-group-open', open);
            const sub = other.querySelector('.gen-group-sub');
            if (sub) sub.hidden = !open;
        });
    }

    function close() {
        const menu = list();
        if (!menu || menu.hidden) return false;
        menu.hidden = true;
        byId(button)?.setAttribute('aria-expanded', 'false');
        return true;
    }

    work.listen(document, 'click', (event) => {
        const target = event.target;
        const menu = list();
        if (!menu) return;
        if (target.closest?.(`#${button}`)) {
            if (!close()) {
                menu.innerHTML = html();
                menu.hidden = false;
                byId(button)?.setAttribute('aria-expanded', 'true');
                // The chosen grouping's "then by" list open, to change the second.
                openItem(menu.querySelector('.gen-group-item > .gen-group-chosen')?.parentElement || null);
            }
            return;
        }
        if (menu.hidden) return;
        const pick = target.closest?.('[data-group-pick]');
        if (pick && menu.contains(pick)) {
            close();
            choose(pick.dataset.groupPick);
            return;
        }
        const item = target.closest?.('.gen-group-item');
        if (item && menu.contains(item)) {
            openItem(item);
            return;
        }
        if (!target.closest?.(`${app} .gen-group-menu`)) close();
    });

    work.listen(document, 'mouseover', (event) => {
        const item = event.target.closest?.('.gen-group-item');
        if (item && list()?.contains(item) && !item.classList.contains('gen-group-open')) openItem(item);
    });

    return {
        /** The button says the grouping - writing nothing when it already does: this runs after every update. */
        showChoice: () => setText(byId(button), groupLabel(current(), names)),
        close,
    };
}

/**
 * A tab's search box, as it starts: empty, whatever the browser kept in it,
 * and searching again when its × empties it - which changes nothing a change
 * event would tell, only a search event.
 */
export function startSearchBox(box, search) {
    if (!box) return;
    box.value = '';
    box.addEventListener('search', () => search(box.value));
}
