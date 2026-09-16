import hmac
from functools import wraps
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request

from ..errors import ApiError
from ..services import (
    AIQualificationService,
    InboundMessageProcessor,
    TwilioOutboundService,
)


integration_bp = Blueprint(
    "integrations", __name__, url_prefix="/integrations/n8n"
)


def require_n8n_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = current_app.config.get("N8N_SHARED_SECRET", "")
        if not expected:
            raise ApiError(
                503,
                "n8n_configuration_error",
                "The n8n integration has not been configured.",
            )
        authorization = request.headers.get("Authorization", "")
        supplied = (
            authorization[len("Bearer ") :]
            if authorization.startswith("Bearer ")
            else ""
        )
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise ApiError(401, "invalid_integration_token", "Invalid integration token.")
        return view(*args, **kwargs)

    return wrapped


@integration_bp.get("/events/pending")
@require_n8n_auth
def list_pending_events():
    raw_limit = request.args.get("limit", "20")
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ApiError(422, "validation_error", "limit must be an integer.") from exc
    if not 1 <= limit <= 100:
        raise ApiError(422, "validation_error", "limit must be between 1 and 100.")
    repository = current_app.extensions["crm_repository"]
    return jsonify({"data": repository.list_pending_integration_events(limit)})


@integration_bp.post("/events/<uuid:event_id>/process")
@require_n8n_auth
def process_event(event_id):
    repository = current_app.extensions["crm_repository"]
    result, already_processed = InboundMessageProcessor(repository).process(
        str(event_id)
    )
    return jsonify(
        {"data": result, "meta": {"already_processed": already_processed}}
    )


@integration_bp.post("/conversations/<uuid:conversation_id>/qualify")
@require_n8n_auth
def qualify_conversation(conversation_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"message_id"}:
        raise ApiError(
            422,
            "validation_error",
            "The JSON body must contain only message_id.",
        )
    try:
        message_id = str(UUID(str(body["message_id"])))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ApiError(422, "validation_error", "message_id must be a UUID.") from exc

    repository = current_app.extensions["crm_repository"]
    conversation = repository.get_conversation_by_id(str(conversation_id))
    if conversation is None:
        raise ApiError(404, "conversation_not_found", "Conversation not found.")
    message = repository.get_message(
        conversation["company_id"], str(conversation_id), message_id
    )
    if message is None or message.get("direction") != "inbound":
        raise ApiError(404, "inbound_message_not_found", "Inbound message not found.")

    openai_client = current_app.extensions.get("openai_client")
    if openai_client is None:
        raise ApiError(
            503,
            "openai_configuration_error",
            "The OpenAI integration has not been configured.",
        )
    result, already_processed = AIQualificationService(
        repository,
        openai_client,
        current_app.config["OPENAI_MODEL"],
    ).qualify(conversation, message)
    return jsonify(
        {"data": result, "meta": {"already_processed": already_processed}}
    )


@integration_bp.post("/conversations/<uuid:conversation_id>/send-ai-reply")
@require_n8n_auth
def send_ai_reply(conversation_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"inbound_message_id"}:
        raise ApiError(
            422,
            "validation_error",
            "The JSON body must contain only inbound_message_id.",
        )
    try:
        inbound_message_id = str(UUID(str(body["inbound_message_id"])))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ApiError(
            422, "validation_error", "inbound_message_id must be a UUID."
        ) from exc

    repository = current_app.extensions["crm_repository"]
    conversation = repository.get_conversation_by_id(str(conversation_id))
    if conversation is None:
        raise ApiError(404, "conversation_not_found", "Conversation not found.")
    automation_run = repository.get_completed_automation_run(
        conversation["company_id"],
        str(conversation_id),
        inbound_message_id,
    )
    if automation_run is None:
        raise ApiError(
            409,
            "qualification_not_completed",
            "A completed qualification is required before sending.",
        )

    twilio_client = current_app.extensions.get("twilio_client")
    if twilio_client is None:
        raise ApiError(
            503,
            "twilio_configuration_error",
            "Twilio outbound messaging has not been configured.",
        )
    result, already_sent = TwilioOutboundService(
        repository,
        twilio_client,
        current_app.config["PUBLIC_BASE_URL"],
    ).send(conversation, automation_run)
    return jsonify({"data": result, "meta": {"already_sent": already_sent}})
