-- Migration 001: 23e Gestão (Fatia Funcional Completa)
-- Seguro, incremental e reversível. Não remove tabelas legadas do PALMACOR.

create extension if not exists pgcrypto;

-- 1. Garantir tabela de empresas (companies)
create table if not exists public.companies (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 160),
  slug text not null unique check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Compatibilidade se a tabela antiga 'organizations' existir
insert into public.companies (id, name, slug, created_at)
select id, name, slug, created_at from public.organizations
on conflict (id) do nothing;

-- 2. Perfis de usuário (profiles)
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text,
  phone text,
  language text default 'pt-BR',
  timezone text default 'America/Sao_Paulo',
  onboarding_completed boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 3. Membros da empresa (company_members)
create table if not exists public.company_members (
  company_id uuid not null references public.companies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'operator' check (role in ('platform_admin', 'marketing_admin', 'company_owner', 'operator', 'viewer')),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (company_id, user_id)
);

-- Migrar membros de organization_members se existirem
insert into public.company_members (company_id, user_id, role, active, created_at)
select organization_id, user_id, 
  case role 
    when 'owner' then 'company_owner'
    when 'admin' then 'company_owner'
    when 'member' then 'operator'
    else 'operator'
  end,
  active, created_at
from public.organization_members
on conflict (company_id, user_id) do nothing;

-- 4. Convites e autorização prévia por e-mail (invitations)
create table if not exists public.invitations (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  email text not null,
  role text not null default 'operator' check (role in ('company_owner', 'operator', 'viewer')),
  token text not null unique default encode(gen_random_bytes(32), 'hex'),
  status text not null default 'pending' check (status in ('pending', 'accepted', 'expired')),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '7 days')
);

create index if not exists invitations_email_status_idx on public.invitations (email, status);

-- 5. Atualizar tabela de leads com colunas adicionais
alter table public.leads add column if not exists company_id uuid references public.companies(id) on delete cascade;
alter table public.leads add column if not exists automation_status text not null default 'ai_active' check (
  automation_status in ('ai_active', 'human_requested', 'human_active', 'paused', 'opted_out')
);

-- Sincronizar company_id com organization_id em leads existentes
update public.leads set company_id = organization_id where company_id is null;

-- 6. Conversas (conversations)
create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  lead_id uuid not null references public.leads(id) on delete cascade,
  automation_status text not null default 'ai_active' check (
    automation_status in ('ai_active', 'human_requested', 'human_active', 'paused', 'opted_out')
  ),
  assigned_operator_id uuid references auth.users(id) on delete set null,
  last_message_at timestamptz default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists conversations_company_status_idx on public.conversations (company_id, automation_status);

-- 7. Mensagens da conversa (messages)
create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  sender_type text not null check (sender_type in ('lead', 'ai', 'human')),
  content text not null,
  raw_payload jsonb,
  created_at timestamptz not null default now()
);

create index if not exists messages_conversation_idx on public.messages (conversation_id, created_at asc);

-- 8. Progresso de Onboarding (onboarding_progress)
create table if not exists public.onboarding_progress (
  company_id uuid primary key references public.companies(id) on delete cascade,
  current_step int not null default 1,
  profile_data jsonb default '{}'::jsonb,
  company_data jsonb default '{}'::jsonb,
  support_data jsonb default '{}'::jsonb,
  automation_data jsonb default '{}'::jsonb,
  completed boolean not null default false,
  updated_at timestamptz not null default now()
);

-- 9. Configurações de Automação por Empresa (automation_settings)
create table if not exists public.automation_settings (
  company_id uuid primary key references public.companies(id) on delete cascade,
  automation_enabled boolean not null default true,
  business_hours jsonb default '{}'::jsonb,
  default_ai_prompt_config jsonb default '{}'::jsonb,
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now()
);

-- 10. Eventos de Transbordo Humano (escalation_events)
create table if not exists public.escalation_events (
  id bigint generated always as identity primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete set null,
  lead_id uuid references public.leads(id) on delete set null,
  reason text not null,
  trigger_command text,
  created_at timestamptz not null default now()
);

-- 11. Logs de Atividades e Auditoria (activity_logs)
create table if not exists public.activity_logs (
  id bigint generated always as identity primary key,
  company_id uuid references public.companies(id) on delete cascade,
  user_id uuid references auth.users(id) on delete set null,
  action text not null,
  details jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists activity_logs_company_idx on public.activity_logs (company_id, created_at desc);

-- Triggers de atualização automática de data
drop trigger if exists companies_set_updated_at on public.companies;
create trigger companies_set_updated_at
before update on public.companies
for each row execute function public.set_updated_at();

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

drop trigger if exists conversations_set_updated_at on public.conversations;
create trigger conversations_set_updated_at
before update on public.conversations
for each row execute function public.set_updated_at();

-- Habilitar RLS em todas as tabelas novas
alter table public.companies enable row level security;
alter table public.profiles enable row level security;
alter table public.company_members enable row level security;
alter table public.invitations enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.onboarding_progress enable row level security;
alter table public.automation_settings enable row level security;
alter table public.escalation_events enable row level security;
alter table public.activity_logs enable row level security;

-- Revogar acesso direto do navegador e conceder estritamente para service_role (Backend Flask)
revoke all on table public.companies from anon, authenticated;
revoke all on table public.profiles from anon, authenticated;
revoke all on table public.company_members from anon, authenticated;
revoke all on table public.invitations from anon, authenticated;
revoke all on table public.conversations from anon, authenticated;
revoke all on table public.messages from anon, authenticated;
revoke all on table public.onboarding_progress from anon, authenticated;
revoke all on table public.automation_settings from anon, authenticated;
revoke all on table public.escalation_events from anon, authenticated;
revoke all on table public.activity_logs from anon, authenticated;

grant all on table public.companies to service_role;
grant all on table public.profiles to service_role;
grant all on table public.company_members to service_role;
grant all on table public.invitations to service_role;
grant all on table public.conversations to service_role;
grant all on table public.messages to service_role;
grant all on table public.onboarding_progress to service_role;
grant all on table public.automation_settings to service_role;
grant all on table public.escalation_events to service_role;
grant all on table public.activity_logs to service_role;
grant usage, select on sequence public.escalation_events_id_seq to service_role;
grant usage, select on sequence public.activity_logs_id_seq to service_role;

-- Exemplo de Seed para Testes Manuais (Duas Empresas Fictícias):
-- insert into public.companies (id, name, slug) values 
--   ('11111111-1111-4111-8111-111111111111', 'Empresa Alfa', 'empresa-alfa'),
--   ('22222222-2222-4222-8222-222222222222', 'Empresa Beta', 'empresa-beta')
-- on conflict (id) do nothing;
