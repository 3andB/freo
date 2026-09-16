# Miami appearance

Use the **Day / Night** buttons in the header to choose Miami Day or Miami Night.
Day is the default. Previously saved System selections now resolve to Day.
Device appearance changes do not change your selection.
An explicit choice is remembered in this browser, shared between tabs on the
same origin, and applies across admin and public pages. Separate devices and
station domains have their own preferences. If browser storage is unavailable,
the choice still applies for the current page session.

Switching changes colours immediately without navigating, resetting form edits,
or interrupting audio. Station logos, artwork and uploaded cover images remain
intact. Player and directory palette accents adapt to the selected appearance.

## Maintaining the skins

`app/static/theme.css` defines semantic `--theme-*` tokens for both skins.
Use text/muted, canvas/surface/raised, border/focus, and the accent/status pairs
rather than adding literal UI colours. Text on solid accent fills uses
`--theme-on-accent`; tinted panels use the matching `*-soft` background and
regular text or the matching status colour. Literal colours are reserved for
illustrations and photo overlays that intentionally retain their materials.

`theme.js` applies the preference before styles render. The appearance partial
is included in each header. Workspace navigation synchronizes the new buttons
and inserts additional component styles before the theme stylesheet. Canvas
renderers can listen for `freo:themechange` and read the computed theme tokens.

Run `venv/bin/pytest -q tests/test_appearance_browser.py tests/test_appearance.py`
for preference, playback, layout, and token contrast checks. The browser tests
require local server sockets, Chromium and ChromeDriver, like the existing
workspace browser tests.

## Forms and header

`forms.css` contains the shared controls and responsive header. Existing page
styles live in the `legacy` cascade layer; shared form rules override their visual
control styles without overriding page layout or needing ID-specific rules.
Native selects, checkboxes, date/time fields and file inputs retain keyboard
behavior. Specialized audio controls keep their compact layout.

Use `admin-primary` or `ui-primary` for the main action, `danger` or `ui-danger`
for destructive actions, and `form-actions` for the action row. Associate helper
and validation messages with `aria-describedby`, and set `aria-invalid` on invalid
fields when errors come from server or JavaScript validation.

The header groups branding, now playing, monitor and account actions. A scoped
ResizeObserver keeps sticky sidebars and toolbars below its actual height.

The form browser audit in `tests/test_forms_browser.py` covers 29 admin screens
in both skins and at 390, 820, 1024 and 1440 pixel widths. It checks horizontal
overflow, header group overlap and usable field sizes. Workflow browser tests
also exercise station creation/deletion, music importing and editing, artwork,
dialogs, scheduling, and playback. Broadcast controls sit beside song categories
so they remain accessible while the preview player is open.

The music list measures the space above the preview player when the header,
filters, player or viewport resize. Playlist details sit beside tracks on wide
screens, keeping reorder controls visible without shrinking form fields.
