# Music tags rollout

Apply migration `e20a6b7c9012` with `venv/bin/flask --app wsgi db upgrade` before loading the updated application. It adds a tag description and fills in missing starter tags for existing stations, preserving existing names, colors, and assignments. New stations receive starter tags during station creation. Reads never recreate deleted tags.

## Disposable installation validation

On a fresh PostgreSQL installation, apply migrations through `d72e1f90a631`. Create two stations, an existing `hit` tag with a custom name/color, and a song assigned to it. Upgrade to head and verify each station has the seven starter slugs, the custom tag is preserved, and its assignment remains. Edit and delete starter tags, reload Music, and verify the changes persist. Downgrade and re-upgrade on this disposable installation to check schema compatibility; downgrading preserves tags but removes descriptions, and re-upgrading fills in missing starter slugs again.

Run the Music API and browser tests. Check Programming → Tags creation, editing, and confirmed deletion; rapid tag/category clicks; connection failure rollback; artist and album song controls; narrow screens and keyboard access. Verify ongoing preview playback and song selection remain intact while toggling.

Deploy the reviewed migration and application together through the normal deployment process. No audio engine configuration change is required. Rollback must restore matching application/schema versions; a schema downgrade discards descriptions, so retain the ordinary database backup if descriptions need restoring.
