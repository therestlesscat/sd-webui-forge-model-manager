"""The Model Manager toolbar: two right-aligned rows, two boxed action groups."""

import os
import sys

# The extension and the test helpers, found from this file rather than from a
# working directory, so a suite runs from anywhere.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures                                       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'toolbar_test')
import io
import re
import sys

UI = io.open(os.path.join(ROOT, 'model_manager/ui/tab_model_manager.py'), encoding='utf-8').read()
CSS = io.open(os.path.join(ROOT, 'style.css'), encoding='utf-8').read()
JS = io.open(os.path.join(ROOT, 'javascript/model_manager.mjs'), encoding='utf-8').read()

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def block(html, start_marker, nth=0):
    """The nth <div ...> block starting at a marker, by brace-free tag depth."""
    idx = -1
    for _ in range(nth + 1):
        idx = html.index(start_marker, idx + 1)
    depth = 0
    i = idx
    for m in re.finditer(r'<div\b|</div>', html[idx:]):
        depth += 1 if m.group(0) == '<div' else -1
        if depth == 0:
            return html[idx:idx + m.end()]
    raise AssertionError('unbalanced: ' + start_marker)


# One row now: the two ways of updating the library, boxed together on the
# left, and the search buttons where they were on the right.
check('there is exactly one button row', UI.count('<div class="filter-buttons-row">'), 1)
row = block(UI, '<div class="filter-buttons-row">')

check('it has Load Models', 'id="mm_load_btn"' in row)
check('and Save Search', 'id="mm_save_search_btn"' in row)
check('and exactly one boxed group', row.count('class="mm-button-group"'), 1)

update_group = block(row, '<div class="mm-button-group"')
for control in ('mm_sync_btn', 'mm_sync_cancel_btn', 'mm_refresh_btn', 'mm_scan_cancel_btn'):
    check('the group holds %s' % control, 'id="%s"' % control in update_group)
check('the group is two actions and their cancels', update_group.count('<button'), 4)
check('the search buttons stay out of it',
      'mm_load_btn' in update_group or 'mm_save_search_btn' in update_group, False)

check('the group comes first, so it sits on the left',
      row.index('mm-button-group') < row.index('mm_load_btn'))
check('syncing is offered before scanning',
      row.index('mm_sync_btn') < row.index('mm_refresh_btn'))

# The button says what it does now, rather than naming the database.
check('the scan button is called Scan Disk', '>Scan Disk<' in row)
check('and no longer Refresh DB', 'Refresh DB' in UI, False)

for gone in ('mm_sync_meta_btn', 'mm_sync_meta_images_btn'):
    check('%s is gone from the toolbar' % gone, gone in UI, False)
check('Force is no longer in the toolbar row', 'mm_sync_force' in row, False)

# --- every control survived the move, exactly once --------------------------
CONTROLS = ['mm_load_btn', 'mm_save_search_btn', 'mm_refresh_btn', 'mm_scan_cancel_btn',
            'mm_sync_btn', 'mm_sync_cancel_btn']
for control in CONTROLS:
    check('%s appears exactly once in the markup' % control, UI.count('id="%s"' % control), 1)

# --- CSS --------------------------------------------------------------------
row_css = CSS[CSS.index('.filter-buttons-row {'):]
row_css = row_css[:row_css.index('}')]
check('the row is right-aligned', 'justify-content: flex-end' in row_css, True)
check('and still wraps', 'flex-wrap: wrap' in row_css, True)
check('the group claims the slack, putting it on the left',
      'margin-right: auto' in CSS[CSS.index('.filter-buttons-row .mm-button-group {'):
                                  CSS.index('}', CSS.index('.filter-buttons-row .mm-button-group {'))])

# Anchored at a line start: '.filter-buttons-row .mm-button-group {' ends
# with the same text and would otherwise be found first.
check('the boxed group has a border', '\n.mm-button-group {' in CSS)
group_css = CSS[CSS.index('\n.mm-button-group {'):]
group_css = group_css[:group_css.index('}')]
for prop in ('border:', 'border-radius:', 'background:', 'display: flex'):
    check('boxed group sets %s' % prop.rstrip(':'), prop in group_css)

# The height used to come from a descendant selector on this row, which meant
# nesting a button one level deeper silently changed its size. It now comes
# from the shared button rule, so it reaches every button wherever it sits.
base = CSS[CSS.index('.mm-btn,' + chr(10) + '.cb-btn,'):]
base = base[:base.index('}')]
check('the shared button rule sets the height', 'height: var(--mm-btn-height)' in base)
check('and pins the margin Gradio would otherwise add',
      'margin: 0 !important' in base)
# Gradio's preflight resets every button's background at (0,1,1), which beats
# any single class. The colour is declared once with !important and the
# variants move the variable, so a variant never has to out-specify it.
check('the background is declared once, past the preflight reset',
      'background: var(--mm-btn-bg) !important' in base)
for variant in ('primary', 'danger'):
    variant_css = CSS[CSS.index('.mm-btn.%s,' % variant):]
    variant_css = variant_css[:variant_css.index('}')]
    check('the %s variant sets the variable, not the background' % variant,
          '--mm-btn-bg:' in variant_css and 'background:' not in variant_css)
check('so the row does not have to size buttons itself',
      '.filter-buttons-row .mm-btn' in CSS, False)
# The browser used to wrap its actions in .filter-buttons-group; they now sit
# on .filter-buttons-row, the same row the Model Manager uses, so that class
# is gone rather than kept as a second way to lay out the same buttons.
check('the browser has no group of its own', '.filter-buttons-group' in CSS, False)

# --- JS still addresses everything by id, not by nesting --------------------
check('JS never walks up from a sync button', 'mm_sync_btn").parentNode' in JS, False)
for control in CONTROLS:
    if control == 'mm_save_search_btn':
        continue  # bound via its own lookup elsewhere
    check('JS still references %s' % control, control in JS)
check('no handler still reaches for the removed buttons',
      'mm_sync_meta_btn' in JS or 'mm_sync_meta_images_btn' in JS, False)

# --- the dialog the button now opens ----------------------------------------
dialog = block(UI, '<div id="mm_sync_dialog"')
check('the dialog starts hidden', 'style="display: none;"' in dialog)
check('the dialog is a modal to assistive tech', 'role="dialog"' in dialog
      and 'aria-modal="true"' in dialog)
check('and is labelled by its heading', 'aria-labelledby="mm_sync_dialog_title"' in dialog
      and 'id="mm_sync_dialog_title"' in dialog)

# scope: four mutually exclusive choices, one group
scopes = re.findall(r'name="mm_sync_scope" value="(\w+)"', dialog)
check('the five scopes', scopes, ['all', 'results', 'stale', 'downloaded', 'force'])
check('exactly one is preselected',
      dialog.count('name="mm_sync_scope"') - dialog.count('checked>'), len(scopes) - 1)
check('the staleness windows live in a select', 'id="mm_sync_stale_days"' in dialog)
check('and the download windows in their own',
      'id="mm_sync_downloaded_days"' in dialog)
check('force sync picks which files to read',
      'id="mm_sync_force_mode"' in dialog)
check('and offers all three sets',
      re.findall(r'<option value="(\w+)"', dialog),
      ['all', 'identified', 'unidentified'])
check('all three are the same kind of control',
      dialog.count('class="mm-dialog-select"'), 3)

# depth: metadata is compulsory, the rest are choices
check('metadata cannot be turned off', '<input type="checkbox" checked disabled>' in dialog)
# Include is only about what data to fetch now; which files is a scope.
for control in ('mm_sync_images', 'mm_sync_prompts'):
    check('the dialog offers %s' % control, 'id="%s"' % control in dialog)
for gone in ('mm_sync_rehash', 'mm_sync_force_row'):
    check('%s is no longer a depth option' % gone, gone in dialog, False)
check('prompts start disabled, waiting on images',
      'id="mm_sync_prompts" disabled' in dialog)
check('and unticked, since a locked tick would promise what cannot happen',
      'id="mm_sync_prompts" checked' in dialog, False)
check('the Include section is three lines',
      dialog.count('type="checkbox"'), 3)

check('there is somewhere to put the estimate', 'id="mm_sync_estimate"' in dialog)
check('and a Start and a Cancel',
      'id="mm_sync_dialog_start"' in dialog and 'id="mm_sync_dialog_cancel"' in dialog)

# every id the dialog defines is one the script actually drives
dialog_ids = set(re.findall(r'id="(mm_[\w]+)"', dialog))
unused = sorted(i for i in dialog_ids if i not in JS and i != 'mm_sync_dialog_title')
check('no dialog control is left unwired', unused, [])

# --- the missing-key banner -------------------------------------------------
banner = block(UI, '<div id="mm_api_key_warning"')
check('the banner starts hidden', 'style="display: none;"' in banner)
check('it names the setting exactly',
      'Settings &rarr; Model Manager &rarr; Civitai API Key' in banner)
check('and says why it matters', 'No Civitai API key' in banner)
check('it sits above the filters',
      UI.index('mm_api_key_warning') < UI.index('model-manager-filters'))
check('the script decides when to show it',
      "showApiKeyBanner('mm_api_key_warning')" in JS)
check('CSS styles it', '.mm-banner {' in CSS)

# The row reads left to right up to the action it exists for: the library
# group on the left, then Save Search, then Load Models last. The scroll
# restore button is built by script and lands immediately before Load Models,
# so that one stays rightmost whether or not the button is there.
ROW = UI[UI.index('<div class="filter-buttons-row">'):]
ROW = ROW[:ROW.index('</div>' + chr(10) + ' ' * 16 + '</div>')]
check('the library group comes first', ROW.index('mm-button-group') < ROW.index('mm_save_search_btn'))
check('and Load Models is the last thing on the row',
      ROW.index('mm_save_search_btn') < ROW.index('mm_load_btn'))
check('the restore button is placed against Load Models, not at the start',
      "buttonsRow.insertBefore(btn, loadBtn || null)" in JS)
check('and never at firstChild', 'buttonsRow.firstChild' in JS, False)

# --- Basic and advanced filters ---------------------------------------------
BASIC = UI[UI.index('<div class="model-manager-filters">'):UI.index('<details class="mm-advanced"')]
ADVANCED = UI[UI.index('<details class="mm-advanced"'):UI.index('</details>')]

for control in ('mm_type', 'mm_checkpoint_type', 'mm_nsfw_dropdown',
                'mm_preview_show_nsfw', 'mm_sort_by', 'mm_sort_order', 'mm_search'):
    check('%s stays in reach without expanding anything' % control, control in BASIC)

for control in ('mm_civitai', 'mm_base_model', 'mm_is_bookmarked', 'mm_min_versions',
                'mm_commercial_dropdown', 'mm_allow_derivatives',
                'mm_allow_different_license'):
    check('%s is behind Advanced' % control, control in ADVANCED)

# One row of controls, then the search box on its own.
check('the visible controls share a single row', BASIC.count('<div class="filter-row">'), 2)
check('and the search box is the second of them',
      BASIC.index('mm_search') > BASIC.rindex('<div class="filter-row">'))
check('the search box is given the row to itself', 'style="flex: 1;"' in BASIC)

# Controls of three different element types sit side by side in that row, so
# the height is stated once rather than derived from padding - which is how
# the two multi-selects ended up taller than the selects beside them.
control_css = CSS[CSS.index('.filter-group input:not([type="checkbox"]),'):]
control_css = control_css[:control_css.index('}')]
check('the shared control rule covers the multi-selects',
      '.mm-multiselect-display' in control_css)
check('and the checkbox label beside them',
      '.mm-checkbox-label' in control_css)
check('it states a height', 'height: 36px' in control_css)
check('and measures it from the border', 'box-sizing: border-box' in control_css)
check('the multi-select no longer sets its own box',
      'padding' in CSS[CSS.index(chr(10) + '.mm-multiselect-display {'):
                       CSS.index('}', CSS.index(chr(10) + '.mm-multiselect-display {'))],
      False)

# The checkbox asks the opposite of what the API takes: it offers to SHOW
# NSFW in the preview, while preview_least_nsfw asks for the least NSFW image
# to be used. The conversion lives in two named functions so it cannot be
# applied at some call sites and not others.
check('the control is named for what it offers', 'id="mm_preview_show_nsfw"' in UI)
check('and says so', 'Show NSFW Images In Model Preview' in UI)
check('the old wording is gone', 'Hide NSFW' in UI, False)
check('nothing reads the checkbox directly', "getElementById('mm_preview_show_nsfw').checked" in JS, False)
check('the value sent is the inverse of the box',
      'return checkbox ? !checkbox.checked : null;' in JS)
# Both are called from four other functions, so they have to be declared at
# module scope. Nested inside one of their callers they parse fine and throw
# ReferenceError everywhere else, which is how they were first written.
for helper in ('previewLeastNsfwFromCheckbox', 'setPreviewCheckboxFrom'):
    check('%s is declared at module scope' % helper,
          (chr(10) + 'function %s(' % helper) in JS)
check('and the box is set as the inverse of the value',
      'if (checkbox) checkbox.checked = !previewLeastNsfw;' in JS)

# The row is not an equal split: the preview toggle is one checkbox, Sort By
# carries the longest options. Both are tagged in the markup rather than
# selected by position, so reordering the row cannot silently reassign them.
check('the preview toggle is tagged compact',
      'filter-group filter-group-compact' in BASIC)
check('and Sort By tagged wide', 'filter-group filter-group-wide' in BASIC)
check('CSS narrows the compact one',
      '.filter-group.filter-group-compact {' in CSS)
check('and the wide rule outspecifies the box it sits in',
      '.filter-group-bordered .filter-group.filter-group-wide {' in CSS)

# A <details> with no `open`: collapsed, with nothing for JavaScript to keep
# in step. Adding `open` here would quietly undo the point of the split.
check('advanced starts collapsed', '<details class="mm-advanced" id="mm_advanced">' in UI)
check('really collapsed', 'mm-advanced" id="mm_advanced" open' in UI, False)
check('it is a disclosure, not a scripted panel', 'mm_advanced' in JS, False)
check('it sits below the search box and above the buttons',
      UI.index('mm_search') < UI.index('<details class="mm-advanced"') <
      UI.index('filter-buttons-row'))
check('CSS styles the summary', '.mm-advanced-summary {' in CSS)

# The Civitai Browser used to carry a parallel copy of the whole filter bar -
# the row, the group, the label, the bordered box, the control box - scoped to
# .cb-filters, at the same specificity as the shared rules and later in the
# file, so every one of them won. That is why unifying a piece at a time kept
# leaving the two tabs looking different. There is now one implementation, and
# .cb-filters styles nothing but the panel it all sits in.
for restated in ('.cb-filters .filter-row', '.cb-filters .filter-group',
                 '.cb-filters .filter-group-bordered',
                 '.cb-filters .filter-group-half'):
    check('the browser does not restate %s' % restated, restated in CSS, False)
check('the panel is the only thing .cb-filters is for',
      CSS.count('.cb-filters'), 1)
check('and it shares even that with the other tab',
      '.model-manager-filters,' + chr(10) + '.cb-filters {' in CSS)
tag_input_css = CSS[CSS.index('.cb-tag-container input {'):]
tag_input_css = tag_input_css[:tag_input_css.index('}')]
check('nor does the tag box', 'padding' in tag_input_css, False)
# Its wrapper is a plain block, so without this the input stays inline-block
# and carries four pixels of descender space that the search box does not.
check('and the tag box is blockified by hand',
      'display: block' in tag_input_css)

# The browser's own row: two search boxes and the options beside them, with
# the actions on a row of their own below - the shape the other tab has.
CB_UI_EARLY = io.open(os.path.join(ROOT, 'model_manager/ui/tab_civitai_browser.py'),
                      encoding='utf-8').read()
check('the options are laid out across, not stacked',
      '<div class="filter-checkboxes">' in CB_UI_EARLY)
check('both checkboxes are inside it',
      CB_UI_EARLY.index('cb_nsfw') > CB_UI_EARLY.index('filter-checkboxes') and
      CB_UI_EARLY.index('cb_require_prompt') > CB_UI_EARLY.index('filter-checkboxes'))
check('the actions sit below the whole row',
      CB_UI_EARLY.index('cb_search"') < CB_UI_EARLY.index('filter-buttons-row') <
      CB_UI_EARLY.index('cb_search_btn'))
check('on the row both tabs use', 'class="filter-buttons-row"' in CB_UI_EARLY)
check('and CSS lays the checkboxes out', '.filter-checkboxes {' in CSS)
check('the browser sort box gets the width its options need',
      'class="filter-group filter-group-wide"' in CB_UI_EARLY)
check('and the modifier is not named after one tab',
      'mm-filter-wide' in CSS or 'mm-filter-compact' in CSS, False)

# Each tab can hand a model to the other. The Civitai Browser end existed;
# this is the return trip. tests/js/bridge_test.mjs drives the lookup itself -
# these only check the two halves are wired to each other's names.
check('the details header offers the jump',
      'window.mmShowInCivitaiBrowser(' in JS)
check('only for a model Civitai knows',
      JS.index('window.mmShowInCivitaiBrowser(${modelId})') > 0)
check('it looks for the tab by the name the tab is registered under',
      "b.textContent.trim() === 'Civitai Browser'" in JS)
check('and the browser registers exactly that',
      '"Civitai Browser"' in io.open(
          os.path.join(ROOT, 'scripts/model_manager_ui.py'), encoding='utf-8').read())
# Both header actions are the shared small button, so they are the same size
# as each other. Sync used to be a pill of its own - 0.75em text and a height
# that came from its padding - beside a 28px button, which is what put them
# out of line.
for action in ('mmForceSyncModel', 'mmShowInCivitaiBrowser'):
    call = JS[JS.index(action) - 200:JS.index(action)]
    check('%s is on a shared button' % action, 'mm-btn' in call and 'mm-btn-small' in call)
check('neither carries a tab-specific class', 'cb-header-action' in JS, False)
check('and the header rule names the shared one',
      '.detail-header .header-action {' in CSS)

check('it sends the same syntax this tab takes',
      "window.cbShowModel('model:' + modelId)" in JS)

CB_JS_EARLY = io.open(os.path.join(ROOT, 'javascript/civitai_browser.mjs'),
                      encoding='utf-8').read()
check('the browser answers to that name', 'window.cbShowModel = ' in CB_JS_EARLY)
check('and still offers the trip the other way',
      'window.cbShowInModelManager = ' in CB_JS_EARLY)

# Both tabs carry it, from one implementation rather than two copies.
CB_UI = io.open(os.path.join(ROOT, 'model_manager/ui/tab_civitai_browser.py'), encoding='utf-8').read()
CB_JS = io.open(os.path.join(ROOT, 'javascript/civitai_browser.mjs'), encoding='utf-8').read()
COMMON = io.open(os.path.join(ROOT, 'javascript/shared/common.mjs'), encoding='utf-8').read()

cb_banner = block(CB_UI, '<div id="cb_api_key_warning"')
check('the browser has the banner too', 'style="display: none;"' in cb_banner)
check('naming the same setting',
      'Settings &rarr; Model Manager &rarr; Civitai API Key' in cb_banner)
check('and it shares the styling', 'class="mm-banner"' in cb_banner)
check('the browser script shows it',
      "showApiKeyBanner('cb_api_key_warning')" in CB_JS)

check('the waiting is written once', 'export function showApiKeyBanner' in COMMON)
for script in (JS, CB_JS):
    check('neither tab keeps its own copy',
          'function showApiKeyBanner' in script.replace('export function', ''), False)
check('and the answer is fetched once for both', COMMON.count('/model-manager/ui-options'), 1)

# --- Scan Disk asks before it changes anything ------------------------------
scan_dialog = block(UI, '<div id="mm_scan_dialog"')
check('the scan dialog starts hidden', 'style="display: none;"' in scan_dialog)
check('it is a modal to assistive tech',
      'role="dialog"' in scan_dialog and 'aria-modal="true"' in scan_dialog)
check('and is labelled by its heading',
      'aria-labelledby="mm_scan_dialog_title"' in scan_dialog)
check('it has a Cancel and a Scan',
      'id="mm_scan_dialog_cancel"' in scan_dialog and 'id="mm_scan_dialog_start"' in scan_dialog)
check('it says what it adds and removes',
      scan_dialog.count('<li>'), 4)
check('and that Civitai is not involved', 'Does not contact Civitai' in scan_dialog)
check('it stays short', len(re.sub(r'<[^>]+>', ' ', scan_dialog).split()) < 60)
for control in ('mm_scan_dialog', 'mm_scan_dialog_cancel', 'mm_scan_dialog_start'):
    check('JS drives %s' % control, control in JS)

# --- the dialog's own styling exists ----------------------------------------
for rule in ('.mm-dialog-backdrop', '.mm-dialog ', '.mm-dialog-option',
             '.mm-dialog-estimate', '.mm-dialog-actions', '.mm-dialog-muted'):
    check('CSS defines %s' % rule.strip(), rule.strip() + ' {' in CSS or rule + '{' in CSS)
# The dialog has to follow the WebUI's theme, including the parts of it the
# browser draws itself.
dialog_css = CSS[CSS.index('.mm-dialog {'):]
dialog_css = dialog_css[:dialog_css.index('}')]
check('the dialog sets its own text colour', 'color: var(--body-text-color' in dialog_css)

select_css = CSS[CSS.index('.mm-dialog-select {'):]
select_css = select_css[:select_css.index('}')]
check('the select sets a real colour, not inherit',
      'color: var(--body-text-color' in select_css and 'color: inherit' not in select_css)
check('the browser does not paint the closed control',
      'appearance: none' in select_css and '-webkit-appearance: none' in select_css)
check('so the arrow is drawn by us', 'data:image/svg+xml' in select_css)
check('the option list is told to be dark under .dark',
      '.dark .mm-dialog-select {' in CSS
      and 'color-scheme: dark' in CSS[CSS.index('.dark .mm-dialog-select {'):
                                      CSS.index('}', CSS.index('.dark .mm-dialog-select {'))])
# Chrome paints the open list with the select's background-color, which is a
# translucent tint - so the options need an opaque colour of their own, and it
# must not be the white variable.
check('the options carry an opaque background', '.mm-dialog-select option {' in CSS)
option_css = CSS[CSS.index('.mm-dialog-select option {'):]
option_css = option_css[:option_css.index('}')]
check('and it is not the white variable', 'input-background-fill' in option_css, False)
check('it is the one the dialog itself uses',
      'var(--background-fill-primary' in option_css)

# This theme leaves --input-background-fill white even under .dark, so the
# dialog's panels must not be coloured from it.
dialog_block = CSS[CSS.index('   Sync dialog'):]
live = [l for l in dialog_block.splitlines()
        if not l.strip().startswith(('/*', '*', '--')) and '*/' not in l]
live = '\n'.join(live)
check('no dialog panel takes its colour from the white variable',
      'input-background-fill' in live, False)
for rule in ('.dark .mm-dialog-option:hover', '.dark .mm-dialog-select',
             '.dark .mm-dialog-estimate'):
    check('%s has a dark tint' % rule, rule + ' {' in dialog_block)
check('the select keeps its chevron under .dark',
      'background-color:' in dialog_block[dialog_block.index('.dark .mm-dialog-select {'):
                                          dialog_block.index('}', dialog_block.index('.dark .mm-dialog-select {'))])

check('the backdrop sits above the other modal',
      int(re.search(r'\.mm-dialog-backdrop \{[^}]*z-index: (\d+)', CSS).group(1))
      > int(re.search(r'\.mm-modal-overlay \{[^}]*z-index: (\d+)', CSS).group(1)))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
