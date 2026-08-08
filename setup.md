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

## Subdomains: auth.ieltsband.com / dashboard.ieltsband.com

Login/signup now live at `auth.ieltsband.com`, and the app itself lives
at `dashboard.ieltsband.com` (as its own clean root URL, not
`dashboard.ieltsband.com/app`). This is **entirely off by default** — it
only activates once you set one environment variable, specifically so
local development never needs any of this (no `/etc/hosts` tricks, no
`dashboard.localhost`): every existing `/login`, `/signup`, `/app` URL
keeps working exactly as before unless you opt in.

### 1. Add the environment variable

On Render (or wherever you deploy): **Environment → Environment
Variables** → add `PUBLIC_BASE_DOMAIN` = `ieltsband.com` (no `https://`,
no subdomain — just the bare domain).

### 2. Add the two subdomains in Render

**Settings → Custom Domains → Add Custom Domain**, once for each:
- `auth.ieltsband.com`
- `dashboard.ieltsband.com`

Render shows the exact DNS record for each (typically a `CNAME` pointing
at your `<something>.onrender.com` address) — add those at your domain
registrar the same way you did for the apex domain. Each gets its own
free managed TLS certificate once DNS verifies.

**Cost note**: Render's Hobby free tier includes 2 free custom domains.
With the apex domain already using one, adding both `auth.` and
`dashboard.` puts you at 3 total — the third costs $0.25/month. Still
effectively free, just not literally $0 anymore if you want all three.

### 3. Add both subdomains to Firebase's authorized domains

**Firebase Console → Authentication → Settings → Authorized domains** —
add:
- `auth.ieltsband.com` (Firebase Auth actually runs here now — Google
  sign-in and email/password both happen on this page)
- `dashboard.ieltsband.com` (the app shell also loads the Firebase SDK,
  just to sign out of the *client-side* Firebase session on logout)

Sign-in silently fails on any domain not in that list.

### How it works (so `git commit` history explains itself later)

There's deliberately no DNS-level content routing — Render doesn't offer
that for custom domains; every domain you add just points at the same
running service. All the actual "which page for which subdomain" logic
lives in one `before_request` hook in `app.py`
(`_route_by_subdomain`), which only runs at all when `PUBLIC_BASE_DOMAIN`
is set:

- Visiting the apex `/login`, `/signup`, or `/app` redirects to the
  matching subdomain (301 — permanent, since these are the new canonical
  URLs).
- `auth.ieltsband.com/` redirects to `/login` on the same subdomain.
- `dashboard.ieltsband.com/` serves the app shell directly if logged in,
  or bounces to `auth.ieltsband.com/login?next=...` if not — and that
  `next` value is validated server-side against a fixed allowlist of our
  own hosts before it's ever honored, so this can't become an
  open-redirect hole via a crafted link.
- The Flask session cookie is configured (only when `PUBLIC_BASE_DOMAIN`
  is set) with `SESSION_COOKIE_DOMAIN=".ieltsband.com"`, so logging in on
  `auth.ieltsband.com` is recognized on `dashboard.ieltsband.com` too —
  by default Flask's session cookie is tied to the exact host that set
  it, which would otherwise mean logging in on one subdomain wouldn't be
  visible on another at all.

I tested all of this (the apex→subdomain redirects, the auth-root
redirect, the dashboard-root behavior both logged in and out, the
shared-cookie-across-subdomains behavior specifically, and the
open-redirect guard on `next`) against a version of the app with
`PUBLIC_BASE_DOMAIN` set — see `app_tests/test_subdomains.py`.

## What's still local (and why)

The mock test content itself — `tests/` (PDFs, audio, manifests, answer
keys) — still lives on disk inside the container image, not in Firestore
or Cloud Storage. That's a deliberate scope line, not an oversight:

- It's static once scaffolded (unlike users/attempts, which change on
  every request), so it doesn't have the "wiped on redeploy" problem —
  whatever's baked into the image at build time is what serves, and
  stays consistent across replicas.
- Moving it to Cloud Storage would mean rewriting `lib/test_loader.py`
  and `lib/pdf_render.py` to fetch/cache from a bucket instead of
  reading local paths — a real chunk of work I haven't done here, since
  it wasn't clearly part of what you asked for.
- If your test library grows large enough that container image size or
  rebuild time becomes annoying, that rewrite is the right next step —
  happy to do it if/when that's actually the bottleneck.

One consequence: the background auto-scaffolder (`scan_and_scaffold`,
triggered from `app.py`'s `__main__` block) only runs under
`python3 app.py`, not under gunicorn/Docker — intentionally, since
scaffolding writes files to disk, and in production you want your
`tests/` folder already scaffolded *before* you build the image, not
scanned at container startup. Scaffold locally, commit/bake in the
result, then deploy.