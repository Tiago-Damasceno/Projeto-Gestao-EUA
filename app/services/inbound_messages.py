from datetime import datetime, timezone

from ..errors import ApiError


class InboundMessageProcessor:
    """Turn one durable provider event into CRM records exactly once."""

    def __init__(self, repository):
        self.repository = repository

    def process(self, event_id):
        event = self.repository.get_integration_event(event_id)
        if event is None:
            raise ApiError(404, "integration_event_not_found", "Integration event not found.")
        if event.get("status") == "completed":
            return event.get("processed_result") or {}, True
        if event.get("status") == "ignored":
            raise ApiError(409, "integration_event_ignored", "This event was not routed.")

        claimed = self.repository.claim_integration_event(event)
        if claimed is None:
            current = self.repository.get_integration_event(event_id)
            if current and current.get("status") == "completed":
                return current.get("processed_result") or {}, True
            raise ApiError(
                409,
                "integration_event_busy",
                "This event is already being processed.",
            )

        try:
            result = self._process_claimed(claimed)
            completed_at = datetime.now(timezone.utc).isoformat()
            completed = self.repository.complete_integration_event(
                event_id, result, completed_at
            )
            if completed is None:
                raise ApiError(
                    409,
                    "integration_event_state_error",
                    "The processed event could not be completed.",
                )
            return result, False
        except Exception as exc:
            try:
                self.repository.fail_integration_event(
                    event_id, f"processing_failed:{type(exc).__name__}"
                )
            except Exception:
                pass
            raise

    def _process_claimed(self, event):
        if event.get("provider") != "twilio":
            raise ApiError(
                422,
                "unsupported_integration_event",
                "This integration event type is not supported.",
            )
        if event.get("event_type") == "message_status":
            return self._process_message_status(event)
        if event.get("event_type") != "inbound_message":
            raise ApiError(
                422,
                "unsupported_integration_event",
                "This integration event type is not supported.",
            )

        company_id = event.get("company_id")
        channel_id = event.get("channel_id")
        payload = event.get("payload") or {}
        contact_address = payload.get("From")
        provider_message_id = payload.get("MessageSid")
        if not company_id or not channel_id or not contact_address or not provider_message_id:
            raise ApiError(
                422,
                "invalid_integration_event",
                "The integration event is missing routing data.",
            )

        existing_message = self.repository.get_message_by_provider_id(
            "twilio", provider_message_id
        )
        if existing_message:
            conversation = self.repository.get_conversation(
                company_id, existing_message["conversation_id"]
            )
            if conversation:
                return self._result(
                    event, conversation, existing_message, payload, reused=True
                )

        conversation = self.repository.get_open_conversation(
            company_id, channel_id, contact_address
        )
        opt_out_type = str(payload.get("OptOutType", "")).upper()
        contacted_at = datetime.now(timezone.utc).isoformat()

        if conversation is None:
            lead = self.repository.get_active_lead_by_phone(
                company_id, contact_address
            )
            if lead is None:
                lead = self.repository.create_integration_lead(
                    company_id,
                    {
                        "full_name": contact_address,
                        "phone": contact_address,
                        "source": "twilio_sms",
                        "stage": "new",
                        "last_contact_at": contacted_at,
                    },
                )
            conversation = self.repository.create_conversation(
                company_id,
                lead["id"],
                channel_id,
                contact_address,
                "opted_out" if opt_out_type == "STOP" else "ai_active",
            )

        message = self.repository.create_inbound_message(
            {
                "company_id": company_id,
                "conversation_id": conversation["id"],
                "sender_type": "lead",
                "direction": "inbound",
                "content": str(payload.get("Body", "")),
                "raw_payload": payload,
                "provider": "twilio",
                "provider_message_id": provider_message_id,
                "delivery_status": "received",
                "media_count": int(payload.get("NumMedia", 0)),
                "received_at": contacted_at,
            }
        )
        if message is None:
            message = self.repository.get_message_by_provider_id(
                "twilio", provider_message_id
            )
        if message is None:
            raise ApiError(
                502,
                "message_persistence_error",
                "The inbound message could not be stored.",
            )

        conversation_update = {"last_message_at": contacted_at}
        if opt_out_type == "STOP":
            conversation_update.update(
                {"automation_status": "opted_out", "opted_out_at": contacted_at}
            )
        elif opt_out_type == "START":
            conversation_update.update(
                {"automation_status": "ai_active", "opted_out_at": None}
            )
        updated_conversation = self.repository.update_conversation_from_inbound(
            company_id, conversation["id"], conversation_update
        )
        if updated_conversation:
            conversation = updated_conversation
        self.repository.touch_integration_lead(
            company_id, conversation["lead_id"], contacted_at
        )

        return self._result(event, conversation, message, payload, reused=False)

    def _process_message_status(self, event):
        payload = event.get("payload") or {}
        provider_message_id = payload.get("MessageSid")
        delivery_status = payload.get("MessageStatus")
        if not provider_message_id or not delivery_status:
            raise ApiError(
                422,
                "invalid_integration_event",
                "The status event is missing message data.",
            )
        message = self.repository.get_message_by_provider_id(
            "twilio", provider_message_id
        )
        if message is None:
            raise ApiError(
                404,
                "provider_message_not_found",
                "The provider message has not been stored yet.",
            )
        updated = self.repository.update_message_delivery_status(
            message["id"],
            delivery_status,
            payload.get("ErrorCode"),
        )
        if updated is None:
            raise ApiError(
                404,
                "provider_message_not_found",
                "The provider message has not been stored yet.",
            )
        return {
            "event_id": event["id"],
            "event_type": "message_status",
            "company_id": updated["company_id"],
            "conversation_id": updated["conversation_id"],
            "message_id": updated["id"],
            "provider_message_id": provider_message_id,
            "delivery_status": delivery_status,
            "error_code": payload.get("ErrorCode"),
        }

    @staticmethod
    def _result(event, conversation, message, payload, reused):
        return {
            "event_id": event["id"],
            "event_type": "inbound_message",
            "company_id": event["company_id"],
            "lead_id": conversation["lead_id"],
            "conversation_id": conversation["id"],
            "message_id": message["id"],
            "automation_status": conversation.get("automation_status", "ai_active"),
            "contact_address": payload["From"],
            "inbound_body": str(payload.get("Body", "")),
            "media_count": int(payload.get("NumMedia", 0)),
            "record_reused": reused,
        }
