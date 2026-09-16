from types import SimpleNamespace

from conftest import (
    COMPANY_A_ID,
    INTEGRATION_CONV_ID,
    OUTBOUND_MESSAGE_ID,
)
from test_ai_qualification import (
    FakeOpenAI,
    N8N_HEADERS,
    QUALIFY_PATH,
    process_inbound,
)


SEND_PATH = f"/integrations/n8n/conversations/{INTEGRATION_CONV_ID}/send-ai-reply"


class FakeTwilioMessages:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            sid="SM" + "f" * 32,
            status="queued",
        )


class FakeTwilio:
    def __init__(self, error=None):
        self.messages = FakeTwilioMessages(error)


def prepare_qualified_reply(client, app):
    message_id = process_inbound(client, app)
    app.extensions["openai_client"] = FakeOpenAI()
    qualified = client.post(
        QUALIFY_PATH,
        json={"message_id": message_id},
        headers=N8N_HEADERS,
    )
    assert qualified.status_code == 200
    return message_id


def test_qualified_reply_is_sent_and_persisted_once(client, app, repository):
    inbound_message_id = prepare_qualified_reply(client, app)
    twilio_client = FakeTwilio()
    app.extensions["twilio_client"] = twilio_client

    response = client.post(
        SEND_PATH,
        json={"inbound_message_id": inbound_message_id},
        headers=N8N_HEADERS,
    )

    assert response.status_code == 200
    assert response.json["meta"]["already_sent"] is False
    assert response.json["data"]["message_id"] == OUTBOUND_MESSAGE_ID
    assert response.json["data"]["provider_status"] == "queued"
    call = twilio_client.messages.calls[0]
    assert call["to"] == "+5511999999999"
    assert call["from_"] == "+15551230000"
    assert call["status_callback"] == "https://api.example.com/webhooks/twilio/status"
    assert "What city" in call["body"]
    outbound = repository.get_message_by_provider_id("twilio", "SM" + "f" * 32)
    assert outbound["direction"] == "outbound"
    assert outbound["sender_type"] == "ai"

    repeated = client.post(
        SEND_PATH,
        json={"inbound_message_id": inbound_message_id},
        headers=N8N_HEADERS,
    )
    assert repeated.status_code == 200
    assert repeated.json["meta"]["already_sent"] is True
    assert len(twilio_client.messages.calls) == 1
    assert len(repository.outbound_deliveries) == 1
    assert len(repository.messages) == 2


def test_messaging_service_is_used_when_configured(client, app, repository):
    inbound_message_id = prepare_qualified_reply(client, app)
    repository.channels["+15551230000"]["messaging_service_sid"] = (
        "MG" + "1" * 32
    )
    twilio_client = FakeTwilio()
    app.extensions["twilio_client"] = twilio_client

    response = client.post(
        SEND_PATH,
        json={"inbound_message_id": inbound_message_id},
        headers=N8N_HEADERS,
    )

    assert response.status_code == 200
    call = twilio_client.messages.calls[0]
    assert call["messaging_service_sid"] == "MG" + "1" * 32
    assert "from_" not in call


def test_outbound_requires_twilio_configuration(client, app):
    inbound_message_id = prepare_qualified_reply(client, app)
    app.extensions["twilio_client"] = None

    response = client.post(
        SEND_PATH,
        json={"inbound_message_id": inbound_message_id},
        headers=N8N_HEADERS,
    )

    assert response.status_code == 503
    assert response.json["error"]["code"] == "twilio_configuration_error"


def test_uncertain_twilio_failure_is_not_automatically_resent(
    client, app, repository
):
    inbound_message_id = prepare_qualified_reply(client, app)
    twilio_client = FakeTwilio(TimeoutError("network timeout"))
    app.extensions["twilio_client"] = twilio_client

    first = client.post(
        SEND_PATH,
        json={"inbound_message_id": inbound_message_id},
        headers=N8N_HEADERS,
    )
    second = client.post(
        SEND_PATH,
        json={"inbound_message_id": inbound_message_id},
        headers=N8N_HEADERS,
    )

    assert first.status_code == 502
    assert first.json["error"]["code"] == "twilio_delivery_unknown"
    assert second.status_code == 409
    assert second.json["error"]["code"] == "outbound_delivery_busy"
    assert len(twilio_client.messages.calls) == 1
    assert repository.outbound_deliveries[0]["status"] == "unknown"


def test_outbound_rejects_message_without_completed_qualification(client, app):
    inbound_message_id = process_inbound(client, app)
    app.extensions["twilio_client"] = FakeTwilio()

    response = client.post(
        SEND_PATH,
        json={"inbound_message_id": inbound_message_id},
        headers=N8N_HEADERS,
    )

    assert response.status_code == 409
    assert response.json["error"]["code"] == "qualification_not_completed"
    assert repository_company_message_count_is_not_exposed(response)


def repository_company_message_count_is_not_exposed(response):
    return "messages" not in response.json
