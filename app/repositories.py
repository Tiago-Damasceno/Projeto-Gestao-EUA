import requests

from .errors import UpstreamError


class SupabaseRestClient:
    """Cliente minimo para a Data API, usado exclusivamente no servidor."""

    def __init__(self, supabase_url, service_role_key, timeout_seconds=8):
        self.base_url = f"{supabase_url}/rest/v1"
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
            }
        )

    def request(self, method, resource, *, params=None, payload=None, prefer=None):
        headers = {"Prefer": prefer} if prefer else None
        try:
            response = self.session.request(
                method,
                f"{self.base_url}/{resource}",
                params=params,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise UpstreamError() from exc

        if response.status_code >= 400:
            # O corpo do Supabase pode conter SQL/nomes internos; nao o repassamos.
            raise UpstreamError()
        if response.status_code == 204 or not response.content:
            return []
        return response.json()


class CRMRepository:
    def __init__(self, client):
        self.client = client

    def get_membership(self, organization_id, user_id):
        rows = self.client.request(
            "GET",
            "company_members",
            params={
                "select": "role",
                "company_id": f"eq.{organization_id}",
                "user_id": f"eq.{user_id}",
                "active": "eq.true",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def get_user_first_membership(self, user_id):
        # Only trusted database provisioning grants this role. Never infer it
        # from email or editable user metadata. Do not hide lookup failures.
        admins = self.client.request(
            "GET", "company_members",
            params={
                "select": "company_id,role,company:companies(id,name,slug)",
                "user_id": f"eq.{user_id}", "active": "eq.true",
                "role": "eq.platform_admin", "order": "created_at.asc", "limit": "1",
            },
        )
        if admins:
            return admins[0]
        rows = self.client.request(
            "GET",
            "company_members",
            params={
                "select": "company_id,role,company:companies(id,name,slug)",
                "user_id": f"eq.{user_id}",
                "active": "eq.true",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def is_email_authorized(self, email):
        if not email:
            return False
        invites = self.client.request(
            "GET",
            "invitations",
            params={
                "select": "id",
                "email": f"eq.{email.lower()}",
                "status": "eq.pending",
                "limit": "1",
            },
        )
        return bool(invites)

    def list_organizations(self, user_id):
        first = self.get_user_first_membership(user_id)
        if not first:
            return []
        
        # Se for platform_admin ou marketing_admin, busca a lista completa de empresas no banco
        if first.get("role") in ("platform_admin", "marketing_admin"):
            companies = self.client.request(
                "GET",
                "companies",
                params={"select": "id,name,slug", "order": "created_at.asc"},
            )
            return [
                {
                    "role": first["role"],
                    "company": comp,
                    "organization": comp,
                }
                for comp in companies
            ]

        return [
            {
                "role": first["role"],
                "company": first["company"],
                "organization": first["company"],
            }
        ]


    def list_leads(self, organization_id, *, stage=None, limit=50, offset=0):
        params = {
            "select": "*",
            "organization_id": f"eq.{organization_id}",
            "archived_at": "is.null",
            "order": "created_at.desc",
            "limit": str(limit),
            "offset": str(offset),
        }
        if stage:
            params["stage"] = f"eq.{stage}"
        rows = self.client.request("GET", "leads", params=params)
        self._attach_lead_card_context(str(organization_id), rows)
        return rows

    def _attach_lead_card_context(self, organization_id, leads):
        """Attach derived display fields without changing stored lead data."""
        lead_ids = [str(lead["id"]) for lead in leads if lead.get("id")]
        if not lead_ids:
            return

        lead_filter = f"in.({','.join(lead_ids)})"
        current_stages = {str(lead["id"]): lead.get("stage") for lead in leads}
        latest_stage_events = {}
        events = self.client.request(
            "GET",
            "lead_stage_events",
            params={
                "select": "lead_id,to_stage,created_at",
                "organization_id": f"eq.{organization_id}",
                "lead_id": lead_filter,
                "order": "created_at.desc",
            },
        )
        for event in events:
            lead_id = str(event.get("lead_id", ""))
            if (
                lead_id not in latest_stage_events
                and event.get("to_stage") == current_stages.get(lead_id)
            ):
                latest_stage_events[lead_id] = event.get("created_at")

        conversations_by_lead = {}
        conversations = self.client.request(
            "GET",
            "conversations",
            params={
                "select": "id,lead_id,last_message_at",
                "company_id": f"eq.{organization_id}",
                "lead_id": lead_filter,
                "order": "last_message_at.desc",
            },
        )
        for conversation in conversations:
            lead_id = str(conversation.get("lead_id", ""))
            if lead_id and lead_id not in conversations_by_lead:
                conversations_by_lead[lead_id] = conversation.get("id")

        for lead in leads:
            lead_id = str(lead.get("id", ""))
            entered_at = latest_stage_events.get(lead_id)
            if entered_at is None and lead.get("stage") == "new":
                entered_at = lead.get("created_at")
            lead["stage_entered_at"] = entered_at
            lead["conversation_id"] = conversations_by_lead.get(lead_id)

    def get_lead(self, organization_id, lead_id, *, include_archived=False):
        params = {
            "select": "*",
            "id": f"eq.{lead_id}",
            "organization_id": f"eq.{organization_id}",
            "limit": "1",
        }
        if not include_archived:
            params["archived_at"] = "is.null"
        rows = self.client.request("GET", "leads", params=params)
        return rows[0] if rows else None

    def create_lead(self, organization_id, user_id, data):
        payload = {
            **data,
            "organization_id": organization_id,
            "company_id": organization_id,
            "created_by": user_id,
            "updated_by": user_id,
        }
        rows = self.client.request(
            "POST",
            "leads",
            payload=payload,
            prefer="return=representation",
        )
        return rows[0]

    def update_lead(self, organization_id, lead_id, user_id, data):
        payload = {**data, "updated_by": user_id}
        rows = self.client.request(
            "PATCH",
            "leads",
            params={
                "id": f"eq.{lead_id}",
                "organization_id": f"eq.{organization_id}",
                "archived_at": "is.null",
            },
            payload=payload,
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def archive_lead(self, organization_id, lead_id, user_id, archived_at):
        return self.update_lead(
            organization_id,
            lead_id,
            user_id,
            {"archived_at": archived_at},
        )

    def get_profile(self, user_id):
        rows = self.client.request(
            "GET",
            "profiles",
            params={"select": "*", "id": f"eq.{user_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    def upsert_profile(self, user_id, data):
        payload = {"id": user_id, **data}
        rows = self.client.request(
            "POST",
            "profiles",
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0] if rows else payload

    def get_onboarding_progress(self, company_id):
        rows = self.client.request(
            "GET",
            "onboarding_progress",
            params={"select": "*", "company_id": f"eq.{company_id}", "limit": "1"},
        )
        return rows[0] if rows else {"completed": False, "current_step": 1}

    def save_onboarding_progress(self, company_id, data):
        payload = {"company_id": company_id, **data}
        rows = self.client.request(
            "POST",
            "onboarding_progress",
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0] if rows else payload

    def get_automation_settings(self, company_id):
        rows = self.client.request(
            "GET",
            "automation_settings",
            params={"select": "*", "company_id": f"eq.{company_id}", "limit": "1"},
        )
        return rows[0] if rows else {"automation_enabled": True}

    def update_automation_settings(self, company_id, user_id, data):
        payload = {"company_id": company_id, "updated_by": user_id, **data}
        rows = self.client.request(
            "POST",
            "automation_settings",
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0] if rows else payload

    def list_conversations(self, company_id):
        return self.client.request(
            "GET",
            "conversations",
            params={
                "select": "*,lead:leads(full_name,phone,email,service_type)",
                "company_id": f"eq.{company_id}",
                "order": "last_message_at.desc",
            },
        )

    def get_active_channel(self, provider, address):
        rows = self.client.request(
            "GET",
            "company_channels",
            params={
                "select": "id,company_id,provider,channel_type,address,messaging_service_sid",
                "provider": f"eq.{provider}",
                "address": f"eq.{address}",
                "active": "eq.true",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def create_integration_event(
        self,
        *,
        company_id,
        channel_id,
        provider,
        event_type,
        provider_event_id,
        payload,
        status="received",
        last_error=None,
    ):
        rows = self.client.request(
            "POST",
            "integration_events",
            params={"on_conflict": "provider,event_type,provider_event_id"},
            payload={
                "company_id": company_id,
                "channel_id": channel_id,
                "provider": provider,
                "event_type": event_type,
                "provider_event_id": provider_event_id,
                "payload": payload,
                "status": status,
                "last_error": last_error,
            },
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return rows[0] if rows else None

    def list_pending_integration_events(self, limit=20):
        return self.client.request(
            "GET",
            "integration_events",
            params={
                "select": "id,provider,event_type,company_id,status,attempt_count,created_at",
                "status": "in.(received,failed)",
                "order": "created_at.asc",
                "limit": str(limit),
            },
        )

    def get_integration_event(self, event_id):
        rows = self.client.request(
            "GET",
            "integration_events",
            params={"select": "*", "id": f"eq.{event_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    def claim_integration_event(self, event):
        if event.get("status") not in ("received", "failed"):
            return None
        rows = self.client.request(
            "PATCH",
            "integration_events",
            params={
                "id": f"eq.{event['id']}",
                "status": f"eq.{event['status']}",
            },
            payload={
                "status": "processing",
                "attempt_count": int(event.get("attempt_count") or 0) + 1,
                "last_error": None,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def complete_integration_event(self, event_id, result, processed_at):
        rows = self.client.request(
            "PATCH",
            "integration_events",
            params={"id": f"eq.{event_id}", "status": "eq.processing"},
            payload={
                "status": "completed",
                "processed_result": result,
                "processed_at": processed_at,
                "last_error": None,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def fail_integration_event(self, event_id, error):
        self.client.request(
            "PATCH",
            "integration_events",
            params={"id": f"eq.{event_id}", "status": "eq.processing"},
            payload={"status": "failed", "last_error": str(error)[:500]},
        )

    def get_open_conversation(self, company_id, channel_id, contact_address):
        rows = self.client.request(
            "GET",
            "conversations",
            params={
                "select": "*",
                "company_id": f"eq.{company_id}",
                "channel_id": f"eq.{channel_id}",
                "contact_address": f"eq.{contact_address}",
                "closed_at": "is.null",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def get_active_lead_by_phone(self, company_id, phone):
        rows = self.client.request(
            "GET",
            "leads",
            params={
                "select": "*",
                "company_id": f"eq.{company_id}",
                "phone": f"eq.{phone}",
                "archived_at": "is.null",
                "order": "created_at.desc",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def create_integration_lead(self, company_id, data):
        payload = {
            **data,
            "organization_id": company_id,
            "company_id": company_id,
            "created_by": None,
            "updated_by": None,
            "created_via": "integration",
            "updated_via": "integration",
        }
        rows = self.client.request(
            "POST", "leads", payload=payload, prefer="return=representation"
        )
        return rows[0]

    def touch_integration_lead(self, company_id, lead_id, contacted_at):
        rows = self.client.request(
            "PATCH",
            "leads",
            params={
                "id": f"eq.{lead_id}",
                "company_id": f"eq.{company_id}",
                "archived_at": "is.null",
            },
            payload={
                "last_contact_at": contacted_at,
                "updated_by": None,
                "updated_via": "integration",
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def create_conversation(
        self, company_id, lead_id, channel_id, contact_address, automation_status
    ):
        rows = self.client.request(
            "POST",
            "conversations",
            payload={
                "company_id": company_id,
                "lead_id": lead_id,
                "channel_id": channel_id,
                "contact_address": contact_address,
                "automation_status": automation_status,
            },
            prefer="return=representation",
        )
        return rows[0]

    def get_message_by_provider_id(self, provider, provider_message_id):
        rows = self.client.request(
            "GET",
            "messages",
            params={
                "select": "*",
                "provider": f"eq.{provider}",
                "provider_message_id": f"eq.{provider_message_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def create_inbound_message(self, data):
        rows = self.client.request(
            "POST",
            "messages",
            params={"on_conflict": "provider,provider_message_id"},
            payload=data,
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return rows[0] if rows else None

    def update_conversation_from_inbound(self, company_id, conversation_id, data):
        rows = self.client.request(
            "PATCH",
            "conversations",
            params={
                "id": f"eq.{conversation_id}",
                "company_id": f"eq.{company_id}",
            },
            payload=data,
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def get_conversation(self, company_id, conversation_id):
        rows = self.client.request(
            "GET",
            "conversations",
            params={
                "select": "*",
                "id": f"eq.{conversation_id}",
                "company_id": f"eq.{company_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def list_messages(self, company_id, conversation_id, limit=200):
        return self.client.request(
            "GET",
            "messages",
            params={
                "select": "*",
                "company_id": f"eq.{company_id}",
                "conversation_id": f"eq.{conversation_id}",
                "order": "created_at.asc",
                "limit": str(limit),
            },
        )

    def get_message(self, company_id, conversation_id, message_id):
        rows = self.client.request(
            "GET",
            "messages",
            params={
                "select": "*",
                "id": f"eq.{message_id}",
                "company_id": f"eq.{company_id}",
                "conversation_id": f"eq.{conversation_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def get_conversation_by_id(self, conversation_id):
        rows = self.client.request(
            "GET",
            "conversations",
            params={
                "select": "*,lead:leads(id,full_name,phone,email,service_type,stage,description,address_line,city,state,postal_code,estimated_value)",
                "id": f"eq.{conversation_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def get_company_ai_context(self, company_id):
        companies = self.client.request(
            "GET",
            "companies",
            params={"select": "id,name", "id": f"eq.{company_id}", "limit": "1"},
        )
        settings = self.get_automation_settings(company_id)
        return {
            "company": companies[0] if companies else {"id": company_id, "name": ""},
            "settings": settings,
        }

    def create_automation_run(
        self, company_id, conversation_id, inbound_message_id, model
    ):
        rows = self.client.request(
            "POST",
            "automation_runs",
            params={"on_conflict": "inbound_message_id"},
            payload={
                "company_id": company_id,
                "conversation_id": conversation_id,
                "inbound_message_id": inbound_message_id,
                "provider": "openai",
                "model": model,
                "status": "processing",
            },
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return rows[0] if rows else None

    def get_automation_run(self, inbound_message_id):
        rows = self.client.request(
            "GET",
            "automation_runs",
            params={
                "select": "*",
                "inbound_message_id": f"eq.{inbound_message_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def retry_automation_run(self, run):
        if run.get("status") != "failed":
            return None
        rows = self.client.request(
            "PATCH",
            "automation_runs",
            params={"id": f"eq.{run['id']}", "status": "eq.failed"},
            payload={
                "status": "processing",
                "attempt_count": int(run.get("attempt_count") or 1) + 1,
                "last_error": None,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def complete_automation_run(
        self, run_id, decision, provider_response_id, completed_at
    ):
        rows = self.client.request(
            "PATCH",
            "automation_runs",
            params={"id": f"eq.{run_id}", "status": "eq.processing"},
            payload={
                "status": "completed",
                "decision": decision,
                "provider_response_id": provider_response_id,
                "completed_at": completed_at,
                "last_error": None,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def fail_automation_run(self, run_id, error):
        self.client.request(
            "PATCH",
            "automation_runs",
            params={"id": f"eq.{run_id}", "status": "eq.processing"},
            payload={"status": "failed", "last_error": str(error)[:500]},
        )

    def update_lead_from_automation(self, company_id, lead_id, data):
        rows = self.client.request(
            "PATCH",
            "leads",
            params={
                "id": f"eq.{lead_id}",
                "company_id": f"eq.{company_id}",
                "archived_at": "is.null",
            },
            payload={
                **data,
                "updated_by": None,
                "updated_via": "integration",
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def create_escalation_event(
        self, company_id, conversation_id, lead_id, reason
    ):
        rows = self.client.request(
            "POST",
            "escalation_events",
            payload={
                "company_id": company_id,
                "conversation_id": conversation_id,
                "lead_id": lead_id,
                "reason": reason,
                "trigger_command": "ai_qualification",
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def get_channel_by_id(self, company_id, channel_id):
        rows = self.client.request(
            "GET",
            "company_channels",
            params={
                "select": "*",
                "id": f"eq.{channel_id}",
                "company_id": f"eq.{company_id}",
                "active": "eq.true",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def get_completed_automation_run(
        self, company_id, conversation_id, inbound_message_id
    ):
        rows = self.client.request(
            "GET",
            "automation_runs",
            params={
                "select": "*",
                "company_id": f"eq.{company_id}",
                "conversation_id": f"eq.{conversation_id}",
                "inbound_message_id": f"eq.{inbound_message_id}",
                "status": "eq.completed",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def create_outbound_delivery(
        self, automation_run_id, company_id, conversation_id, channel_id
    ):
        rows = self.client.request(
            "POST",
            "outbound_deliveries",
            params={"on_conflict": "automation_run_id"},
            payload={
                "automation_run_id": automation_run_id,
                "company_id": company_id,
                "conversation_id": conversation_id,
                "channel_id": channel_id,
                "provider": "twilio",
                "status": "sending",
            },
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return rows[0] if rows else None

    def get_outbound_delivery(self, automation_run_id):
        rows = self.client.request(
            "GET",
            "outbound_deliveries",
            params={
                "select": "*",
                "automation_run_id": f"eq.{automation_run_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def retry_outbound_delivery(self, delivery):
        if delivery.get("status") != "failed":
            return None
        rows = self.client.request(
            "PATCH",
            "outbound_deliveries",
            params={"id": f"eq.{delivery['id']}", "status": "eq.failed"},
            payload={
                "status": "sending",
                "attempt_count": int(delivery.get("attempt_count") or 1) + 1,
                "last_error": None,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def accept_outbound_delivery(
        self, delivery_id, provider_message_id, provider_status
    ):
        rows = self.client.request(
            "PATCH",
            "outbound_deliveries",
            params={"id": f"eq.{delivery_id}", "status": "eq.sending"},
            payload={
                "status": "accepted",
                "provider_message_id": provider_message_id,
                "provider_status": provider_status,
                "last_error": None,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def complete_outbound_delivery(self, delivery_id, message_id, completed_at):
        rows = self.client.request(
            "PATCH",
            "outbound_deliveries",
            params={"id": f"eq.{delivery_id}", "status": "eq.accepted"},
            payload={
                "status": "completed",
                "message_id": message_id,
                "completed_at": completed_at,
                "last_error": None,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def mark_outbound_delivery(self, delivery_id, status, error):
        self.client.request(
            "PATCH",
            "outbound_deliveries",
            params={"id": f"eq.{delivery_id}", "status": "eq.sending"},
            payload={"status": status, "last_error": str(error)[:500]},
        )

    def create_outbound_message(self, data):
        rows = self.client.request(
            "POST",
            "messages",
            params={"on_conflict": "provider,provider_message_id"},
            payload=data,
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return rows[0] if rows else None

    def update_message_delivery_status(self, message_id, delivery_status, error_code):
        rows = self.client.request(
            "PATCH",
            "messages",
            params={"id": f"eq.{message_id}", "provider": "eq.twilio"},
            payload={
                "delivery_status": delivery_status,
                "error_code": error_code,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def update_conversation_automation(self, company_id, conversation_id, user_id, data):
        payload = {**data}
        rows = self.client.request(
            "PATCH",
            "conversations",
            params={
                "id": f"eq.{conversation_id}",
                "company_id": f"eq.{company_id}",
            },
            payload=payload,
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def create_invitation(self, company_id, user_id, email, role):
        payload = {
            "company_id": company_id,
            "email": email,
            "role": role,
            "created_by": user_id,
            "status": "pending",
        }
        rows = self.client.request(
            "POST",
            "invitations",
            payload=payload,
            prefer="return=representation",
        )
        if not rows:
            raise UpstreamError("O banco nao confirmou a criacao do convite.")
        return rows[0]

    def log_activity(self, company_id, user_id, action, details):
        payload = {
            "company_id": company_id,
            "user_id": user_id,
            "action": action,
            "details": details,
        }
        self.client.request("POST", "activity_logs", payload=payload)

    def get_dashboard_stats(self, company_id):
        leads = self.list_leads(company_id)
        conversations = self.list_conversations(company_id)
        
        new_leads = sum(1 for l in leads if l.get("stage") == "new")
        awaiting_reply = sum(1 for l in leads if l.get("stage") in ("contacted", "follow_up"))
        visits_scheduled = sum(1 for l in leads if l.get("stage") == "visit_scheduled")
        
        ai_active = sum(1 for c in conversations if c.get("automation_status") == "ai_active")
        human_requested = sum(1 for c in conversations if c.get("automation_status") == "human_requested")

        return {
            "new_leads": new_leads,
            "awaiting_reply": awaiting_reply,
            "visits_scheduled": visits_scheduled,
            "ai_active": ai_active,
            "human_requested": human_requested,
            "total_leads": len(leads),
        }

