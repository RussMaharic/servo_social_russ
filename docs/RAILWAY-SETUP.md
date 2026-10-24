# Fast Railway + Vercel deployment

This is the shortest deployment path for a pilot. Railway hosts the shared
directory API and its SQLite database; Vercel hosts the browser frontend.
Supabase is not required for this path.

## 1. Deploy the directory on Railway

1. Create a Railway project from the `RussMaharic/servo_social_russ` GitHub repo.
2. Railway detects `requirements.txt` and `main.py`; leave Build Command and
   Start Command empty. If automatic detection is overridden in the dashboard,
   use Build Command `pip install -r requirements.txt` and Start Command
   `python main.py --host 0.0.0.0`.
3. Attach a volume to the service. Any absolute mount path works; `/data` is
   recommended. The app reads Railway's automatically supplied
   `RAILWAY_VOLUME_MOUNT_PATH` and stores `t2-directory.sqlite3` there.
4. Under Networking, generate a public domain.
5. Open `https://YOUR-DOMAIN.up.railway.app/healthz`. It must return
   `{"status":"ok","service":"t2-directory"}`.

Do not set `T2_DATABASE_URL`, `T2_SUPABASE_PROJECT_REF`, or
`T2_DIRECTORY_REQUIRE_POSTGRES` for this Railway/SQLite deployment. No API key
or database password is needed.

## 2. Deploy the frontend on Vercel

1. Import the same GitHub repository into Vercel.
2. Add one environment variable:

   `T2_DIRECTORY_URL=https://YOUR-DOMAIN.up.railway.app`

3. Deploy. The checked-in `vercel.json` builds the static frontend and companion
   downloads with that directory URL.

## Services required

- GitHub: source and automatic deployments.
- Railway: directory API plus one persistent volume.
- Vercel: static frontend.

Nothing else is required for the pilot. Each robot computer still runs its
downloaded local companion because a hosted web page cannot directly own USB
serial hardware.
