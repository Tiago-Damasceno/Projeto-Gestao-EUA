from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "migration_003_database_security_hardening.sql"
).read_text(encoding="utf-8")


PRIVATE_TABLES = (
    "activity_logs",
    "automation_runs",
    "automation_settings",
    "companies",
    "company_channels",
    "company_members",
    "conversations",
    "escalation_events",
    "integration_events",
    "invitations",
    "lead_stage_events",
    "leads",
    "messages",
    "onboarding_progress",
    "organization_members",
    "organizations",
    "outbound_deliveries",
    "profiles",
)


def test_all_private_tables_receive_an_explicit_browser_deny_policy():
    normalized = " ".join(MIGRATION.lower().split())

    for table in PRIVATE_TABLES:
        assert f"'{table}'" in normalized
    assert "backend_only_deny_browser_roles" in normalized
    assert "to anon, authenticated using (false) with check (false)" in normalized
    assert "revoke all on table public.%i from public, anon, authenticated" in normalized


def test_trigger_function_does_not_run_with_definer_privileges():
    normalized = " ".join(MIGRATION.lower().split())

    assert (
        "alter function public.record_lead_stage_event() security invoker"
        in normalized
    )
    assert (
        "revoke all on function public.record_lead_stage_event() "
        "from public, anon, authenticated"
        in normalized
    )
    assert (
        "grant execute on function public.record_lead_stage_event() to service_role"
        in normalized
    )


def test_future_public_functions_require_explicit_grants():
    normalized = " ".join(MIGRATION.lower().split())

    assert "alter default privileges for role postgres in schema public" in normalized
    assert (
        "revoke execute on functions from public, anon, authenticated, service_role"
        in normalized
    )
