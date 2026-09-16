from twilio.request_validator import RequestValidator

from conftest import STATUS_EVENT_ID
from test_ai_qualification import N8N_HEADERS
from test_twilio_outbound import (
    FakeTwilio,
    SEND_PATH,
    prepare_qualified_reply,
)


STATUS_PATH = "/webhooks/twilio/status"
STATUS_URL = f"https://api.example.com{STATUS_PATH}"
AUTH_TOKEN = "test-twilio-auth-token"


def status_form(status="delivered"):
    return {
        "MessageSid": "SM" + "f" * 32,
        "MessageStatus": status,
        "ErrorCode": "",
    }


def signed_status_headers(form, valid=True):
    signature = RequestValidator(AUTH_TOKEN).compute_signature(STATUS_URL, form)
    return {"X-Twilio-Signature": signature if valid else "invalid"}


def create_outbound_message(client, app):
    inbound_message_id = prepare_qualified_reply(client, app)
    app.extensions["twilio_client"] = FakeTwilio()
    sent = client.post(
        SEND_PATH,
        json={"inbound_message_id": inbound_message_id},
        headers=N8N_HEADERS,
    )
    assert sent.status_code == 200


def test_signed_status_callback_updates_stored_message_once(
    client, app, repository
):
    create_outbound_message(client, app)
    form = status_form()

    callback = client.post(
        STATUS_PATH, data=form, headers=signed_status_headers(form)
    )
    repeated = client.post(
        STATUS_PATH, data=form, headers=signed_status_headers(form)
    )

    assert callback.status_code == 200
    assert callback.headers["X-Webhook-Result"] == "accepted"
    assert repeated.headers["X-Webhook-Result"] == "duplicate"
    assert len(repository.integration_events) == 2

    processed = client.post(
        f"/integrations/n8n/events/{STATUS_EVENT_ID}/process",
        headers=N8N_HEADERS,
    )
    assert processed.status_code == 200
    assert processed.json["data"]["delivery_status"] == "delivered"
    outbound = repository.get_message_by_provider_id("twilio", form["MessageSid"])
    assert outbound["delivery_status"] == "delivered"
    assert outbound["error_code"] is None


def test_invalid_status_signature_is_rejected_before_persistence(
    client, app, repository
):
    create_outbound_message(client, app)
    form = status_form("failed")

    response = client.post(
        STATUS_PATH, data=form, headers=signed_status_headers(form, valid=False)
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "invalid_twilio_signature"
    assert len(repository.integration_events) == 1


def test_status_callback_validates_error_code(client, app, repository):
    create_outbound_message(client, app)
    form = status_form("undelivered")
    form["ErrorCode"] = "not-numeric"

    response = client.post(
        STATUS_PATH, data=form, headers=signed_status_headers(form)
    )

    assert response.status_code == 422
    assert response.json["error"]["code"] == "invalid_twilio_payload"
    assert len(repository.integration_events) == 1
