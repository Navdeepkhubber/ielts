# Moving off local storage — Firestore + production hosting

## What changed

**Before:** users and attempt/progress history lived in `data/progress.db`,
a SQLite file on whatever machine ran `python3 app.py`. That's fine for a
laptop, but breaks the moment you deploy anywhere stateless: platforms
like Cloud Run give every instance a fresh, throwaway disk, so the file
(and everyone's progress) would vanish on the next deploy or restart, and
two instances running at once wouldn't share data at all.

**Now:** both live in **Firestore**, in the same Firebase project you
already set up for Authentication. No local database file, nothing to
back up separately, and it works the same whether you're running on your
laptop or with 10 replicas behind a load balancer.

- `lib/auth.py` — user profiles, one Firestore document per account,
  keyed directly by Firebase UID (no more separate local integer id to
  keep in sync — one less moving part than the SQLite version had).
- `lib/storage.py` — attempts, in a flat `attempts` Firestore collection
  with a `user_id` field. Attempt ids are now Firestore's own document
  ids (strings like `"a1B2c3D4"`) instead of SQLite's auto-increment
  integers — I checked `static/js/app.js` and it treats attempt ids as
  opaque tokens throughout, never parsing them as numbers, so this
  didn't require any frontend changes.
- `lib/firebase_admin_setup.py` — one shared Firebase Admin app, used for
  both verifying login tokens and the Firestore client.

**⚠️ This does not migrate old data.** If you had real accounts/attempts
in your local `data/progress.db` before this change, they stay there —
Firestore starts empty. For a dev database with just test signups, that's
nothing to worry about; if you'd already accumulated real progress
history you care about, say so and I'll write a one-off script to copy it
across before you switch over for good. (`data/debug.py` is also now
stale — it queries the old SQLite file directly and won't do anything
useful anymore.)

## One-time Firestore setup

1. In [Firebase Console](https://console.firebase.google.com), open your
   existing project (the same one from the auth setup) → **Build >
   Firestore Database > Create database**. Choose **production mode**
   and pick a region close to you. Still free at normal hobby-project
   volume (Spark plan's free quota is generous for this).
2. **Security rules**: the app's browser code never talks to Firestore
   directly — only your Flask server does, via the Admin SDK, which
   bypasses security rules entirely. So the default locked-down rules
   (deny all client access) are exactly right; you don't need to write
   custom rules. Leave whatever Firestore's "production mode" default
   gives you.
3. **Composite indexes**: the progress-history query filters by
   `user_id` (and optionally `test_id`/`section`) *and* orders by
   `submitted_at` — Firestore requires a composite index for that
   combination. Easiest path: just use the app normally; the first time
   a query needs an index it doesn't have, Firestore returns an error in
   your server logs containing a direct link that creates the exact
   index needed, one click. Do that once per query shape you actually
   use (base history, history filtered by test, history filtered by
   section) and you're done — no manual index authoring required.

## Local development

Nothing changes about how you run it locally:

```
pip install -r requirements.txt
python3 app.py
```

Local dev still uses `serviceAccountKey.json` (or
`FIREBASE_SERVICE_ACCOUNT_JSON`) exactly as before — that credential now
also grants Firestore access, no separate key needed.

## Production deployment (Docker)

A `Dockerfile` is included, plus `requirements-prod.txt` (a trimmed
dependency set — see the comment at its top for why) and `render.yaml`.
The image runs the app with **gunicorn** instead of `python3 app.py` —
the Flask dev server is single-threaded and explicitly documented as
unsafe for real traffic.

```
docker build -t ieltsband .
docker run -p 8080:8080 --env-file .env.production ieltsband
```

Required environment variables in production:

| Variable | Required? | Notes |
|---|---|---|
| `FLASK_SECRET_KEY` | **Yes** | `python3 -c "import secrets; print(secrets.token_hex(32))"`. The app now refuses to start without this outside debug mode — a random per-process key would silently break sessions across gunicorn's multiple worker processes. |
| `FLASK_DEBUG` | Yes | Set to `0`. |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Only off Google Cloud | See below. |

### Recommended for genuinely free hosting: Render

I checked current (2026) free-tier terms before recommending this: Render's
free web services need **no credit card**, include **2 free custom
domains with automatic managed TLS**, and give 750 free instance-hours a
month — enough to run one service continuously. The tradeoff is that a
free service spins down after 15 minutes of no traffic and takes
30–60 seconds to wake up on the next request; fine for a personal/small
project, less fine if you need it always instantly responsive (Render's
paid tier removes this, starting around $7/month, if that ever matters).

Render deploys the `Dockerfile` directly, so:

1. Push this repo to GitHub (Render deploys from a Git repo).
2. In the Render dashboard: **New > Web Service**, connect the repo,
   Render auto-detects the `Dockerfile`, and (if you keep `render.yaml`)
   picks up its config automatically.
3. **Environment > Secret Files**: upload your downloaded Firebase
   service account key, named `serviceAccountKey.json`. `render.yaml`
   already sets `FIREBASE_SERVICE_ACCOUNT_JSON` to the path Render mounts
   secret files at, so nothing else to configure there.
4. **Environment > Environment Variables**: set `FLASK_SECRET_KEY` to a
   generated value (see table above). `FLASK_DEBUG=0` is already set by
   `render.yaml`.
5. Deploy. You'll get a `<something>.onrender.com` URL immediately.
6. **Settings > Custom Domains > Add Custom Domain**, enter
   `IELTSBand.com`. Render shows you the exact DNS record(s) to add at
   your domain registrar (this varies by registrar setup, which is why
   I'm not guessing exact values here) — add them, and Render provisions
   a free TLS certificate once DNS verifies.
7. Add `IELTSBand.com` (and `www.IELTSBand.com` if you'll use it) to
   **Firebase Console > Authentication > Settings > Authorized domains**
   — sign-in silently fails on any domain not in that list, and it's easy
   to forget when moving off `localhost`.

### Alternative: Cloud Run + Firebase Hosting

Worth knowing before you pick this: as of a February 2026 policy change,
Google Cloud now requires a **linked billing account (credit card) even
to use Cloud Run's free tier** — you won't be charged as long as you stay
within the free monthly quota (2 million requests, generous CPU/memory
seconds), but the card requirement itself is real, unlike Render. If
that's fine and you'd rather stay inside the Google ecosystem you're
already using for Firebase (no cold-start sleep, scales further if this
ever gets real traffic):

1. **Deploy the container to Cloud Run**, in the *same* GCP project as
   your Firebase app:
   ```
   gcloud run deploy ieltsband \
     --source . \
     --region <pick one near you> \
     --set-env-vars FLASK_SECRET_KEY=<the value you generated>,FLASK_DEBUG=0 \
     --allow-unauthenticated
   ```
   Leave `FIREBASE_SERVICE_ACCOUNT_JSON` unset — Cloud Run's attached
   service account already has access to your project's Firebase/Firestore
   data via Application Default Credentials, so there's no key file to
   manage or leak in this path at all.
2. **Point Firebase Hosting at it**, so `IELTSBand.com` serves the app
   with a free managed SSL certificate:
   ```
   firebase init hosting   # choose "Configure as a single-page app": No
   ```
   In the generated `firebase.json`, add a rewrite:
   ```json
   {
     "hosting": {
       "rewrites": [
         { "source": "**", "run": { "serviceId": "ieltsband", "region": "<same region as above>" } }
       ]
     }
   }
   ```
   Then `firebase deploy --only hosting`, and in Firebase Console →
   Hosting → **Add custom domain**, enter `IELTSBand.com` and follow the
   DNS verification steps. Firebase provisions the certificate
   automatically.
3. Add `IELTSBand.com` (and `www.IELTSBand.com` if used) to
   **Authentication > Settings > Authorized domains**, same as above.

### Other hosts (Railway, Fly.io, a plain VPS)

All work fine with the same `Dockerfile` (it already installs from
`requirements-prod.txt`) — they just don't get Render's zero-card free
tier or Cloud Run's zero-config credential trick. Set
`FIREBASE_SERVICE_ACCOUNT_JSON` to wherever you've mounted the downloaded
service account key as a secret file (each platform has its own
mechanism for this), plus `FLASK_SECRET_KEY` and `FLASK_DEBUG=0` as above.

## CI/CD (GitHub Actions)

One thing worth being clear about: **Render already deploys on every push**
once you connect the GitHub repo — that's its default behavior, nothing
to build for that part. What was actually missing is the "integration"
half — nothing checked that a given push was even safe to deploy. That's
what `.github/workflows/ci-cd.yml` adds.

On every push and pull request against `main`, it:

1. **Runs the test suite** (`app_tests/`, via `pytest`) — 12 tests
   covering the auth gate (anonymous visitors get redirected/401'd),
   the Firebase session flow (verified email logs in, unverified is
   rejected, Google sign-in bypasses email verification), the full
   attempt lifecycle (start → submit → history → detail → band
   explanation), the manual-score-then-refuse-remark guard, cross-user
   isolation (Bob can't see or touch Alice's attempts), and logout. These
   run against an in-memory fake Firestore (`app_tests/fake_firestore.py`)
   — no live Firebase project or credentials needed in CI.
2. **Validates the production Docker image actually builds**
   (`docker build`, using the same `Dockerfile` that ships to Render) —
   catches a broken `requirements-prod.txt` or Dockerfile edit before it
   reaches production, rather than finding out when Render's build fails.
3. **On `main` only, after both pass**: optionally triggers a deploy.

That third step is the actual CI**/CD** connection, and it's opt-in:

- **If you do nothing further**: Render's own auto-deploy (already
  enabled by default when you connected the repo) fires independently,
  regardless of whether the GitHub Actions tests passed. You get CI
  (test/build feedback on every PR) but deploys aren't actually gated by
  it — a red CI run and a live deploy could both happen from the same
  broken push.
- **To make tests actually gate the deploy** (recommended): in Render,
  go to the service → **Settings → Build & Deploy → Auto-Deploy**, turn
  it **off**. Then **Settings → Deploy Hook**, copy the URL shown there.
  In GitHub, go to the repo → **Settings → Secrets and variables →
  Actions → New repository secret**, name it `RENDER_DEPLOY_HOOK_URL`,
  paste the value. Now a push to `main` only reaches production if both
  the test suite and the Docker build succeed first — a broken push
  just... doesn't deploy, instead of deploying broken.

Run the tests locally the same way CI does, any time:
```
pip install -r requirements-prod.txt -r requirements-test.txt
pytest app_tests -v
```

## Subdomain: app.ieltsband.com

Login, signup, and the app itself all live at `app.ieltsband.com` (the
dashboard as its own clean root URL, not `app.ieltsband.com/app`). This
is **entirely off by default** — it only activates once you set one
environment variable, specifically so local development never needs any
of this (no `/etc/hosts` tricks, no `app.localhost`): every existing
`/login`, `/signup`, `/app` URL keeps working exactly as before unless
you opt in.

Login/signup and the dashboard deliberately share **one** subdomain
rather than two separate ones (`auth.` + `dashboard.`, which an earlier
version of this used) — Render's free tier caps custom domains at 2, and
apex + two subdomains is 3. One subdomain keeps the whole setup inside
the free allotment, with no functional downside: login and the
dashboard never needed to be on different hosts, that was just an
earlier design choice.

### 1. Add the environment variable

On Render (or wherever you deploy): **Environment → Environment
Variables** → add `PUBLIC_BASE_DOMAIN` = `ieltsband.com` (no `https://`,
no subdomain — just the bare domain).

### 2. Add the subdomain in Render

**Settings → Custom Domains → Add Custom Domain** → `app.ieltsband.com`.

That's domain #2 (apex is #1) — both fit inside Render's free 2 custom
domains, no extra cost. Render shows the exact DNS record (typically a
`CNAME` pointing at your `<something>.onrender.com` address) — add that
at your domain registrar the same way you did for the apex domain. It
gets its own free managed TLS certificate once DNS verifies.

### 3. Add the subdomain to Firebase's authorized domains

**Firebase Console → Authentication → Settings → Authorized domains** →
add `app.ieltsband.com`. Sign-in silently fails on any domain not in
that list.

### How it works (so `git commit` history explains itself later)

There's deliberately no DNS-level content routing — Render doesn't offer
that for custom domains; every domain you add just points at the same
running service. All the actual "which page for which host" logic lives
in one `before_request` hook in `app.py` (`_route_by_subdomain`), which
only runs at all when `PUBLIC_BASE_DOMAIN` is set:

- Visiting the apex `/login`, `/signup`, or `/app` redirects to
  `app.ieltsband.com` (301 — permanent, since these are the new
  canonical URLs).
- `app.ieltsband.com/` serves the app shell directly if logged in, or
  redirects to `/login` (same host — a plain relative redirect, no
  cross-domain handling needed at all now) if not.
- The Flask session cookie is configured (only when `PUBLIC_BASE_DOMAIN`
  is set) with `SESSION_COOKIE_DOMAIN=".ieltsband.com"`, so a session is
  recognized on both the apex and the subdomain — mostly relevant for an
  old bookmark straight to the apex's `/app`.
- The `next` param on `/login` only ever accepts same-host relative
  paths now (no allowlist of external hosts needed, unlike the earlier
  two-subdomain version) — a plain, simple open-redirect guard.

I tested all of this (the apex→subdomain redirects, the subdomain-root
behavior both logged in and out, and the open-redirect guard on `next`)
against a version of the app with `PUBLIC_BASE_DOMAIN` set — see
`app_tests/test_subdomains.py`.


## Remote test-content storage (Backblaze B2 or similar)

Test content (`tests/` — PDFs, audio, manifests, answer keys) can now
live in S3-compatible remote storage instead of being baked into the
Docker image. This is what actually solves the "growing library keeps
bloating the deployed image" problem — the image stays a fixed, small
size regardless of how many mocks you add, since the app fetches
content from the bucket on demand instead.

Like every other optional integration in this app, it's **entirely
inert unless configured** — with no `BLOB_*` env vars set, `lib/test_loader.py`
reads straight from the local `tests/` folder exactly as it always has.
Nothing changes for local dev.

### One-time bucket + key setup

1. Create a bucket (you've done this — **Private**, any region).
2. **Create a scoped Application Key** — not the Master key. Two
   reasons, not just one: it's the usual security practice (the Master
   key has account-wide power), but more concretely, **Backblaze's docs
   state the Master key doesn't work with the S3-compatible API at
   all** — since this app talks to B2 over that API (via `boto3`), the
   Master key would fail outright, not just be risky.

   In B2 Console → Application Keys → Add a New Application Key:
   - **Allow Access to Bucket(s)** → your specific bucket (not "All")
   - Also check **"Allow List All Bucket Names"** — required for S3-SDK
     compatibility even on a bucket-restricted key, or you'll hit an
     authorization error
   - Access type: **Read and Write**
   - Copy both the **Key ID** and **Application Key** immediately — the
     secret is shown once, never again

### Environment variables

| Variable | Value |
|---|---|
| `BLOB_BUCKET_NAME` | Your bucket's **name** (not its Bucket ID) |
| `BLOB_ENDPOINT_URL` | e.g. `https://s3.ca-east-006.backblazeb2.com` — the region-specific endpoint your bucket's page shows |
| `BLOB_KEY_ID` | The scoped key's Key ID |
| `BLOB_APPLICATION_KEY` | The scoped key's secret |

Set all four in Render (or wherever you deploy) and locally (a `.env`
file, or exported in your shell) once you're ready to switch over.

### Uploading your existing test library

```
pip install -r requirements.txt   # picks up boto3
python3 scripts/sync_tests_to_blob_storage.py --dry-run   # see what would upload
python3 scripts/sync_tests_to_blob_storage.py             # actually upload
```

Skips files already in the bucket with a matching size, so re-running
it after adding one new mock only uploads what's new. `--mock "Mock 19"`
limits it to a single mock folder. This script is the only thing that
ever writes to the bucket — the deployed app only ever reads from it.

### How it works

`lib/blob_storage.py` wraps a plain `boto3` S3 client. `lib/test_loader.py`'s
`cached_file()` is the one place that decides whether to read from the
local `tests/` folder or fetch-and-cache from the bucket — every other
function (`main_pdf_path`, `audio_path`, `load_answers`, ...) calls
through it, so `lib/pdf_render.py`, `app.py`'s routes, and `lib/scaffold.py`
needed zero changes. Fetched files are cached under `BLOB_CACHE_DIR`
(defaults to `/tmp/ielts-blob-cache`) so a page or audio file is only
downloaded once per container instance's lifetime, not on every
request — on Render specifically, that cache is wiped on every
redeploy/restart (ephemeral disk), so the first request for each file
after a deploy is a little slower while it re-downloads; every request
after that is served from the local cache.

I tested this against a fake in-memory S3 client (`app_tests/fake_s3.py`)
covering: fetch-and-cache, caching actually preventing a second download,
a missing-object 404, bucket listing, the upload path, and — the
property that matters most — that `test_loader.py` behaves identically
to the pre-B2 version when nothing is configured. See
`app_tests/test_blob_storage.py`.

### Switching providers later

Cloudflare R2, Wasabi, and DigitalOcean Spaces all speak the same S3
API `boto3` already uses here — moving to any of them later is a matter
of changing `BLOB_ENDPOINT_URL` and the credentials, not touching code.

## What's still local (and why)

Test content (`tests/`) is now **optionally** remote (see the section
above) — baked into the image only if you haven't configured
`BLOB_*`. What's genuinely still local, always:

- **Scaffolding itself.** Turning a freshly-dumped, unscanned mock
  folder into `manifest.json` + answer files (`lib/scaffold.py`,
  `lib/answer_key.py`) is a local authoring step, not something the
  deployed app does. Those tools (plus `fill_answer_keys_local.py`,
  `scripts/diagnose_mock.py`, `lib/report.py`) still work directly
  against your local `tests/` folder exactly as before — they're for
  *before* you upload, not something the server needs at runtime.
- The background auto-scaffolder (`scan_and_scaffold`, triggered from
  `app.py`'s `__main__` block) only runs under `python3 app.py`, not
  under gunicorn/Docker — intentionally, since scaffolding writes files
  to disk, and in production you want content already scaffolded (and,
  now, already uploaded) *before* you deploy, not scanned at container
  startup. Scaffold locally, sync to blob storage, then deploy.