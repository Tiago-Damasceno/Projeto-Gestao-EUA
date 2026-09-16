# pyrefly: ignore [missing-import]
import pytest

from app import create_app
from app.errors import ApiError


COMPANY_A_ID = "11111111-1111-4111-8111-111111111111"
COMPANY_B_ID = "22222222-2222-4222-8222-222222222222"
COMPANY_23E_ID = "00000000-0000-4000-8000-000000000000"  # 23e Growth (empresa matriz)

USER_A_ID = "33333333-3333-4333-8333-333333333333"
USER_B_ID = "44444444-4444-4444-8444-444444444444"
UNAUTHORIZED_USER_ID = "55555555-5555-4555-8555-555555555555"
MASTER_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MARKETING_USER_ID = "10101010-1010-4010-8010-101010101010"

LEAD_A_ID = "66666666-6666-4666-8666-666666666666"
LEAD_B_ID = "77777777-7777-4777-8777-777777777777"
CONV_A_ID = "88888888-8888-4888-8888-888888888888"
CHANNEL_A_ID = "abababab-abab-4bab-8bab-abababababab"
EVENT_A_ID = "bcbcbcbc-bcbc-4cbc-8cbc-bcbcbcbcbcbc"
STATUS_EVENT_ID = "45454545-4545-4545-8545-454545454545"
MESSAGE_A_ID = "cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd"
INTEGRATION_LEAD_ID = "dededede-dede-4ede-8ede-dededededede"
INTEGRATION_CONV_ID = "efefefef-efef-4fef-8fef-efefefefefef"
RUN_A_ID = "12121212-1212-4212-8212-121212121212"
DELIVERY_A_ID = "23232323-2323-4232-8232-232323232323"
OUTBOUND_MESSAGE_ID = "34343434-3434-4434-8434-343434343434"


class FakeAuth:
    def verify(self, token):
        if token == "token-user-a" or token == "valid-token":
            return {"id": USER_A_ID, "email": "owner_alfa@example.com"}
        if token == "token-user-b":
            return {"id": USER_B_ID, "email": "owner_beta@example.com"}
        if token == "token-operator-a":
            return {"id": "99999999-9999-4999-8999-999999999999", "email": "operator_alfa@example.com"}
        if token == "token-marketing":
            return {"id": MARKETING_USER_ID, "email": "marketing@23egrowth.com"}
        if token == "token-master":
            return {"id": MASTER_USER_ID, "email": "master@23egrowth.com"}
        if token == "token-unauthorized":
            return {"id": UNAUTHORIZED_USER_ID, "email": "unauthorized@example.com"}
        raise ApiError(401, "invalid_token", "Sessao invalida ou expirada.")



class FakeRepository:
    def __init__(self, role="company_owner"):
        self.role = role
        self.archived = False
        self.automation_enabled = True
        self.leads = {
            COMPANY_A_ID: [{"id": LEAD_A_ID, "organization_id": COMPANY_A_ID, "company_id": COMPANY_A_ID, "full_name": "Lead Alfa", "stage": "new"}],
            COMPANY_B_ID: [{"id": LEAD_B_ID, "organization_id": COMPANY_B_ID, "company_id": COMPANY_B_ID, "full_name": "Lead Beta", "stage": "new"}],
        }
        self.conversations = {
            COMPANY_A_ID: [{"id": CONV_A_ID, "company_id": COMPANY_A_ID, "automation_status": "ai_active"}]
        }
        self.activity_logs = []
        self.integration_events = []
        self.messages = []
        self.automation_runs = []
        self.escalation_events = []
        self.outbound_deliveries = []
        self.channels = {
            "+15551230000": {
                "id": CHANNEL_A_ID,
                "company_id": COMPANY_A_ID,
                "provider": "twilio",
                "channel_type": "sms",
                "address": "+15551230000",
            }
        }

    def get_membership(self, organization_id, user_id):
        if user_id == USER_A_ID and str(organization_id) == COMPANY_A_ID:
            return {"role": self.role}
        if user_id == "99999999-9999-4999-8999-999999999999" and str(organization_id) == COMPANY_A_ID:
            return {"role": "operator"}
        if user_id == USER_B_ID and str(organization_id) == COMPANY_B_ID:
            return {"role": "company_owner"}
        # Master e Marketing pertencem à empresa matriz; retorna None para empresas de clientes
        # (auth.py vai elevar via get_user_first_membership)
        if user_id in (MASTER_USER_ID, MARKETING_USER_ID) and str(organization_id) == COMPANY_23E_ID:
            role = "platform_admin" if user_id == MASTER_USER_ID else "marketing_admin"
            return {"role": role}
        return None

    def get_user_first_membership(self, user_id):
        if user_id in (USER_A_ID, "99999999-9999-4999-8999-999999999999"):
            role = self.role if user_id == USER_A_ID else "operator"
            return {"company_id": COMPANY_A_ID, "role": role, "company": {"id": COMPANY_A_ID, "name": "Empresa Alfa", "slug": "empresa-alfa"}}
        if user_id == USER_B_ID:
            return {"company_id": COMPANY_B_ID, "role": "company_owner", "company": {"id": COMPANY_B_ID, "name": "Empresa Beta", "slug": "empresa-beta"}}
        if user_id == MASTER_USER_ID:
            return {"company_id": COMPANY_23E_ID, "role": "platform_admin", "company": {"id": COMPANY_23E_ID, "name": "23e Growth", "slug": "23e-growth"}}
        if user_id == MARKETING_USER_ID:
            return {"company_id": COMPANY_23E_ID, "role": "marketing_admin", "company": {"id": COMPANY_23E_ID, "name": "23e Growth", "slug": "23e-growth"}}
        return None

    def is_email_authorized(self, email):
        return email in (
            "owner_alfa@example.com",
            "owner_beta@example.com",
            "operator_alfa@example.com",
            "marketing@23egrowth.com",
            "master@23egrowth.com",
        )

    def list_organizations(self, user_id):
        first = self.get_user_first_membership(user_id)
        if not first:
            return []
        # Papéis globais enxergam todas as empresas
        if first.get("role") in ("platform_admin", "marketing_admin"):
            all_companies = [
                {"id": COMPANY_23E_ID, "name": "23e Growth", "slug": "23e-growth"},
                {"id": COMPANY_A_ID, "name": "Empresa Alfa", "slug": "empresa-alfa"},
                {"id": COMPANY_B_ID, "name": "Empresa Beta", "slug": "empresa-beta"},
            ]
            return [{"role": first["role"], "company": c, "organization": c} for c in all_companies]
        return [{"role": first["role"], "company": first["company"], "organization": first["company"]}]

    def list_leads(self, organization_id, **kwargs):
        return self.leads.get(str(organization_id), [])

    def get_lead(self, organization_id, lead_id, **kwargs):
        for l in self.leads.get(str(organization_id), []):
            if l["id"] == str(lead_id):
                return l
        return None

    def create_lead(self, organization_id, user_id, data):
        new_lead = {"id": LEAD_A_ID, "organization_id": organization_id, "company_id": organization_id, **data}
        self.leads.setdefault(str(organization_id), []).append(new_lead)
        return new_lead

    def update_lead(self, organization_id, lead_id, user_id, data):
        lead = self.get_lead(organization_id, lead_id)
        if lead:
            lead.update(data)
            return lead
        return None

    def archive_lead(self, organization_id, lead_id, user_id, archived_at):
        lead = self.get_lead(organization_id, lead_id)
        if lead:
            self.archived = True
            return lead
        return None

    def get_profile(self, user_id):
        return {"id": user_id, "full_name": "Usuário Teste", "onboarding_completed": True}

    def upsert_profile(self, user_id, data):
        return {"id": user_id, **data}

    def get_onboarding_progress(self, company_id):
        return {"company_id": company_id, "completed": True}

    def save_onboarding_progress(self, company_id, data):
        return {"company_id": company_id, **data}

    def get_automation_settings(self, company_id):
        return {"company_id": company_id, "automation_enabled": self.automation_enabled}

    def update_automation_settings(self, company_id, user_id, data):
        self.automation_enabled = data.get("automation_enabled", True)
        return {"company_id": company_id, "automation_enabled": self.automation_enabled}

    def list_conversations(self, company_id):
        return self.conversations.get(str(company_id), [])

    def get_active_channel(self, provider, address):
        channel = self.channels.get(address)
        return channel if channel and channel["provider"] == provider else None

    def create_integration_event(self, **data):
        duplicate = any(
            event["provider"] == data["provider"]
            and event["event_type"] == data["event_type"]
            and event["provider_event_id"] == data["provider_event_id"]
            for event in self.integration_events
        )
        if duplicate:
            return None
        event = {
            "id": EVENT_A_ID if not self.integration_events else STATUS_EVENT_ID,
            "attempt_count": 0,
            "processed_result": None,
            **data,
        }
        self.integration_events.append(event)
        return event

    def list_pending_integration_events(self, limit=20):
        return [
            {
                key: event.get(key)
                for key in (
                    "id", "provider", "event_type", "company_id", "status",
                    "attempt_count", "created_at"
                )
            }
            for event in self.integration_events
            if event["status"] in ("received", "failed")
        ][:limit]

    def get_integration_event(self, event_id):
        return next(
            (event for event in self.integration_events if event["id"] == str(event_id)),
            None,
        )

    def claim_integration_event(self, event):
        if event["status"] not in ("received", "failed"):
            return None
        event["status"] = "processing"
        event["attempt_count"] += 1
        event["last_error"] = None
        return event

    def complete_integration_event(self, event_id, result, processed_at):
        event = self.get_integration_event(event_id)
        if not event or event["status"] != "processing":
            return None
        event.update(
            status="completed",
            processed_result=result,
            processed_at=processed_at,
            last_error=None,
        )
        return event

    def fail_integration_event(self, event_id, error):
        event = self.get_integration_event(event_id)
        if event and event["status"] == "processing":
            event.update(status="failed", last_error=error)

    def get_open_conversation(self, company_id, channel_id, contact_address):
        return next(
            (
                conversation
                for conversation in self.conversations.get(str(company_id), [])
                if conversation.get("channel_id") == str(channel_id)
                and conversation.get("contact_address") == contact_address
                and not conversation.get("closed_at")
            ),
            None,
        )

    def get_active_lead_by_phone(self, company_id, phone):
        return next(
            (
                lead
                for lead in reversed(self.leads.get(str(company_id), []))
                if lead.get("phone") == phone and not lead.get("archived_at")
            ),
            None,
        )

    def create_integration_lead(self, company_id, data):
        lead = {
            "id": INTEGRATION_LEAD_ID,
            "organization_id": company_id,
            "company_id": company_id,
            "created_via": "integration",
            "updated_via": "integration",
            **data,
        }
        self.leads.setdefault(str(company_id), []).append(lead)
        return lead

    def touch_integration_lead(self, company_id, lead_id, contacted_at):
        lead = self.get_lead(company_id, lead_id)
        if lead:
            lead.update(last_contact_at=contacted_at, updated_via="integration")
        return lead

    def create_conversation(
        self, company_id, lead_id, channel_id, contact_address, automation_status
    ):
        conversation = {
            "id": INTEGRATION_CONV_ID,
            "company_id": company_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "contact_address": contact_address,
            "automation_status": automation_status,
        }
        self.conversations.setdefault(str(company_id), []).append(conversation)
        return conversation

    def get_message_by_provider_id(self, provider, provider_message_id):
        return next(
            (
                message
                for message in self.messages
                if message.get("provider") == provider
                and message.get("provider_message_id") == provider_message_id
            ),
            None,
        )

    def create_inbound_message(self, data):
        if self.get_message_by_provider_id(
            data["provider"], data["provider_message_id"]
        ):
            return None
        message = {"id": MESSAGE_A_ID, **data}
        self.messages.append(message)
        return message

    def update_conversation_from_inbound(self, company_id, conversation_id, data):
        conversation = self.get_conversation(company_id, conversation_id)
        if conversation:
            conversation.update(data)
        return conversation

    def get_conversation(self, company_id, conversation_id):
        return next(
            (
                conversation
                for conversation in self.conversations.get(str(company_id), [])
                if conversation["id"] == str(conversation_id)
            ),
            None,
        )

    def list_messages(self, company_id, conversation_id, limit=200):
        return [
            message
            for message in self.messages
            if message["company_id"] == str(company_id)
            and message["conversation_id"] == str(conversation_id)
        ][:limit]

    def get_message(self, company_id, conversation_id, message_id):
        return next(
            (
                message
                for message in self.messages
                if message["id"] == str(message_id)
                and message["company_id"] == str(company_id)
                and message["conversation_id"] == str(conversation_id)
            ),
            None,
        )

    def get_conversation_by_id(self, conversation_id):
        for company_id, conversations in self.conversations.items():
            for conversation in conversations:
                if conversation["id"] == str(conversation_id):
                    result = dict(conversation)
                    if conversation.get("lead_id"):
                        result["lead"] = self.get_lead(
                            company_id, conversation["lead_id"]
                        )
                    return result
        return None

    def get_company_ai_context(self, company_id):
        return {
            "company": {"id": company_id, "name": "Empresa Alfa"},
            "settings": {
                "company_id": company_id,
                "automation_enabled": self.automation_enabled,
                "default_ai_prompt_config": {},
            },
        }

    def create_automation_run(
        self, company_id, conversation_id, inbound_message_id, model
    ):
        if self.get_automation_run(inbound_message_id):
            return None
        run = {
            "id": RUN_A_ID,
            "company_id": company_id,
            "conversation_id": conversation_id,
            "inbound_message_id": inbound_message_id,
            "provider": "openai",
            "model": model,
            "status": "processing",
            "attempt_count": 1,
        }
        self.automation_runs.append(run)
        return run

    def get_automation_run(self, inbound_message_id):
        return next(
            (
                run
                for run in self.automation_runs
                if run["inbound_message_id"] == str(inbound_message_id)
            ),
            None,
        )

    def retry_automation_run(self, run):
        if run["status"] != "failed":
            return None
        run.update(
            status="processing",
            attempt_count=run["attempt_count"] + 1,
            last_error=None,
        )
        return run

    def complete_automation_run(
        self, run_id, decision, provider_response_id, completed_at
    ):
        run = next((item for item in self.automation_runs if item["id"] == run_id), None)
        if not run or run["status"] != "processing":
            return None
        run.update(
            status="completed",
            decision=decision,
            provider_response_id=provider_response_id,
            completed_at=completed_at,
            last_error=None,
        )
        return run

    def fail_automation_run(self, run_id, error):
        run = next((item for item in self.automation_runs if item["id"] == run_id), None)
        if run and run["status"] == "processing":
            run.update(status="failed", last_error=error)

    def update_lead_from_automation(self, company_id, lead_id, data):
        lead = self.get_lead(company_id, lead_id)
        if lead:
            lead.update(data, updated_via="integration")
        return lead

    def create_escalation_event(
        self, company_id, conversation_id, lead_id, reason
    ):
        event = {
            "id": len(self.escalation_events) + 1,
            "company_id": company_id,
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "reason": reason,
        }
        self.escalation_events.append(event)
        return event

    def get_channel_by_id(self, company_id, channel_id):
        return next(
            (
                channel
                for channel in self.channels.values()
                if channel["id"] == str(channel_id)
                and channel["company_id"] == str(company_id)
            ),
            None,
        )

    def get_completed_automation_run(
        self, company_id, conversation_id, inbound_message_id
    ):
        return next(
            (
                run
                for run in self.automation_runs
                if run["company_id"] == str(company_id)
                and run["conversation_id"] == str(conversation_id)
                and run["inbound_message_id"] == str(inbound_message_id)
                and run["status"] == "completed"
            ),
            None,
        )

    def create_outbound_delivery(
        self, automation_run_id, company_id, conversation_id, channel_id
    ):
        if self.get_outbound_delivery(automation_run_id):
            return None
        delivery = {
            "id": DELIVERY_A_ID,
            "automation_run_id": automation_run_id,
            "company_id": company_id,
            "conversation_id": conversation_id,
            "channel_id": channel_id,
            "provider": "twilio",
            "status": "sending",
            "attempt_count": 1,
        }
        self.outbound_deliveries.append(delivery)
        return delivery

    def get_outbound_delivery(self, automation_run_id):
        return next(
            (
                delivery
                for delivery in self.outbound_deliveries
                if delivery["automation_run_id"] == str(automation_run_id)
            ),
            None,
        )

    def retry_outbound_delivery(self, delivery):
        if delivery["status"] != "failed":
            return None
        delivery.update(
            status="sending",
            attempt_count=delivery["attempt_count"] + 1,
            last_error=None,
        )
        return delivery

    def accept_outbound_delivery(
        self, delivery_id, provider_message_id, provider_status
    ):
        delivery = next(
            (item for item in self.outbound_deliveries if item["id"] == delivery_id),
            None,
        )
        if not delivery or delivery["status"] != "sending":
            return None
        delivery.update(
            status="accepted",
            provider_message_id=provider_message_id,
            provider_status=provider_status,
            last_error=None,
        )
        return delivery

    def complete_outbound_delivery(self, delivery_id, message_id, completed_at):
        delivery = next(
            (item for item in self.outbound_deliveries if item["id"] == delivery_id),
            None,
        )
        if not delivery or delivery["status"] != "accepted":
            return None
        delivery.update(
            status="completed",
            message_id=message_id,
            completed_at=completed_at,
            last_error=None,
        )
        return delivery

    def mark_outbound_delivery(self, delivery_id, status, error):
        delivery = next(
            (item for item in self.outbound_deliveries if item["id"] == delivery_id),
            None,
        )
        if delivery and delivery["status"] == "sending":
            delivery.update(status=status, last_error=error)

    def create_outbound_message(self, data):
        if self.get_message_by_provider_id(
            data["provider"], data["provider_message_id"]
        ):
            return None
        message = {"id": OUTBOUND_MESSAGE_ID, **data}
        self.messages.append(message)
        return message

    def update_message_delivery_status(self, message_id, delivery_status, error_code):
        message = next(
            (item for item in self.messages if item["id"] == str(message_id)),
            None,
        )
        if message:
            message.update(
                delivery_status=delivery_status,
                error_code=error_code,
            )
        return message

    def update_conversation_automation(self, company_id, conversation_id, user_id, data):
        convs = self.conversations.get(str(company_id), [])
        for c in convs:
            if c["id"] == str(conversation_id):
                c.update(data)
                return c
        return {"id": conversation_id, "company_id": company_id, **data}

    def create_invitation(self, company_id, user_id, email, role):
        return {"id": "inv-123", "company_id": company_id, "email": email, "role": role}

    def log_activity(self, company_id, user_id, action, details):
        self.activity_logs.append({"company_id": company_id, "user_id": user_id, "action": action, "details": details})

    def get_dashboard_stats(self, company_id):
        return {"new_leads": 1, "awaiting_reply": 0, "visits_scheduled": 0, "ai_active": 1, "human_requested": 0, "total_leads": 1}


@pytest.fixture
def repository():
    return FakeRepository()


@pytest.fixture
def app(repository):
    return create_app(
        {
            "TESTING": True,
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_PUBLIC_KEY": "public",
            "SUPABASE_SERVICE_ROLE_KEY": "secret",
            "ALLOWED_ORIGINS": ["http://localhost:3000"],
            "MAX_CONTENT_LENGTH": 1024 * 1024,
            "SUPABASE_TIMEOUT_SECONDS": 1,
            "TWILIO_AUTH_TOKEN": "test-twilio-auth-token",
            "TWILIO_ACCOUNT_SID": "",
            "N8N_SHARED_SECRET": "test-n8n-shared-secret",
            "N8N_INBOUND_WEBHOOK_URL": "",
            "OPENAI_API_KEY": "",
            "OPENAI_MODEL": "gpt-5.6-luna",
            "PUBLIC_BASE_URL": "https://api.example.com",
        },
        auth_verifier=FakeAuth(),
        repository=repository,
    )


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer valid-token"}


@pytest.fixture
def auth_headers_user_a():
    return {"Authorization": "Bearer token-user-a"}


@pytest.fixture
def auth_headers_user_b():
    return {"Authorization": "Bearer token-user-b"}


@pytest.fixture
def auth_headers_operator():
    return {"Authorization": "Bearer token-operator-a"}


@pytest.fixture
def auth_headers_unauthorized():
    return {"Authorization": "Bearer token-unauthorized"}


@pytest.fixture
def auth_headers_master():
    return {"Authorization": "Bearer token-master"}


@pytest.fixture
def auth_headers_marketing():
    return {"Authorization": "Bearer token-marketing"}
