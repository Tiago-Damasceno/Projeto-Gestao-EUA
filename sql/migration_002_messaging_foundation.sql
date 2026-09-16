-- Migration 002: secure multi-company messaging and webhook idempotency.
-- Apply after schema.sql and migration_001_gestao23e.sql.

alter table public.leads
  alter column created_by drop not null,
  alter column updated_by drop not null,
  add column if not exists created_via text not null default 'user',
  add column if not exists updated_via text not null default 'user';

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'leads_created_via_check'
      and conrelid = 'public.leads'::regclass
  ) then
    alter table public.leads
      add constraint leads_created_via_check
      check (created_via in ('user', 'integration'));
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'leads_updated_via_check'
      and conrelid = 'public.leads'::regclass
  ) then
    alter table public.leads
      add constraint leads_updated_via_check
      check (updated_via in ('user', 'integration'));
  end if;
end
$$;

create table if not exists public.company_channels (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  provider text not null check (provider in ('twilio')),
  channel_type text not null check (channel_type in ('sms')),
  address text not null check (address ~ '^\+[1-9][0-9]{7,14}$'),
  messaging_service_sid text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (provider, channel_type, address)
);

create unique index if not exists company_channels_one_active_sender_idx
  on public.company_channels (company_id, provider, channel_type)
  where active;

create index if not exists company_channels_destination_idx
  on public.company_channels (provider, address)
  where active;

alter table public.conversations
  add column if not exists channel_id uuid references public.company_channels(id) on delete restrict,
  add column if not exists contact_address text,
  add column if not exists external_thread_id text,
  add column if not exists opted_out_at timestamptz,
  add column if not exists closed_at timestamptz;

create unique index if not exists conversations_open_channel_contact_idx
  on public.conversations (company_id, channel_id, contact_address)
  where channel_id is not null
    and contact_address is not null
    and closed_at is null;

alter table public.messages
  add column if not exists company_id uuid references public.companies(id) on delete cascade,
  add column if not exists direction text,
  add column if not exists provider text,
  add column if not exists provider_message_id text,
  add column if not exists delivery_status text,
  add column if not exists media_count integer not null default 0,
  add column if not exists error_code text,
  add column if not exists received_at timestamptz,
  add column if not exists sent_at timestamptz;

update public.messages as message
set company_id = conversation.company_id
from public.conversations as conversation
where message.conversation_id = conversation.id
  and message.company_id is null;

update public.messages
set direction = case when sender_type = 'lead' then 'inbound' else 'outbound' end
where direction is null;

alter table public.messages
  alter column company_id set not null,
  alter column direction set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'messages_direction_check'
      and conrelid = 'public.messages'::regclass
  ) then
    alter table public.messages
      add constraint messages_direction_check
      check (direction in ('inbound', 'outbound'));
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'messages_provider_check'
      and conrelid = 'public.messages'::regclass
  ) then
    alter table public.messages
      add constraint messages_provider_check
      check (provider is null or provider in ('twilio'));
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'messages_delivery_status_check'
      and conrelid = 'public.messages'::regclass
  ) then
    alter table public.messages
      add constraint messages_delivery_status_check
      check (
        delivery_status is null
        or delivery_status in (
          'received', 'accepted', 'queued', 'sending', 'sent', 'delivered',
          'undelivered', 'failed', 'read'
        )
      );
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'messages_media_count_check'
      and conrelid = 'public.messages'::regclass
  ) then
    alter table public.messages
      add constraint messages_media_count_check check (media_count >= 0);
  end if;
end
$$;

create unique index if not exists messages_provider_message_id_idx
  on public.messages (provider, provider_message_id)
  where provider is not null and provider_message_id is not null;

create index if not exists messages_company_created_idx
  on public.messages (company_id, created_at desc);

create table if not exists public.integration_events (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references public.companies(id) on delete cascade,
  channel_id uuid references public.company_channels(id) on delete set null,
  provider text not null check (provider in ('twilio')),
  event_type text not null check (
    event_type in ('inbound_message', 'message_status')
  ),
  provider_event_id text not null,
  status text not null default 'received' check (
    status in ('received', 'processing', 'completed', 'failed', 'ignored')
  ),
  payload jsonb not null default '{}'::jsonb,
  processed_result jsonb,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  last_error text,
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (provider, event_type, provider_event_id)
);

create index if not exists integration_events_pending_idx
  on public.integration_events (status, created_at)
  where status in ('received', 'failed');

create table if not exists public.automation_runs (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  inbound_message_id uuid not null references public.messages(id) on delete cascade,
  provider text not null check (provider in ('openai')),
  model text not null,
  status text not null default 'processing' check (
    status in ('processing', 'completed', 'failed')
  ),
  decision jsonb,
  provider_response_id text,
  attempt_count integer not null default 1 check (attempt_count >= 1),
  last_error text,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (inbound_message_id)
);

create index if not exists automation_runs_company_created_idx
  on public.automation_runs (company_id, created_at desc);

create table if not exists public.outbound_deliveries (
  id uuid primary key default gen_random_uuid(),
  automation_run_id uuid not null unique references public.automation_runs(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  channel_id uuid not null references public.company_channels(id) on delete restrict,
  provider text not null check (provider in ('twilio')),
  status text not null default 'sending' check (
    status in ('sending', 'accepted', 'completed', 'failed', 'unknown')
  ),
  provider_message_id text,
  provider_status text,
  message_id uuid references public.messages(id) on delete set null,
  attempt_count integer not null default 1 check (attempt_count >= 1),
  last_error text,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists outbound_deliveries_provider_message_idx
  on public.outbound_deliveries (provider, provider_message_id)
  where provider_message_id is not null;

drop trigger if exists company_channels_set_updated_at on public.company_channels;
create trigger company_channels_set_updated_at
before update on public.company_channels
for each row execute function public.set_updated_at();

drop trigger if exists integration_events_set_updated_at on public.integration_events;
create trigger integration_events_set_updated_at
before update on public.integration_events
for each row execute function public.set_updated_at();

drop trigger if exists automation_runs_set_updated_at on public.automation_runs;
create trigger automation_runs_set_updated_at
before update on public.automation_runs
for each row execute function public.set_updated_at();

drop trigger if exists outbound_deliveries_set_updated_at on public.outbound_deliveries;
create trigger outbound_deliveries_set_updated_at
before update on public.outbound_deliveries
for each row execute function public.set_updated_at();

alter table public.company_channels enable row level security;
alter table public.integration_events enable row level security;
alter table public.automation_runs enable row level security;
alter table public.outbound_deliveries enable row level security;

revoke all on table public.company_channels from anon, authenticated;
revoke all on table public.integration_events from anon, authenticated;
revoke all on table public.automation_runs from anon, authenticated;
revoke all on table public.outbound_deliveries from anon, authenticated;

grant all on table public.company_channels to service_role;
grant all on table public.integration_events to service_role;
grant all on table public.automation_runs to service_role;
grant all on table public.outbound_deliveries to service_role;
