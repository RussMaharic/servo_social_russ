-- Run in the SQL Editor for project fwamzeswdfhqtabakaib.
-- This creates a private directory schema; it does not change existing app tables.
begin;

create schema if not exists t2_directory;
revoke all on schema t2_directory from public, anon, authenticated;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 't2_directory_app') then
    create role t2_directory_app login nosuperuser nocreatedb nocreaterole noreplication nobypassrls;
  end if;
end
$$;

create table if not exists t2_directory.devices (
  id text primary key,
  username text unique not null check (username ~ '^[a-z][a-z0-9_-]{2,23}$'),
  token text not null check (length(token) = 64)
);

create table if not exists t2_directory.followers (
  id text primary key references t2_directory.devices(id),
  label text not null check (length(label) between 1 and 60),
  endpoint text not null,
  certificate text not null,
  seen double precision not null,
  busy integer not null default 0 check (busy in (0, 1)),
  holder text references t2_directory.devices(id),
  held_until double precision not null default 0
);

create index if not exists followers_seen_idx on t2_directory.followers(seen);
alter table t2_directory.devices enable row level security;
alter table t2_directory.followers enable row level security;
revoke all on all tables in schema t2_directory from public, anon, authenticated;

grant usage on schema t2_directory to t2_directory_app;
grant select, insert on t2_directory.devices to t2_directory_app;
grant select, insert, update, delete on t2_directory.followers to t2_directory_app;

-- This role is used only by the Render API. No anon/authenticated policy exists.
drop policy if exists directory_server_devices on t2_directory.devices;
create policy directory_server_devices on t2_directory.devices
  for all to t2_directory_app using (true) with check (true);
drop policy if exists directory_server_followers on t2_directory.followers;
create policy directory_server_followers on t2_directory.followers
  for all to t2_directory_app using (true) with check (true);

commit;

-- After running this migration, set your own database password in a SEPARATE
-- SQL Editor query (do not save a real password in this repository):
-- alter role t2_directory_app password 'YOUR_NEW_LONG_RANDOM_PASSWORD';
