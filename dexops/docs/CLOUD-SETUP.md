# Vercel UI and Render directory

The repository root deployment files point to this `dexops/` application.
No external database setup or SQL queries are needed.

## Render

For the existing web service, keep Python 3 and branch `main`.

| Setting | Value |
| --- | --- |
| Root Directory | `dexops` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `t2-directory --host 0.0.0.0` |
| Health Check Path | `/healthz` |

`PORT` is supplied by Render. No database credentials are needed. The optional
`T2_DIRECTORY_DB` can point to a persistent disk if the service has one. The
current pilot default uses a local SQLite file; usernames/listings can reset when
the hosting filesystem is replaced. This is the existing pilot behavior.

If Root Directory is left blank, the repository-root `requirements.txt` installs
`./dexops[directory]`, and the same start command works. Prefer setting `dexops`
to make the deployed source explicit.

Check the actual service URL followed by `/healthz`:

```json
{"status":"ok","service":"t2-directory"}
```

## Vercel

Keep Root Directory as the repository root and use the `Other` preset. The root
`vercel.json` runs `python3 dexops/scripts/build-vercel-site.py` and serves
`dexops/src/t2_bots/connect/static`.

Add this build environment variable using your actual directory URL:

```text
T2_DIRECTORY_URL=https://servo-social-russ-1.onrender.com
```

Every build generates release metadata, `bootstrap.py`, and a source ZIP retained
for compatibility. The primary user flow copies a command that clones/reuses the
exact Git commit published in the metadata. Production builds require committed
source so setup cannot fetch a release that is missing the displayed changes.
The approved hosted origins remain
`https://servosocialruss.vercel.app` and `https://play.trydexops.com`.

Deploy the UI before running the website setup command or `dexops update`.
For local asset checks on an uncommitted tree, the builder accepts
`--allow-development`; this option is refused in Vercel builds.
Both users keep their companion process running while using the hosted page.
Public sharing still needs OpenSSH and Pinggy; a reachable LAN/VPN address also
works. Movement requires the same explicit Enable following action as before.
