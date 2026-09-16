-- PALMACOR MVP: execute no SQL Editor de um projeto Supabase novo.
-- Este schema substitui a policy publica do prototipo antigo.

create extension if not exists pgcrypto;

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 160),
  slug text not null unique check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  created_at timestamptz not null default now()
);

create table if not exists public.organization_members (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'member' check (role in ('owner', 'admin', 'member')),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  full_name text not null check (char_length(full_name) between 1 and 160),
  company_name text,
  phone text,
  email text,
  service_type text,
  source text not null default 'manual',
  stage text not null default 'new' check (
    stage in (
      'new', 'contacted', 'qualified', 'visit_scheduled',
      'estimate_sent', 'follow_up', 'won', 'lost'
    )
  ),
  description text,
  address_line text,
  city text,
  state text,
  postal_code text,
  estimated_value numeric(12,2) check (estimated_value >= 0),
  assigned_to uuid references auth.users(id) on delete set null,
  next_follow_up_at timestamptz,
  last_contact_at timestamptz,
  created_by uuid not null references auth.users(id),
  updated_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);

create table if not exists public.lead_stage_events (
  id bigint generated always as identity primary key,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  lead_id uuid not null references public.leads(id) on delete cascade,
  from_stage text,
  to_stage text not null,
  changed_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists leads_org_stage_idx
  on public.leads (organization_id, stage, created_at desc)
  where archived_at is null;
create index if not exists leads_org_follow_up_idx
  on public.leads (organization_id, next_follow_up_at)
  where archived_at is null and next_follow_up_at is not null;
create index if not exists lead_stage_events_lead_idx
  on public.lead_stage_events (lead_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists leads_set_updated_at on public.leads;
create trigger leads_set_updated_at
before update on public.leads
for each row execute function public.set_updated_at();

create or replace function public.record_lead_stage_event()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' or new.stage is distinct from old.stage then
    insert into public.lead_stage_events (
      organization_id, lead_id, from_stage, to_stage, changed_by
    ) values (
      new.organization_id,
      new.id,
      case when tg_op = 'INSERT' then null else old.stage end,
      new.stage,
      new.updated_by
    );
  end if;
  return new;
end;
$$;

drop trigger if exists leads_record_stage on public.leads;
create trigger leads_record_stage
after insert or update on public.leads
for each row execute function public.record_lead_stage_event();

-- Defesa em profundidade: RLS fica ligada mesmo que no futuro alguem conceda
-- acesso direto a um papel do navegador por engano.
alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;
alter table public.leads enable row level security;
alter table public.lead_stage_events enable row level security;

-- O frontend nao acessa as tabelas. Somente o backend usa service_role.
revoke all on table public.organizations from anon, authenticated;
revoke all on table public.organization_members from anon, authenticated;
revoke all on table public.leads from anon, authenticated;
revoke all on table public.lead_stage_events from anon, authenticated;

grant all on table public.organizations to service_role;
grant all on table public.organization_members to service_role;
grant all on table public.leads to service_role;
grant all on table public.lead_stage_events to service_role;
grant usage, select on sequence public.lead_stage_events_id_seq to service_role;
revoke all on function public.record_lead_stage_event()
  from public, anon, authenticated;
grant execute on function public.record_lead_stage_event() to service_role;

-- Depois de criar o primeiro usuario em Authentication > Users, rode:
-- insert into public.organizations (name, slug)
-- values ('Minha empresa', 'minha-empresa') returning id;
--
-- insert into public.organization_members (organization_id, user_id, role)
-- values ('UUID_DA_EMPRESA', 'UUID_DO_USUARIO', 'owner');
