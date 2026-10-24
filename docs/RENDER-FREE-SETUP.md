# Render Free + Vercel pilot (no Supabase)

This path has no database account, API key, or database password. The directory
uses its built-in SQLite store on Render.

## Render

1. Create a Web Service from `RussMaharic/servo_social_russ`, branch `main`.
2. Choose the Free instance.
3. Use:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `t2-directory --host 0.0.0.0`
   - Health Check Path: `/healthz`
4. Set only `PYTHON_VERSION=3.12.14`. Remove `T2_DATABASE_URL`,
   `T2_SUPABASE_PROJECT_REF`, and `T2_DIRECTORY_REQUIRE_POSTGRES` if they exist.
5. Deploy, then open `https://YOUR-SERVICE.onrender.com/healthz`.

The expected response is:

```json
{"status":"ok","service":"t2-directory"}
```

## Vercel

Set one variable and redeploy:

```text
T2_DIRECTORY_URL=https://YOUR-SERVICE.onrender.com
```

## Free-plan limitation

Render Free has an ephemeral filesystem and spins down after inactivity. A
restart, redeploy, or spin-down can clear the SQLite directory, so pilot users
may need to reclaim their username and reshare their follower. Robot calibration
remains saved on each local computer. Persistent multi-user operation requires
either a paid Render disk or an external database later.
