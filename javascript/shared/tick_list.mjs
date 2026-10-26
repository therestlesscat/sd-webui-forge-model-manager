/**
 * A list of checkboxes behind a box, as the filter bars draw NSFW Levels,
 * Commercial Use and Type (#341): the box opens and closes it, a click
 * outside closes it, and the box says what is ticked.
 *
 * The checkboxes are the state; this keeps none of its own. The caller lays
 * out the parts and hands them in. A row's checkbox carries its value; one
 * that stands for several carries them comma-joined (the LoRA row's six
 * kinds), and a row with an empty value is All. A row with `hidden` is not
 * in the list. Given `several`, a checkbox of its own, the list picks one row
 * at a time - a click picks its row and closes the list, as a dropdown does -
 * unless that box is ticked.
 */

/**
 * @param {object} parts
 * @param {Element} parts.dropdown - what holds the box and the list; a click outside it closes the list
 * @param {Element} parts.panel - the list, shown while it has the class `open`
 * @param {Element} [parts.display] - where the box's text goes
 * @param {HTMLInputElement} [parts.several] - the Select several box: the list picks one row unless it is ticked
 * @param {(list) => string} [parts.text] - the box's text; without it, the text is left to the caller
 * @param {(list) => void} [parts.changed] - after the ticks change by a click
 * @param {object} scope - the tab's scope: the outside click is listened to through it
 */
export function tickList({ dropdown, panel, display = null, several = null, text = null, changed = null }, scope) {
    const rowBoxes = () => [...panel.querySelectorAll('input[type="checkbox"][value]')]
        .filter((box) => !box.closest('[hidden]'));
    const allBox = () => rowBoxes().find((box) => box.value === '') || null;
    const kindBoxes = () => rowBoxes().filter((box) => box.value !== '');
    const one = () => Boolean(several) && !several.checked;

    const list = {
        open: () => panel.classList.contains('open'),
        toggle() { panel.classList.toggle('open'); },
        close() { panel.classList.remove('open'); },
        /** The ticked rows' values, in the list's order, a row of several spelled out. */
        values() {
            return kindBoxes().filter((box) => box.checked)
                .flatMap((box) => box.value.split(',')).filter(Boolean);
        },
        /** The labels of the ticked rows, in the list's order. */
        labels() {
            return kindBoxes().filter((box) => box.checked)
                .map((box) => box.closest('label')?.textContent.trim() || box.value);
        },
        /** Whether every row is ticked, or none - either way, every type. */
        everything() {
            const boxes = kindBoxes();
            const on = boxes.filter((box) => box.checked).length;
            return on === 0 || on === boxes.length;
        },
        /**
         * Tick the rows these values name: a row of several when any of its
         * values is among them. Picking one row at a time, more than one is
         * either ticked by ticking Select several (`more: 'several'`, a saved
         * search) or cut to the first of them in the list's order.
         */
        set(values, { more = 'first' } = {}) {
            const wanted = new Set((values || []).filter(Boolean));
            const hits = kindBoxes().filter((box) => box.value.split(',').some((v) => wanted.has(v)));
            if (one() && hits.length > 1) {
                if (more === 'several') several.checked = true;
                else hits.splice(1);
            }
            kindBoxes().forEach((box) => { box.checked = hits.includes(box); });
            list.update();
        },
        /**
         * Show some rows in place of others - one row for several, or the
         * several again - the ticks carried over by set's rule.
         */
        replaceRows(shown, hidden) {
            const values = list.values();
            hidden.forEach((row) => { row.hidden = true; });
            shown.forEach((row) => { row.hidden = false; });
            list.set(values);
        },
        /** Draw the box's text, the mode and the picked row again, from the ticks. */
        update() {
            const single = one();
            panel.classList.toggle('tick-list-one', single);
            const all = allBox();
            if (all) all.checked = kindBoxes().every((box) => !box.checked);
            rowBoxes().forEach((box) => {
                box.closest('label')?.classList.toggle('tick-list-picked', single && box.checked);
            });
            if (display && text) {
                const said = text(list);
                if (display.textContent !== said) display.textContent = said;
            }
        },
    };

    panel.addEventListener('change', (event) => {
        const box = event.target;
        if (!box?.matches?.('input[type="checkbox"]')) return;
        if (box === several) {
            // Back to one row: the first ticked stays (#341).
            if (!several.checked) list.set(list.values());
            else list.update();
            return;
        }
        if (!box.hasAttribute('value')) return;
        if (box.value === '') {
            // All: every row unticked, which asks for every type.
            kindBoxes().forEach((other) => { other.checked = false; });
            if (one()) list.close();
        } else if (one()) {
            kindBoxes().forEach((other) => { other.checked = other === box; });
            list.close();
        }
        list.update();
        changed?.(list);
    });

    scope.listen(document, 'click', (event) => {
        if (!dropdown.contains(event.target)) list.close();
    });

    list.update();
    return list;
}
