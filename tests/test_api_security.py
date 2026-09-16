import pytest

from conftest import COMPANY_A_ID, COMPANY_B_ID, CONV_A_ID, LEAD_A_ID, LEAD_B_ID


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_api_requires_bearer_token(client):
    response = client.get(f"/api/v1/companies/{COMPANY_A_ID}/leads")
    assert response.status_code == 401
    assert response.json["error"]["code"] == "authentication_required"


def test_invalid_token_is_rejected(client):
    response = client.get(
        f"/api/v1/companies/{COMPANY_A_ID}/leads",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401
    assert response.json["error"]["code"] == "invalid_token"


def test_unauthorized_user_without_company_returns_403(client, auth_headers_unauthorized):
    response = client.get("/api/v1/me", headers=auth_headers_unauthorized)
    assert response.status_code == 403
    assert response.json["error"]["code"] == "access_not_granted"
    assert "Seu acesso ainda não foi liberado" in response.json["error"]["message"]


def test_isolation_between_companies(client, auth_headers_user_a, auth_headers_user_b):
    # Conta A enxerga apenas leads da Empresa A
    res_a = client.get("/api/v1/leads", headers=auth_headers_user_a)
    assert res_a.status_code == 200
    leads_a = res_a.json["data"]
    assert len(leads_a) == 1
    assert leads_a[0]["full_name"] == "Lead Alfa"

    # Conta B enxerga apenas leads da Empresa B
    res_b = client.get("/api/v1/leads", headers=auth_headers_user_b)
    assert res_b.status_code == 200
    leads_b = res_b.json["data"]
    assert len(leads_b) == 1
    assert leads_b[0]["full_name"] == "Lead Beta"


def test_user_a_cannot_access_or_modify_company_b_lead(client, auth_headers_user_a):
    # Conta A tentando acessar lead da Empresa B recebe 404/403
    response = client.get(
        f"/api/v1/companies/{COMPANY_B_ID}/leads/{LEAD_B_ID}",
        headers=auth_headers_user_a,
    )
    assert response.status_code == 404

    # Conta A tentando alterar lead da Empresa B
    patch_res = client.patch(
        f"/api/v1/companies/{COMPANY_B_ID}/leads/{LEAD_B_ID}",
        headers=auth_headers_user_a,
        json={"full_name": "Invasao Alfa"},
    )
    assert patch_res.status_code == 404


def test_create_lead_and_move_stage(client, auth_headers_user_a):
    create_res = client.post(
        "/api/v1/leads",
        headers=auth_headers_user_a,
        json={"full_name": "Novo Lead Teste", "service_type": "Pintura"},
    )
    assert create_res.status_code == 201
    assert create_res.json["data"]["full_name"] == "Novo Lead Teste"

    lead_id = create_res.json["data"]["id"]

    move_res = client.post(
        f"/api/v1/companies/{COMPANY_A_ID}/leads/{lead_id}/stage",
        headers=auth_headers_user_a,
        json={"stage": "visit_scheduled"},
    )
    assert move_res.status_code == 200
    assert move_res.json["data"]["stage"] == "visit_scheduled"


def test_robot_automation_control_company_and_conversation(client, auth_headers_user_a):
    # Desligar automacao da empresa com motivo
    disable_res = client.patch(
        "/api/v1/company/automation",
        headers=auth_headers_user_a,
        json={"automation_enabled": False, "reason": "Manutencao programada"},
    )
    assert disable_res.status_code == 200
    assert disable_res.json["data"]["automation_enabled"] is False

    # Assumir conversa no nivel da conversa (human_active)
    conv_res = client.patch(
        f"/api/v1/conversations/{CONV_A_ID}/automation",
        headers=auth_headers_user_a,
        json={"automation_status": "human_active"},
    )
    assert conv_res.status_code == 200
    assert conv_res.json["data"]["automation_status"] == "human_active"


def test_operator_cannot_execute_admin_action(client, auth_headers_operator):
    # Operador nao pode alterar automacao geral da empresa
    res_automation = client.patch(
        "/api/v1/company/automation",
        headers=auth_headers_operator,
        json={"automation_enabled": False, "reason": "Tentativa de operador"},
    )
    assert res_automation.status_code == 403

    # Operador nao pode enviar convites
    res_invite = client.post(
        "/api/v1/admin/invitations",
        headers=auth_headers_operator,
        json={"email": "novo@equipe.com", "role": "operator"},
    )
    assert res_invite.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/v1/leads", {"full_name": "Blocked"}),
        ("patch", f"/api/v1/leads/{LEAD_A_ID}", {"full_name": "Blocked"}),
        (
            "post",
            f"/api/v1/leads/{LEAD_A_ID}/stage",
            {"stage": "qualified"},
        ),
        ("post", f"/api/v1/companies/{COMPANY_A_ID}/leads", {"full_name": "Blocked"}),
    ],
)
def test_viewer_cannot_write_leads(
    client, repository, auth_headers_user_a, method, path, payload
):
    repository.role = "viewer"
    response = getattr(client, method)(path, headers=auth_headers_user_a, json=payload)
    assert response.status_code == 403


def test_forged_company_id_in_payload_is_rejected_or_ignored(client, auth_headers_user_a):
    response = client.post(
        "/api/v1/leads",
        headers=auth_headers_user_a,
        json={"full_name": "Lead Malicioso", "company_id": COMPANY_B_ID},
    )
    # Rejeitado por campos desconhecidos no payload ou ignorado com substituição no backend
    assert response.status_code in (422, 201)
    if response.status_code == 201:
        assert response.json["data"]["company_id"] == COMPANY_A_ID
