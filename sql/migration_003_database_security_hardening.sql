-- Migration 003: make the backend-only Data API policy explicit.
-- Apply after migration_002_messaging_foundation.sql.
--
-- The Flask backend is the only component allowed to access application tables.
-- Supabase Auth still runs in the browser, but browser roles never query these
-- tables directly.

do $$
declare
  target_table text;
begin
  foreach target_table in array array[
    'activity_logs',
    'automation_runs',
    'automation_settings',
    'companies',
    'company_channels',
    'company_members',
    'conversations',
    'escalation_events',
    'integration_events',
    'invitations',
    'lead_stage_events',
    'leads',
    'messages',
    'onboarding_progress',
    'organization_members',
    'organizations',
    'outbound_deliveries',
    'profiles'
  ]
  loop
    execute format(
      'alter table public.%I enable row level security',
      target_table
    );
    execute format(
      'revoke all on table public.%I from public, anon, authenticated',
      target_table
    );

    if not exists (
      select 1
      from pg_policies p
      where p.schemaname = 'public'
        and p.tablename = target_table
        and p.policyname = 'backend_only_deny_browser_roles'
    ) then
      execute format(
        'create policy backend_only_deny_browser_roles
         on public.%I
         as restrictive
         for all
         to anon, authenticated
         using (false)
         with check (false)',
        target_table
      );
    end if;
  end loop;
end
$$;

-- This function is invoked only by the leads trigger. The backend service role
-- already has permission to write both leads and lead_stage_events, so elevated
-- definer privileges are unnecessary.
alter function public.record_lead_stage_event() security invoker;
revoke all on function public.record_lead_stage_event()
  from public, anon, authenticated;
grant execute on function public.record_lead_stage_event() to service_role;

-- Functions are executable by PUBLIC by default in PostgreSQL. Future functions
-- created by the SQL Editor role must be granted deliberately.
alter default privileges for role postgres in schema public
  revoke execute on functions from public, anon, authenticated, service_role;

