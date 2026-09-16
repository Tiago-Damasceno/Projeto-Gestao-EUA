import base64
import json

import pytest

from app.auth import SupabaseAuthVerifier
from app.errors import ApiError, UpstreamError
from app.repositories import CRMRepository
from conftest import COMPANY_A_ID, COMPANY_B_ID, LEAD_B_ID, MASTER_USER_ID, USER_A_ID


def jwt_key(role):
    payload = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


@pytest.mark.parametrize("key", ["sb_publishable_test", jwt_key("anon")])
def test_public_config_is_an_explicit_allowlist(app, client, key):
    app.config["SUPABASE_PUBLIC_KEY"] = key
    response = client.get("/auth/config")
    assert response.status_code == 200
    assert response.json == {"url": "https://example.supabase.co", "publicKey": key}
    assert app.config["SUPABASE_SERVICE_ROLE_KEY"] not in response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("key", ["sb_secret_bad", jwt_key("service_role"), "bad-key"])
def test_misconfigured_private_key_is_never_published(app, client, key):
    app.config["SUPABASE_PUBLIC_KEY"] = key
    response = client.get("/auth/config")
    assert response.status_code == 503
    assert key not in response.get_data(as_text=True)


def test_master_enters_dashboard_without_customer_onboarding(client, repository, auth_headers_master):
    repository.get_profile = lambda user_id: None
    response = client.get("/api/v1/me", headers=auth_headers_master)
    assert response.status_code == 200
    assert response.json["data"]["role"] == "platform_admin"
    assert response.json["data"]["onboarding_completed"] is True
    companies = client.get("/api/v1/companies", headers=auth_headers_master).json["data"]
    assert len(companies) == 3


def test_master_reads_and_writes_another_company(client, auth_headers_master):
    response = client.get(f"/api/v1/leads?company_id={COMPANY_B_ID}", headers=auth_headers_master)
    assert response.status_code == 200
    assert response.json["data"][0]["id"] == LEAD_B_ID
    response = client.patch(f"/api/v1/companies/{COMPANY_B_ID}/leads/{LEAD_B_ID}",
                            headers=auth_headers_master, json={"full_name": "Updated by master"})
    assert response.status_code == 200
    assert response.json["data"]["full_name"] == "Updated by master"
    assert client.delete(f"/api/v1/companies/{COMPANY_B_ID}/leads/{LEAD_B_ID}",
                         headers=auth_headers_master).status_code == 204


def test_master_privilege_wins_over_local_viewer_membership(client, repository, auth_headers_master):
    repository.get_membership = lambda company_id, user_id: {"role": "viewer"}
    assert client.delete(f"/api/v1/companies/{COMPANY_B_ID}/leads/{LEAD_B_ID}",
                         headers=auth_headers_master).status_code == 204


@pytest.mark.parametrize("endpoint", ["leads", "dashboard/stats", "conversations", "company/automation"])
def test_ordinary_user_cannot_select_another_company(client, auth_headers_user_a, endpoint):
    response = client.get(f"/api/v1/{endpoint}?company_id={COMPANY_B_ID}", headers=auth_headers_user_a)
    assert response.status_code == 403


def test_ordinary_user_cannot_write_another_company_by_query(client, auth_headers_user_a):
    response = client.patch(f"/api/v1/company/automation?company_id={COMPANY_B_ID}",
                            headers=auth_headers_user_a, json={"automation_enabled": False})
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", f"/api/v1/companies/{COMPANY_B_ID}/leads", {"full_name": "Blocked"}),
        (
            "patch",
            f"/api/v1/companies/{COMPANY_B_ID}/leads/{LEAD_B_ID}",
            {"full_name": "Blocked"},
        ),
        (
            "post",
            f"/api/v1/companies/{COMPANY_B_ID}/leads/{LEAD_B_ID}/stage",
            {"stage": "qualified"},
        ),
    ],
)
def test_marketing_admin_cannot_write_through_scoped_routes(
    client, auth_headers_marketing, method, path, payload
):
    response = getattr(client, method)(path, headers=auth_headers_marketing, json=payload)
    assert response.status_code == 403


def test_email_and_user_metadata_never_grant_master(app, client):
    class ForgedMetadataAuth:
        def verify(self, token):
            return {"id": USER_A_ID, "email": "agencia23e@gmail.com",
                    "user_metadata": {"role": "platform_admin"}}
    app.extensions["auth_verifier"] = ForgedMetadataAuth()
    headers = {"Authorization": "Bearer verified-ordinary-user"}
    me = client.get("/api/v1/me", headers=headers)
    assert me.json["data"]["role"] == "company_owner"
    assert client.get(f"/api/v1/leads?company_id={COMPANY_B_ID}", headers=headers).status_code == 403


def test_repository_explicitly_finds_active_admin_before_other_memberships():
    class Rest:
        def request(self, method, resource, *, params):
            assert resource == "company_members"
            assert params["user_id"] == f"eq.{MASTER_USER_ID}"
            assert params["role"] == "eq.platform_admin"
            assert params["active"] == "eq.true"
            return [{"company_id": COMPANY_A_ID, "role": "platform_admin"}]
    assert CRMRepository(Rest()).get_user_first_membership(MASTER_USER_ID)["role"] == "platform_admin"


def test_admin_lookup_failure_is_not_hidden():
    class Rest:
        def request(self, *args, **kwargs):
            raise UpstreamError()
    with pytest.raises(UpstreamError):
        CRMRepository(Rest()).get_user_first_membership(MASTER_USER_ID)


def test_real_verifier_rejects_supabase_rejected_token(monkeypatch):
    class Response:
        status_code = 401
    monkeypatch.setattr("app.auth.requests.get", lambda *args, **kwargs: Response())
    with pytest.raises(ApiError) as error:
        SupabaseAuthVerifier("https://example.supabase.co", "public").verify("token_fake")
    assert error.value.status_code == 401
