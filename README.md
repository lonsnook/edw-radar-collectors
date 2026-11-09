# EDW project radar collectors

Daily scripts that read public government records for new multifamily and senior living projects. They save what is new so Claude can read it, add context and update the Early Project Radar dashboard.

## What it reads

| Source | How | Status |
|---|---|---|
| Charlotte planning and zoning agendas | Legistar data interface | Enabled. Not tested against the live site. May need a token. |
| Chicago building permits | City open data portal | Enabled. Dataset id from memory, not tested live. |
| Dallas building permits | City open data portal | Disabled. Dataset id and field names must be checked first. |
| NC Certificate of Need application logs | PDF logs on the state site | Enabled. PDF layout not tested live. |

Not built yet: Raleigh, Greensboro, Winston-Salem, High Point, county loan and deed filings, HUD, bond disclosures.

## What it writes (in `data/`)

- `items.json`: every matching item from the last 90 days, each with a `first_seen` date.
- `new_today.json`: only items first seen in the latest run.
- `run_log.json`: per source, whether it worked, how many items it found and any error. Check this first when something looks wrong.

## Set up

1. Create a new GitHub repository (private is fine to start) and upload everything in this folder, including the hidden `.github` folder.
2. In the repository, open Settings, then Actions, then General. Under Workflow permissions choose "Read and write permissions" and save.
3. Open the Actions tab, choose "Daily collectors", and press "Run workflow".
4. When it finishes, open `data/run_log.json`. Each source shows `ok` or an error message.
5. Fix errors by editing `config.json` (dataset ids, field names, keywords). The workflow then runs by itself every morning.

If Charlotte's data interface asks for a token, request one from the city's Legistar contact and save it in the repository under Settings, Secrets, as `LEGISTAR_TOKEN_CHARLOTTE`.

## Tuning

Everything you are likely to change is in `config.json`: the keywords, the minimum unit count, the minimum permit cost, and which sources are on.

## Tests

`python -m unittest discover -s tests` runs checks on the filtering, history and error handling using sample data. They do not contact any real website.

## Known limits

- The first run on each source may find many items, because everything is new the first time.
- A city that redesigns its site will break its collector. `run_log.json` shows when.
- Government pages often show the owner and not the architect. These scripts record what the page says and nothing more.
