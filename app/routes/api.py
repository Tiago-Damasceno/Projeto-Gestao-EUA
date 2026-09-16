from datetime import datetime, timezone
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request

from ..auth import require_auth, require_membership
from ..errors import ApiError
from ..validation import (
    STAGES,
    json_object,
    validate_company_automation,
    validate_conversation_automation,
    validate_invitation,
    validate_lead,
    validate_onboarding,
)


api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def get_current_user_company_id():
    user_id = str(g.current_user["id"])
    email = g.current_user.get("email")
    repository = current_app.extensions["crm_repository"]
    membership = repository.get_user_first_membership(user_id)
    if not membership:
        if not repository.is_email_authorized(email):
            raise ApiError(403, "access_not_granted", "Seu acesso ainda não foi liberado.")
        raise ApiError(403, "access_not_granted", "Seu acesso ainda não foi liberado.")
    
    role = membership["role"]
    requested_company_id = request.args.get("company_id")
    
    # Se for papel global (Master ou Marketing) e enviou um company_id especifico, usa ele
    if requested_company_id:
        try:
            requested_company_id = str(UUID(requested_company_id))
        except ValueError:
            raise ApiError(422, "validation_error", "company_id invalido.")
        if role in ("platform_admin", "marketing_admin"):
            return requested_company_id, role
        if requested_company_id != membership["company_id"]:
            raise ApiError(403, "forbidden", "Voce nao tem acesso a esta empresa.")
        
    return membership["company_id"], role


def _deny_if_readonly(role):
    """Permit lead writes only to operational roles."""
    if role not in (
        "platform_admin",
        "company_owner",
        "operator",
        "owner",
        "admin",
        "member",
    ):
        raise ApiError(403, "forbidden", "Seu perfil possui acesso somente leitura.")


@api_bp.get("/me")
@require_auth
def me():
    user = g.current_user
    user_id = str(user["id"])
    repository = current_app.extensions["crm_repository"]
    
    first_membership = repository.get_user_first_membership(user_id)
    profile = repository.get_profile(user_id) or {}
    
    if not first_membership and not repository.is_email_authorized(user.get("email")):
        raise ApiError(403, "access_not_granted", "Seu acesso ainda não foi liberado.")

    company_id = first_membership["company_id"] if first_membership else None
    role = first_membership["role"] if first_membership else None
    onboarding_completed = role == "platform_admin" or profile.get("onboarding_completed", False)

    return jsonify(
        {
            "data": {
                "id": user["id"],
                "email": user.get("email"),
                "full_name": profile.get("full_name") or user.get("user_metadata", {}).get("full_name", ""),
                "company_id": company_id,
                "role": role,
                "onboarding_completed": onboarding_completed,
                "company": first_membership.get("company") if first_membership else None
            }
        }
    )


@api_bp.get("/organizations")
@api_bp.get("/companies")
@require_auth
def list_companies():
    repository = current_app.extensions["crm_repository"]
    rows = repository.list_organizations(str(g.current_user["id"]))
    return jsonify({"data": rows})


@api_bp.get("/dashboard/stats")
@require_auth
def dashboard_stats():
    company_id, _ = get_current_user_company_id()
    repository = current_app.extensions["crm_repository"]
    stats = repository.get_dashboard_stats(company_id)
    return jsonify({"data": stats})


# Rotas de Leads com resolução automatica da empresa do usuário
@api_bp.get("/leads")
@require_auth
def list_my_leads():
    company_id, _ = get_current_user_company_id()
    return list_leads(company_id)


@api_bp.post("/leads")
@require_auth
def create_my_lead():
    company_id, role = get_current_user_company_id()
    _deny_if_readonly(role)
    return create_lead(company_id)


@api_bp.patch("/leads/<uuid:lead_id>")
@require_auth
def update_my_lead(lead_id):
    company_id, role = get_current_user_company_id()
    _deny_if_readonly(role)
    return update_lead(company_id, lead_id)


@api_bp.delete("/leads/<uuid:lead_id>")
@require_auth
def delete_my_lead(lead_id):
    company_id, role = get_current_user_company_id()
    _deny_if_readonly(role)
    return delete_lead(company_id, lead_id)


@api_bp.post('/leads/<uuid:lead_id>/stage')
@require_auth
def move_my_lead(lead_id):
    company_id, role = get_current_user_company_id()
    _deny_if_readonly(role)
    return _move_lead(company_id, lead_id)


# Rotas escopadas por ID da empresa (preservadas e verificadas)
@api_bp.get("/organizations/<uuid:organization_id>/leads")
@api_bp.get("/companies/<uuid:organization_id>/leads")
@require_auth
def list_leads(organization_id):
    require_membership(organization_id)
    stage = request.args.get("stage")
    if stage and stage not in STAGES:
        raise ApiError(422, "validation_error", "Filtro stage invalido.")
    limit = parse_int_query("limit", default=50, minimum=1, maximum=100)
    offset = parse_int_query("offset", default=0, minimum=0, maximum=100000)

    repository = current_app.extensions["crm_repository"]
    rows = repository.list_leads(
        str(organization_id), stage=stage, limit=limit, offset=offset
    )
    return jsonify(
        {"data": rows, "meta": {"limit": limit, "offset": offset, "count": len(rows)}}
    )


@api_bp.post("/organizations/<uuid:organization_id>/leads")
@api_bp.post("/companies/<uuid:organization_id>/leads")
@require_auth
def create_lead(organization_id):
    require_membership(
        organization_id,
        allowed_roles={"company_owner", "operator", "owner", "admin", "member"},
    )
    data = validate_lead(json_object(request))
    repository = current_app.extensions["crm_repository"]
    ensure_assignee_is_member(repository, organization_id, data)
    lead = repository.create_lead(
        str(organization_id), str(g.current_user["id"]), data
    )
    return jsonify({"data": lead}), 201


@api_bp.get("/organizations/<uuid:organization_id>/leads/<uuid:lead_id>")
@api_bp.get("/companies/<uuid:organization_id>/leads/<uuid:lead_id>")
@require_auth
def get_lead(organization_id, lead_id):
    require_membership(organization_id)
    repository = current_app.extensions["crm_repository"]
    lead = repository.get_lead(str(organization_id), str(lead_id))
    if lead is None:
        raise ApiError(404, "lead_not_found", "Lead nao encontrado.")
    return jsonify({"data": lead})


@api_bp.patch("/organizations/<uuid:organization_id>/leads/<uuid:lead_id>")
@api_bp.patch("/companies/<uuid:organization_id>/leads/<uuid:lead_id>")
@require_auth
def update_lead(organization_id, lead_id):
    require_membership(
        organization_id,
        allowed_roles={"company_owner", "operator", "owner", "admin", "member"},
    )
    data = validate_lead(json_object(request), partial=True)
    if not data:
        raise ApiError(422, "validation_error", "Envie ao menos um campo.")
    repository = current_app.extensions["crm_repository"]
    ensure_assignee_is_member(repository, organization_id, data)
    lead = repository.update_lead(
        str(organization_id), str(lead_id), str(g.current_user["id"]), data
    )
    if lead is None:
        raise ApiError(404, "lead_not_found", "Lead nao encontrado.")
    return jsonify({"data": lead})


@api_bp.post("/organizations/<uuid:organization_id>/leads/<uuid:lead_id>/stage")
@api_bp.post("/companies/<uuid:organization_id>/leads/<uuid:lead_id>/stage")
@require_auth
def move_lead(organization_id, lead_id):
    require_membership(
        organization_id,
        allowed_roles={"company_owner", "operator", "owner", "admin", "member"},
    )
    return _move_lead(organization_id, lead_id)


def _move_lead(organization_id, lead_id):
    body = json_object(request)
    if set(body) != {"stage"} or body.get("stage") not in STAGES:
        raise ApiError(
            422,
            "validation_error",
            "Envie apenas um stage valido.",
            {"allowed": sorted(STAGES)},
        )
    repository = current_app.extensions["crm_repository"]
    lead = repository.update_lead(
        str(organization_id),
        str(lead_id),
        str(g.current_user["id"]),
        {"stage": body["stage"]},
    )
    if lead is None:
        raise ApiError(404, "lead_not_found", "Lead nao encontrado.")
    return jsonify({"data": lead})


@api_bp.delete("/organizations/<uuid:organization_id>/leads/<uuid:lead_id>")
@api_bp.delete("/companies/<uuid:organization_id>/leads/<uuid:lead_id>")
@require_auth
def delete_lead(organization_id, lead_id):
    require_membership(organization_id, allowed_roles={"company_owner", "owner", "admin"})
    repository = current_app.extensions["crm_repository"]
    lead = repository.archive_lead(
        str(organization_id),
        str(lead_id),
        str(g.current_user["id"]),
        datetime.now(timezone.utc).isoformat(),
    )
    if lead is None:
        raise ApiError(404, "lead_not_found", "Lead nao encontrado.")
    return "", 204


# Rotas de Conversas e Atendente de IA
@api_bp.get("/conversations")
@require_auth
def list_conversations():
    company_id, _ = get_current_user_company_id()
    repository = current_app.extensions["crm_repository"]
    rows = repository.list_conversations(company_id)
    return jsonify({"data": rows})


@api_bp.get("/conversations/<uuid:conversation_id>/messages")
@require_auth
def list_conversation_messages(conversation_id):
    company_id, _ = get_current_user_company_id()
    repository = current_app.extensions["crm_repository"]
    conversation = repository.get_conversation(company_id, str(conversation_id))
    if conversation is None:
        raise ApiError(404, "conversation_not_found", "Conversa nao encontrada.")
    rows = repository.list_messages(company_id, str(conversation_id))
    return jsonify({"data": rows})


@api_bp.patch("/conversations/<uuid:conversation_id>/automation")
@require_auth
def update_conversation_automation(conversation_id):
    company_id, role = get_current_user_company_id()
    if role not in ("platform_admin", "company_owner", "operator", "owner", "admin"):
        raise ApiError(403, "forbidden", "Sem permissao para alterar a automacao da conversa.")
    
    data = validate_conversation_automation(json_object(request))
    user_id = str(g.current_user["id"])
    
    # Se estiver assumindo a conversa (human_active), atribuir o operador
    if data["automation_status"] == "human_active" and "assigned_operator_id" not in data:
        data["assigned_operator_id"] = user_id

    repository = current_app.extensions["crm_repository"]
    conv = repository.update_conversation_automation(company_id, str(conversation_id), user_id, data)
    if conv is None:
        raise ApiError(404, "conversation_not_found", "Conversa nao encontrada.")
    repository.log_activity(company_id, user_id, "update_conversation_automation", {"conversation_id": str(conversation_id), "status": data["automation_status"]})
    return jsonify({"data": conv})


# Rotas de Automação da Empresa
@api_bp.get("/company/automation")
@require_auth
def get_company_automation():
    company_id, _ = get_current_user_company_id()
    repository = current_app.extensions["crm_repository"]
    settings = repository.get_automation_settings(company_id)
    return jsonify({"data": settings})


@api_bp.patch("/company/automation")
@require_auth
def update_company_automation():
    company_id, role = get_current_user_company_id()
    if role not in ("platform_admin", "company_owner", "owner", "admin"):
        raise ApiError(403, "forbidden", "Apenas o proprietario ou administrador pode alterar a automacao da empresa.")
    
    data = validate_company_automation(json_object(request))
    user_id = str(g.current_user["id"])
    repository = current_app.extensions["crm_repository"]
    
    old_settings = repository.get_automation_settings(company_id)
    updated = repository.update_automation_settings(company_id, user_id, {"automation_enabled": data["automation_enabled"]})
    
    repository.log_activity(
        company_id,
        user_id,
        "toggle_company_automation",
        {
            "previous_state": old_settings.get("automation_enabled", True),
            "new_state": data["automation_enabled"],
            "reason": data.get("reason", "")
        }
    )
    return jsonify({"data": updated})


# Rota de Onboarding
@api_bp.post("/onboarding/complete")
@require_auth
def complete_onboarding():
    company_id, _ = get_current_user_company_id()
    data = validate_onboarding(json_object(request))
    user_id = str(g.current_user["id"])
    repository = current_app.extensions["crm_repository"]
    
    saved = repository.save_onboarding_progress(company_id, data)
    repository.upsert_profile(user_id, {"onboarding_completed": True, "full_name": data["profile_data"].get("name", "")})
    repository.log_activity(company_id, user_id, "onboarding_completed", {})
    return jsonify({"data": saved})


# Rota de Convites Administrativos
@api_bp.post("/admin/invitations")
@require_auth
def create_invitation():
    company_id, role = get_current_user_company_id()
    if role not in ("platform_admin", "company_owner", "owner", "admin"):
        raise ApiError(403, "forbidden", "Apenas administradores podem enviar convites.")
    
    data = validate_invitation(json_object(request))
    user_id = str(g.current_user["id"])
    repository = current_app.extensions["crm_repository"]
    
    invitation = repository.create_invitation(company_id, user_id, data["email"], data["role"])
    repository.log_activity(company_id, user_id, "create_invitation", {"email": data["email"], "role": data["role"]})
    return jsonify({"data": invitation}), 201


def parse_int_query(name, *, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiError(422, "validation_error", f"{name} deve ser inteiro.") from exc
    if not minimum <= value <= maximum:
        raise ApiError(
            422,
            "validation_error",
            f"{name} deve estar entre {minimum} e {maximum}.",
        )
    return value


def ensure_assignee_is_member(repository, organization_id, data):
    assigned_to = data.get("assigned_to")
    if assigned_to and repository.get_membership(str(organization_id), assigned_to) is None:
        raise ApiError(
            422,
            "validation_error",
            "assigned_to precisa ser um membro ativo da empresa.",
        )

