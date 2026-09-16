import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .errors import ApiError


STAGES = {
    "new",
    "contacted",
    "qualified",
    "visit_scheduled",
    "estimate_sent",
    "follow_up",
    "won",
    "lost",
}

AUTOMATION_STATUSES = {
    "ai_active",
    "human_requested",
    "human_active",
    "paused",
    "opted_out",
}

ROLES = {"platform_admin", "marketing_admin", "company_owner", "operator", "viewer"}

CREATE_FIELDS = {
    "full_name",
    "company_name",
    "phone",
    "email",
    "service_type",
    "source",
    "stage",
    "description",
    "address_line",
    "city",
    "state",
    "postal_code",
    "estimated_value",
    "assigned_to",
    "automation_status",
    "next_follow_up_at",
    "last_contact_at",
}

UPDATE_FIELDS = CREATE_FIELDS - {"source"}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def json_object(request):
    if not request.is_json:
        raise ApiError(415, "json_required", "Envie Content-Type: application/json.")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_json", "O corpo deve ser um objeto JSON.")
    return data


def validate_lead(data, *, partial=False):
    allowed = UPDATE_FIELDS if partial else CREATE_FIELDS
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ApiError(
            422,
            "unknown_fields",
            "O corpo contem campos nao permitidos.",
            {"fields": unknown},
        )

    clean = {}
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        clean[key] = value

    if not partial and not clean.get("full_name"):
        raise ApiError(422, "validation_error", "full_name e obrigatorio.")
    if "full_name" in clean:
        require_string(clean, "full_name", 1, 160)
    for field, maximum in {
        "company_name": 160,
        "phone": 40,
        "service_type": 100,
        "source": 80,
        "address_line": 240,
        "city": 100,
        "state": 80,
        "postal_code": 20,
    }.items():
        optional_string(clean, field, maximum)

    if "email" in clean and clean["email"] not in (None, ""):
        require_string(clean, "email", 3, 254)
        if not EMAIL_PATTERN.match(clean["email"]):
            raise ApiError(422, "validation_error", "email invalido.")
        clean["email"] = clean["email"].lower()

    if "description" in clean and clean["description"] is not None:
        require_string(clean, "description", 0, 5000)

    if "stage" in clean and clean["stage"] not in STAGES:
        raise ApiError(
            422,
            "validation_error",
            "stage invalido.",
            {"allowed": sorted(STAGES)},
        )

    if "automation_status" in clean and clean["automation_status"] not in AUTOMATION_STATUSES:
        raise ApiError(
            422,
            "validation_error",
            "automation_status invalido.",
            {"allowed": sorted(AUTOMATION_STATUSES)},
        )

    for field in ("next_follow_up_at", "last_contact_at"):
        if field in clean and clean[field] is not None:
            validate_iso_datetime(clean[field], field)

    if "assigned_to" in clean and clean["assigned_to"] is not None:
        try:
            clean["assigned_to"] = str(uuid.UUID(str(clean["assigned_to"])))
        except (ValueError, AttributeError) as exc:
            raise ApiError(
                422, "validation_error", "assigned_to deve ser um UUID valido."
            ) from exc

    if "estimated_value" in clean and clean["estimated_value"] is not None:
        try:
            value = Decimal(str(clean["estimated_value"]))
        except InvalidOperation as exc:
            raise ApiError(422, "validation_error", "estimated_value invalido.") from exc
        if value < 0 or value > Decimal("9999999999.99"):
            raise ApiError(422, "validation_error", "estimated_value fora do limite.")
        clean["estimated_value"] = str(value.quantize(Decimal("0.01")))

    for nullable in ("company_name", "phone", "email", "description"):
        if clean.get(nullable) == "":
            clean[nullable] = None
    return clean


def validate_company_automation(data):
    allowed = {"automation_enabled", "reason"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ApiError(422, "unknown_fields", "Campos nao permitidos.", {"fields": unknown})
    if "automation_enabled" not in data or not isinstance(data["automation_enabled"], bool):
        raise ApiError(422, "validation_error", "automation_enabled (boolean) e obrigatorio.")
    if data["automation_enabled"] is False and not data.get("reason"):
        raise ApiError(422, "validation_error", "Desligar a automacao exige informar um motivo (reason).")
    return {
        "automation_enabled": data["automation_enabled"],
        "reason": str(data.get("reason", "")).strip()
    }


def validate_conversation_automation(data):
    allowed = {"automation_status", "assigned_operator_id"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ApiError(422, "unknown_fields", "Campos nao permitidos.", {"fields": unknown})
    status = data.get("automation_status")
    if not status or status not in AUTOMATION_STATUSES:
        raise ApiError(422, "validation_error", "automation_status invalido.", {"allowed": sorted(AUTOMATION_STATUSES)})
    result = {"automation_status": status}
    if "assigned_operator_id" in data and data["assigned_operator_id"] is not None:
        try:
            result["assigned_operator_id"] = str(uuid.UUID(str(data["assigned_operator_id"])))
        except (ValueError, AttributeError) as exc:
            raise ApiError(422, "validation_error", "assigned_operator_id deve ser UUID valido.") from exc
    return result


def validate_onboarding(data):
    required = {"profile_data", "company_data", "support_data", "automation_data"}
    missing = required - set(data)
    if missing:
        raise ApiError(422, "validation_error", f"Campos obrigatorios ausentes: {sorted(missing)}")
    return {
        "profile_data": data["profile_data"] if isinstance(data["profile_data"], dict) else {},
        "company_data": data["company_data"] if isinstance(data["company_data"], dict) else {},
        "support_data": data["support_data"] if isinstance(data["support_data"], dict) else {},
        "automation_data": data["automation_data"] if isinstance(data["automation_data"], dict) else {},
        "completed": bool(data.get("completed", True))
    }


def validate_invitation(data):
    if not data.get("email") or not EMAIL_PATTERN.match(str(data["email"]).strip()):
        raise ApiError(422, "validation_error", "email valido e obrigatorio.")
    role = data.get("role", "operator")
    if role not in ROLES:
        raise ApiError(422, "validation_error", "role invalido.", {"allowed": sorted(ROLES)})
    return {
        "email": str(data["email"]).strip().lower(),
        "role": role
    }


def require_string(data, field, minimum, maximum):
    value = data.get(field)
    if not isinstance(value, str) or not (minimum <= len(value) <= maximum):
        raise ApiError(
            422,
            "validation_error",
            f"{field} deve ter entre {minimum} e {maximum} caracteres.",
        )


def optional_string(data, field, maximum):
    if field in data and data[field] is not None:
        require_string(data, field, 0, maximum)


def validate_iso_datetime(value, field):
    if not isinstance(value, str):
        raise ApiError(422, "validation_error", f"{field} deve ser uma data ISO 8601.")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(422, "validation_error", f"{field} deve ser uma data ISO 8601.") from exc

