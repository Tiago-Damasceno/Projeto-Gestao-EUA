import re

from flask import Blueprint, Response, current_app, request
from twilio.request_validator import RequestValidator

from ..errors import ApiError
from ..services import dispatch_integration_event


webhook_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")

E164_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
TWILIO_MESSAGE_SID_PATTERN = re.compile(r"^(?:SM|MM)[A-Za-z0-9]{32}$")


def _signature_url():
    public_base_url = current_app.config.get("PUBLIC_BASE_URL", "")
    if not public_base_url:
        return request.url
    suffix = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
    return f"{public_base_url}{suffix}"


def _validate_twilio_signature():
    auth_token = current_app.config.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        raise ApiError(
            503,
            "twilio_configuration_error",
            "A validacao do webhook Twilio ainda nao foi configurada.",
        )

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature or not RequestValidator(auth_token).validate(
        _signature_url(), request.form, signature
    ):
        raise ApiError(
            403,
            "invalid_twilio_signature",
            "Assinatura do webhook Twilio invalida.",
        )


def _validated_twilio_form():
    _validate_twilio_signature()
    message_sid = str(request.form.get("MessageSid", "")).strip()
    from_address = str(request.form.get("From", "")).strip()
    to_address = str(request.form.get("To", "")).strip()
    body = str(request.form.get("Body", ""))
    try:
        media_count = int(request.form.get("NumMedia", "0"))
    except (TypeError, ValueError) as exc:
        raise ApiError(422, "invalid_twilio_payload", "NumMedia invalido.") from exc

    if not TWILIO_MESSAGE_SID_PATTERN.fullmatch(message_sid):
        raise ApiError(422, "invalid_twilio_payload", "MessageSid invalido.")
    if not E164_PATTERN.fullmatch(from_address) or not E164_PATTERN.fullmatch(to_address):
        raise ApiError(422, "invalid_twilio_payload", "From ou To invalido.")
    if len(body) > 5000 or not 0 <= media_count <= 10:
        raise ApiError(422, "invalid_twilio_payload", "Conteudo da mensagem invalido.")
    if not body and media_count == 0:
        raise ApiError(422, "invalid_twilio_payload", "A mensagem esta vazia.")

    payload = {
        "MessageSid": message_sid,
        "From": from_address,
        "To": to_address,
        "Body": body,
        "NumMedia": str(media_count),
    }
    opt_out_type = request.form.get("OptOutType")
    if opt_out_type:
        payload["OptOutType"] = str(opt_out_type)
    for index in range(media_count):
        for prefix in ("MediaUrl", "MediaContentType"):
            key = f"{prefix}{index}"
            if key in request.form:
                payload[key] = str(request.form[key])
    return payload


def _validated_twilio_status():
    _validate_twilio_signature()
    message_sid = str(request.form.get("MessageSid", "")).strip()
    message_status = str(request.form.get("MessageStatus", "")).strip().lower()
    error_code = str(request.form.get("ErrorCode", "")).strip() or None
    allowed_statuses = {
        "accepted",
        "queued",
        "sending",
        "sent",
        "delivered",
        "undelivered",
        "failed",
        "read",
    }
    if not TWILIO_MESSAGE_SID_PATTERN.fullmatch(message_sid):
        raise ApiError(422, "invalid_twilio_payload", "MessageSid invalido.")
    if message_status not in allowed_statuses:
        raise ApiError(422, "invalid_twilio_payload", "MessageStatus invalido.")
    if error_code is not None and (
        len(error_code) > 20 or not error_code.isdigit()
    ):
        raise ApiError(422, "invalid_twilio_payload", "ErrorCode invalido.")
    return {
        "MessageSid": message_sid,
        "MessageStatus": message_status,
        "ErrorCode": error_code,
    }


@webhook_bp.post("/twilio/inbound")
def twilio_inbound():
    payload = _validated_twilio_form()
    repository = current_app.extensions["crm_repository"]
    channel = repository.get_active_channel("twilio", payload["To"])

    status = "received" if channel else "ignored"
    event = repository.create_integration_event(
        company_id=channel.get("company_id") if channel else None,
        channel_id=channel.get("id") if channel else None,
        provider="twilio",
        event_type="inbound_message",
        provider_event_id=payload["MessageSid"],
        payload=payload,
        status=status,
        last_error=None if channel else "No active company channel matched the destination.",
    )

    result = "duplicate" if event is None else ("accepted" if channel else "unrouted")
    if event is not None and channel:
        dispatch_integration_event(current_app, event)
    return Response(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>",
        status=200,
        mimetype="application/xml",
        headers={"X-Webhook-Result": result},
    )


@webhook_bp.post("/twilio/status")
def twilio_status():
    payload = _validated_twilio_status()
    repository = current_app.extensions["crm_repository"]
    message = repository.get_message_by_provider_id(
        "twilio", payload["MessageSid"]
    )
    event = repository.create_integration_event(
        company_id=message.get("company_id") if message else None,
        channel_id=None,
        provider="twilio",
        event_type="message_status",
        provider_event_id=(
            f"{payload['MessageSid']}:{payload['MessageStatus']}"
        ),
        payload=payload,
        status="received",
        last_error=None,
    )
    if event is not None:
        dispatch_integration_event(current_app, event)
    result = "duplicate" if event is None else "accepted"
    return Response(
        "",
        status=200,
        mimetype="text/plain",
        headers={"X-Webhook-Result": result},
    )
