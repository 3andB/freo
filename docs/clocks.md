# Clocks

A clock is a reusable, station-scoped ordered list of music requests. Phase 6 supports `CATEGORY` and `ROTATION` slots only. A category slot asks the proven Phase 5 candidate selector for one approved track. A rotation slot asks a named rotation for its next category, then uses the same selector. Unsupported slot types fail validation; no database value is evaluated as code. A rotation's internal category cursor and a clock's programming cursor are separate.

The clock repeats its enabled slots while active. A new weekly assignment occurrence starts at slot one. A worker restart within the same occurrence resumes the durable `clock_states` cursor. The same clock on a later day is a new occurrence and starts at slot one. Editing a clock affects future decisions; the current track is not interrupted. Referenced categories and rotations must belong to the same station and be enabled. Deletion is deliberately deferred; disable or replace references first.

Administrative examples (run from the server as root, with Freo's private environment):

```sh
flask --app wsgi clock create --station freo-demo --name Morning --slug morning
flask --app wsgi clock add-slot --station freo-demo --clock morning --type category --target power
flask --app wsgi clock add-slot --station freo-demo --clock morning --type rotation --target main-test
flask --app wsgi clock validate --station freo-demo morning
flask --app wsgi clock preview --station freo-demo --slots 12 morning
flask --app wsgi clock default --station freo-demo morning
```

`clock preview` simulates choices in memory and does not advance durable cursors or history. Public `GET /api/stations/<slug>/clocks` and `/clocks/<clock-slug>` expose safe read-only programming metadata. There are no anonymous mutation routes. A future phase can add carts, IDs, sweepers, and breaks as explicitly implemented slot types; these are not supported now.
