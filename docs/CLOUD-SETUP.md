# Cloud setup for t2 Connect

Target Supabase project: `fwamzeswdfhqtabakaib`
([SQL Editor](https://supabase.com/dashboard/project/fwamzeswdfhqtabakaib/sql/new)).
No cloud resources have been provisioned or deployed by preparing these files.

## 1. Run the schema in Supabase

Open `supabase/migrations/20261024080538_create_t2_directory.sql`, copy the
contents into the SQL Editor, and run them. The migration creates a private
`t2_directory` schema and a dedicated `t2_directory_app` login role. Existing
application tables are not changed. Do not add this schema to the public Data API.

Then run a separate query, replacing the placeholder with a long random password:

```sql
alter role t2_directory_app password 'YOUR_NEW_LONG_RANDOM_PASSWORD';
```

Use that password only in Render's private database connection setting.
It is the password for this new role, not your Supabase account password.
Do not save a real password in this repository or send it in chat.

You can inspect the result without exposing credentials:

```sql
select schemaname, tablename, rowsecurity
from pg_tables where schemaname = 't2_directory';

select rolname, rolcanlogin, rolsuper, rolbypassrls
from pg_roles where rolname = 't2_directory_app';
```

Expect two tables with row security enabled; the role can log in and is neither
a superuser nor an RLS bypass role. No Supabase Auth users or login screens are used.

## 2. Set Render environment variables

Deploy this repository's `render.yaml` after publishing the local source changes
to your repository. It runs only the directory API. The existing Starter plan
in this Blueprint is paid; review the plan before creating the service.

In your Supabase project's **Connect** dialog select the **transaction pooler**.
Copy the actual host and port; do not infer its region from the project URL.
Use the custom database username `t2_directory_app.fwamzeswdfhqtabakaib` and the
password set above. URL-encode special characters in the password.

Add these in **Render → service → Environment**:

| Name | Value |
| --- | --- |
| `T2_DATABASE_URL` | `postgresql://t2_directory_app.fwamzeswdfhqtabakaib:YOUR_ENCODED_PASSWORD@YOUR_ACTUAL_POOLER_HOST:6543/postgres` |
| `T2_SUPABASE_PROJECT_REF` | `fwamzeswdfhqtabakaib` |
| `T2_DIRECTORY_REQUIRE_POSTGRES` | `1` |

The last two are already declared in `render.yaml`. Only the connection URL
is secret. No Render persistent disk is needed with Supabase storage.
Build command: `pip install '.[directory]'`.
Start command: `t2-directory --host 0.0.0.0` (reads Render's `PORT`).

After deploy, open `https://YOUR-SERVICE.onrender.com/healthz`. It must return
`{"status":"ok","service":"t2-directory"}`. A database failure returns HTTP 503.
The server refuses to silently use temporary SQLite storage if its secret is missing.

## 3. Set Vercel environment variable

Import the same published repository into Vercel with Framework Preset **Other**,
and leave the repository root selected. The checked-in `vercel.json` supplies
the install/build commands and output directory.

Add in **Vercel → project → Settings → Environment Variables**:

```text
T2_DIRECTORY_URL=https://YOUR-SERVICE.onrender.com
```

Set it for each environment you deploy (Preview and Production, for example).
Do not put `T2_DATABASE_URL`, database passwords, service-role keys or private
station credentials in Vercel. The public site only needs the directory address.
The install command installs the Python build tool; the build command generates
the source download and validates a source-only release. Python 3.10+ is required
on users' computers. Standalone signed installers remain a separate release task.

## 4. Check the published flow

1. Open the Vercel site and ensure `release.json` contains the real Render URL.
2. Download the offered source ZIP and verify it opens and includes `START-HERE.txt`.
3. Start the companion locally. Confirm its runtime, then claim a username against
   the Render directory. For an existing development station, change its directory
   address in station settings; calibration and certificates remain local.
4. Add and qualify your follower, then explicitly share it. Use another station
   to check that it appears and can be reserved by only one operator.
5. Connect read-only first. Hardware following still requires explicit enabling.

Local `.env` files are not loaded automatically by the Python launchers. `.env.example`
documents the same variable names; hosting secrets belong in platform settings.
This project currently has local changes that must be committed/pushed before a
Git-based Render/Vercel deploy can include them. Adding dashboard variables alone
does not publish local code. Database network/authentication and the public
deployment still need verification against your actual accounts.
