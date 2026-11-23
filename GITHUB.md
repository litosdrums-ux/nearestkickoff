# Putting Nearest Kickoff on GitHub

Everything in this repo is ready to go. The parts that need a human are the parts that need
*your* identity — an account, a password, an email you can verify.

## What you do (about 15 minutes, no git knowledge needed)

### 1. Create the account
**github.com/signup.** Use an email you'll keep after Columbia. Turn on two-factor
authentication when it offers — GitHub will require it eventually anyway.

### 2. Create an empty repository
**New repository**, name it `nearestkickoff`. Private is fine; nothing here is secret, so public
is also fine if you'd rather. **Do not** tick "Add a README" — an empty repo uploads more
cleanly.

### 3. Upload this folder
On the empty repo's page: **uploading an existing file** → drag the whole unzipped project
folder onto the browser window. GitHub takes nested folders.

Two things to check before you commit:
- `.github/workflows/rebuild.yml` made it up. Browsers sometimes skip dot-folders on drag —
  if it's missing, use **Add file → Create new file**, type `.github/workflows/rebuild.yml` as
  the name, and paste the contents in.
- `node_modules` did **not** come along. `.gitignore` excludes it, but drag-and-drop ignores
  `.gitignore`. If you see it in the list, cancel and delete that folder first.

Then **Commit changes**.

### 4. Connect Cloudflare Pages to the repo
In Cloudflare: **Workers & Pages → Create → Pages → Connect to Git**, pick the repo, and set:

- **Build command:** leave empty
- **Build output directory:** `dist`

That's it. `dist/` is committed to the repo already, so Cloudflare has nothing to build — it
just serves the folder. Every push redeploys automatically.

Then add `nearestkickoff.com` under **Custom domains**, and point Porkbun's DNS at it as
described in `DEPLOY.md`.

### 5. Turn the nightly rebuild on
GitHub disables scheduled workflows on new repos until you confirm. Go to the **Actions** tab
and enable workflows. Then hit **Run workflow** on "Nightly fixture refresh" once, by hand, to
watch it work before trusting it.

---

## What the nightly job does

At 04:17 UTC every night, and whenever you push:

1. Re-fetches the eight openfootball league schedules.
2. Merges in the calendar-file leagues from `fixtures-static.json` — without this step every
   rebuild would silently delete two thirds of the map.
3. Runs `ingest/verify.py`, which checks every venue sits on land inside its own country.
4. Rebuilds `dist/` and commits it, which makes Cloudflare redeploy.

**If anything fails, nothing is committed and nothing deploys** — the live site stays on its
last good data. A bad upstream day leaves yesterday's fixtures up rather than publishing a hole.
That is deliberate: wrong data is worse than slightly old data on a site people plan trips with.

You get an email from GitHub when a run fails. That email *is* the freshness alerting — it tells
you a league changed something the parser didn't expect, usually before a user notices.

## What the nightly job does NOT do

It refreshes the eight leagues that have a machine-readable feed. The calendar-file leagues —
Serie B and C, the EFL, the Bundesliga 2, the Scottish Premiership, and the ten voetbalkrant
`.ics` feeds — come from published PDFs and calendar files in `calendars/`, and those only
change when a league republishes its schedule.

When one does, download the new file, drop it in `calendars/` with the **same filename pattern**
(`ingest/calendars.py` maps filename fragments to parsers), and run the full ingest locally:

    python3 ingest/calendars.py calendars/*
    python3 ingest/build.py
    python3 ingest/verify.py
    ./build-site.sh

Austria, Switzerland and Denmark are **partial seasons** and will need exactly this once those
leagues publish their post-split fixtures.
