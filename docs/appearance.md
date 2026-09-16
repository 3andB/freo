# Miami appearance

Use **Appearance** in the header to choose **Miami Day**, **Miami Night**, or
**System**. System is the default and follows the device's light/dark setting.
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
is included in each header. Workspace navigation synchronizes the new selector
and inserts additional component styles before the theme stylesheet. Canvas
renderers can listen for `freo:themechange` and read the computed theme tokens.

Run `venv/bin/pytest -q tests/test_appearance_browser.py tests/test_appearance.py`
for preference, playback, layout, and token contrast checks. The browser tests
require local server sockets, Chromium and ChromeDriver, like the existing
workspace browser tests.
