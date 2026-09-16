from conftest import (
    COMPANY_A_ID,
    EVENT_A_ID,
    INTEGRATION_CONV_ID,
    INTEGRATION_LEAD_ID,
    MESSAGE_A_ID,
)
from test_twilio_webhook import WEBHOOK_PATH, signed_headers, twilio_form


N8N_HEADERS = {"Authorization": "Bearer test-n8n-shared-secret"}
PROCESS_PATH = f"/integrations/n8n/events/{EVENT_A_ID}/process"


def accept_twilio_event(client, **form_overrides):
    form = twilio_form()
    form.update(form_overrides)
    response = client.post(WEBHOOK_PATH, data=form, headers=signed_headers(form))
    assert response.headers["X-Webhook-Result"] == "accepted"
    return form


def test_n8n_processes_inbound_event_into_crm_records_once(client, repository):
    form = accept_twilio_event(client)

    response = client.post(PROCESS_PATH, headers=N8N_HEADERS)

    assert response.status_code == 200
    assert response.json["meta"]["already_processed"] is False
    assert response.json["data"] == {
        "event_id": EVENT_A_ID,
        "event_type": "inbound_message",
        "company_id": COMPANY_A_ID,
        "lead_id": INTEGRATION_LEAD_ID,
        "conversation_id": INTEGRATION_CONV_ID,
        "message_id": MESSAGE_A_ID,
        "automation_status": "ai_active",
        "contact_address": form["From"],
        "inbound_body": form["Body"],
        "media_count": 0,
        "record_reused": False,
    }
    assert repository.integration_events[0]["status"] == "completed"
    assert repository.integration_events[0]["attempt_count"] == 1
    assert repository.messages[0]["provider_message_id"] == form["MessageSid"]
    assert repository.get_lead(COMPANY_A_ID, INTEGRATION_LEAD_ID)["source"] == "twilio_sms"

    repeated = client.post(PROCESS_PATH, headers=N8N_HEADERS)
    assert repeated.status_code == 200
    assert repeated.json["meta"]["already_processed"] is True
    assert len(repository.messages) == 1
    assert len(repository.leads[COMPANY_A_ID]) == 2
    assert len(repository.conversations[COMPANY_A_ID]) == 2


def test_n8n_routes_reject_invalid_token(client, repository):
    accept_twilio_event(client)

    response = client.post(
        PROCESS_PATH, headers={"Authorization": "Bearer incorrect"}
    )

    assert response.status_code == 401
    assert response.json["error"]["code"] == "invalid_integration_token"
    assert repository.integration_events[0]["status"] == "received"


def test_n8n_routes_fail_closed_when_secret_is_missing(client, app):
    app.config["N8N_SHARED_SECRET"] = ""

    response = client.get("/integrations/n8n/events/pending", headers=N8N_HEADERS)

    assert response.status_code == 503
    assert response.json["error"]["code"] == "n8n_configuration_error"


def test_pending_event_list_excludes_provider_payload(client):
    accept_twilio_event(client)

    response = client.get(
        "/integrations/n8n/events/pending?limit=10", headers=N8N_HEADERS
    )

    assert response.status_code == 200
    assert response.json["data"][0]["id"] == EVENT_A_ID
    assert "payload" not in response.json["data"][0]


def test_stop_message_opts_conversation_out(client, repository):
    accept_twilio_event(client, OptOutType="STOP", Body="STOP")

    response = client.post(PROCESS_PATH, headers=N8N_HEADERS)

    assert response.status_code == 200
    conversation = repository.get_conversation(COMPANY_A_ID, INTEGRATION_CONV_ID)
    assert conversation["automation_status"] == "opted_out"
    assert conversation["opted_out_at"]


def test_processing_failure_is_retryable_and_records_safe_error(client, repository):
    accept_twilio_event(client)
    repository.channels.clear()
    repository.integration_events[0]["channel_id"] = None

    response = client.post(PROCESS_PATH, headers=N8N_HEADERS)

    assert response.status_code == 422
    event = repository.integration_events[0]
    assert event["status"] == "failed"
    assert event["last_error"] == "processing_failed:ApiError"
