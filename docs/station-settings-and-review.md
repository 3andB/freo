# Station settings and song review

Each station has **Station settings** in the admin navigation, with shortcuts from Overview and Stations. Set the name, city, state/region, contact email, phone, description, timezone, logo, and public URL name there.

The public URL opens the Freo listening page. Changing its name preserves previous URLs and does not rename the station's internal identity or media directory. `PUBLIC_BASE_URL`, when configured, supplies the origin of the copyable URL. Contact email and phone stay private unless **Publish contact email and phone** is selected. Name, description, location, and logo appear in station views and the public player.

Logos accept JPEG, PNG, or WebP up to 10 MB and 3000 pixels on either side. A square image is recommended. The server decodes and re-encodes the image, strips metadata, and stores an original-size PNG and a thumbnail up to 512 pixels. Replace or remove the logo from Settings.

## Auto playback

Beside Monitor, **Skip to next** advances the current item through the automation worker. **Next** displays the first observed queued item, including imaging when that comes before a song. Empty queues and lost connections are stated explicitly. Skipping an empty queue can lead to fallback audio while automation refills it.

A skip is tied to the observed playback decision. Repeated clicks cannot skip additional songs. The worker rechecks the active request and operating mode before acting; stale observations disable controls.

## Review flags

Use **💬 Flag song** beside the Auto controls or beside any song in Music. An optional note describes the issue. The dialog retains the song selected when opened, even when playback changes before saving.

**Flagged songs** in Music lists open flags and supports the usual search/filter controls. Edit the note, resolve a flag, or find it under **Resolved flags** and reopen it. Flags belong to the selected station, including for shared songs. They do not disable songs or change eligibility. Conflicting edits require reopening the dialog. Creation retains the operator and timestamp; all updates enter the admin audit log. Deleting a song removes it from review lists; its retained database record and audit history remain.

## Play counts

Music song rows and the song inspector show confirmed play counts. Categories show their own totals in Music and category views. Counts are per station and come from confirmed playback starts, not queue requests or browser previews. A skip still counts the song that actually started. Repeat counts again only when the repeated playback starts. Category credit uses the category recorded when the item was selected; later membership changes do not move that credit. Manual songs without a selected category increase only the song count.

## Upgrade and validation

Apply the additive database migration with `venv/bin/flask --app app:create_app db upgrade` before restarting the web and automation services. Revision `b27d903e1a46` adds station identity fields, logo storage, and song flags. Back up the database before deployment. Existing stations begin with empty contact/location fields and no logo; existing airplay history remains the source for counts.

Regression coverage includes settings validation and alias preservation, contact privacy, logo formats/limits/removal, flag concurrency and shared-song isolation, stale/duplicate skips, browser navigation and mobile layout, and a real isolated Liquidsoap Auto skip with confirmed song/category counts.
