from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "migration_002_messaging_foundation.sql"
).read_text(encoding="utf-8")


def test_messaging_migration_enforces_sender_and_event_uniqueness():
    normalized = " ".join(MIGRATION.lower().split())
    assert "alter column created_by drop not null" in normalized
    assert "unique (provider, channel_type, address)" in normalized
    assert "unique (provider, event_type, provider_event_id)" in normalized
    assert "messages_provider_message_id_idx" in normalized
    assert "where active" in normalized


def test_messaging_tables_are_private_to_the_backend():
    normalized = " ".join(MIGRATION.lower().split())
    for table in (
        "company_channels",
        "integration_events",
        "automation_runs",
        "outbound_deliveries",
    ):
        assert f"alter table public.{table} enable row level security" in normalized
        assert f"revoke all on table public.{table} from anon, authenticated" in normalized
        assert f"grant all on table public.{table} to service_role" in normalized
