-- Run as the trusted database administrator in Supabase SQL Editor.
-- First apply schema.sql, then migration_001_gestao23e.sql.
-- Replace REPLACE_WITH_VERIFIED_AUTH_USER_UUID with the UUID from Authentication > Users.
-- This transaction changes only Tiago's membership/profile and the 23e growth home company.
begin;
do $$
declare
  target_user uuid;
  home_id uuid;
  legacy_id uuid;
begin
  select id into target_user from auth.users
  where id::text = 'REPLACE_WITH_VERIFIED_AUTH_USER_UUID'
    and lower(email) = 'agencia23e@gmail.com'
    and email_confirmed_at is not null;
  if target_user is null then
    raise exception 'Stop: supply the UUID of the verified agencia23e@gmail.com Auth user.';
  end if;

  select id into home_id from public.companies where slug = '23e-growth';
  select id into legacy_id from public.organizations where slug = '23e-growth';
  if home_id is not null and legacy_id is not null and home_id <> legacy_id then
    raise exception 'Stop: 23e growth company and organization IDs differ; review before provisioning.';
  end if;
  home_id := coalesce(home_id, legacy_id, gen_random_uuid());
  -- Keep the legacy organization FK used by leads aligned with the company.
  insert into public.organizations (id, name, slug)
    values (home_id, '23e growth', '23e-growth') on conflict (id) do nothing;
  insert into public.companies (id, name, slug)
    values (home_id, '23e growth', '23e-growth') on conflict (id) do nothing;
  insert into public.company_members (company_id, user_id, role, active)
    values (home_id, target_user, 'platform_admin', true)
    on conflict (company_id, user_id) do update set role = 'platform_admin', active = true;
  insert into public.profiles (id, full_name, onboarding_completed)
    values (target_user, 'Tiago', true)
    on conflict (id) do update set onboarding_completed = true;
end;
$$;
commit;
