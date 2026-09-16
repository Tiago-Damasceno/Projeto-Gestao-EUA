from twilio.request_validator import RequestValidator
import requests

from conftest import CHANNEL_A_ID, COMPANY_A_ID


WEBHOOK_PATH = "/webhooks/twilio/inbound"
PUBLIC_WEBHOOK_URL = f"https://api.example.com{WEBHOOK_PATH}"
AUTH_TOKEN = "test-twilio-auth-token"


def twilio_form(message_sid="SM" + "a" * 32, to_address="+15551230000"):
    return {
        "MessageSid": message_sid,
        "From": "+5511999999999",
        "To": to_address,
        "Body": "I need a drywall estimate.",
        "NumMedia": "0",
    }


def signed_headers(form, signature="valid"):
    value = (
        RequestValidator(AUTH_TOKEN).compute_signature(PUBLIC_WEBHOOK_URL, form)
        if signature == "valid"
        else "invalid"
    )
    return {"X-Twilio-Signature": value}


def test_signed_inbound_message_is_routed_and_persisted(client, repository):
    form = twilio_form()
    response = client.post(WEBHOOK_PATH, data=form, headers=signed_headers(form))

    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    assert response.headers["X-Webhook-Result"] == "accepted"
    assert len(repository.integration_events) == 1
    event = repository.integration_events[0]
    assert event["company_id"] == COMPANY_A_ID
    assert event["channel_id"] == CHANNEL_A_ID
    assert event["provider_event_id"] == form["MessageSid"]
    assert event["status"] == "received"


def test_invalid_twilio_signature_is_rejected_before_persistence(client, repository):
    form = twilio_form()
    response = client.post(
        WEBHOOK_PATH, data=form, headers=signed_headers(form, signature="invalid")
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "invalid_twilio_signature"
    assert repository.integration_events == []


def test_duplicate_message_sid_is_acknowledged_once(client, repository):
    form = twilio_form()
    headers = signed_headers(form)

    first = client.post(WEBHOOK_PATH, data=form, headers=headers)
    second = client.post(WEBHOOK_PATH, data=form, headers=headers)

    assert first.headers["X-Webhook-Result"] == "accepted"
    assert second.headers["X-Webhook-Result"] == "duplicate"
    assert len(repository.integration_events) == 1


def test_unknown_destination_is_recorded_without_triggering_twilio_retries(
    client, repository
):
    form = twilio_form(to_address="+15559876543")
    response = client.post(WEBHOOK_PATH, data=form, headers=signed_headers(form))

    assert response.status_code == 200
    assert response.headers["X-Webhook-Result"] == "unrouted"
    assert repository.integration_events[0]["company_id"] is None
    assert repository.integration_events[0]["status"] == "ignored"


def test_routed_event_notifies_n8n_without_sending_message_body(
    client, app, monkeypatch
):
    app.config["N8N_INBOUND_WEBHOOK_URL"] = "https://n8n.example.com/webhook/inbound"
    captured = {}

    class SuccessfulResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return SuccessfulResponse()

    monkeypatch.setattr("app.services.n8n_dispatch.requests.post", fake_post)
    form = twilio_form()

    response = client.post(WEBHOOK_PATH, data=form, headers=signed_headers(form))

    assert response.status_code == 200
    assert captured["url"] == app.config["N8N_INBOUND_WEBHOOK_URL"]
    assert captured["json"]["event_id"]
    assert captured["json"]["company_id"] == COMPANY_A_ID
    assert "Body" not in captured["json"]
    assert captured["headers"]["Authorization"] == "Bearer test-n8n-shared-secret"


def test_n8n_notification_failure_does_not_make_twilio_retry(
    client, app, repository, monkeypatch
):
    app.config["N8N_INBOUND_WEBHOOK_URL"] = "https://n8n.example.com/webhook/inbound"

    def fail_post(*args, **kwargs):
        raise requests.ConnectionError("unavailable")

    monkeypatch.setattr("app.services.n8n_dispatch.requests.post", fail_post)
    form = twilio_form()

    response = client.post(WEBHOOK_PATH, data=form, headers=signed_headers(form))

    assert response.status_code == 200
    assert response.headers["X-Webhook-Result"] == "accepted"
    assert repository.integration_events[0]["status"] == "received"
