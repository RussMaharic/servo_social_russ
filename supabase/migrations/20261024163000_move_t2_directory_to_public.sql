-- Make the directory tables visible in Supabase's default Table Editor view.
-- They remain server-only: RLS stays enabled and browser roles get no grants.
begin;

do $$
begin
  if to_regclass('public.devices') is not null
     or to_regclass('public.followers') is not null then
    raise exception 'public.devices or public.followers already exists; rename the conflicting table before running this migration';
  end if;
end
$$;

alter table t2_directory.devices set schema public;
alter table t2_directory.followers set schema public;

alter table public.devices enable row level security;
alter table public.followers enable row level security;

revoke all on public.devices, public.followers from public, anon, authenticated;
grant select, insert on public.devices to t2_directory_app;
grant select, insert, update, delete on public.followers to t2_directory_app;

drop policy if exists directory_server_devices on public.devices;
create policy directory_server_devices on public.devices
  for all to t2_directory_app using (true) with check (true);
drop policy if exists directory_server_followers on public.followers;
create policy directory_server_followers on public.followers
  for all to t2_directory_app using (true) with check (true);

drop schema if exists t2_directory;

commit;
