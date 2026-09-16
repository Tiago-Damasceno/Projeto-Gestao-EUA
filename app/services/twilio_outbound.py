from datetime import datetime, timezone

from twilio.base.exceptions import TwilioRestException

from ..errors import ApiError


class TwilioOutboundService:
    """Send one stored AI decision once and persist the provider result."""

    def __init__(self, repository, client, public_base_url):
        self.repository = repository
        self.client = client
        self.public_base_url = public_base_url

    def send(self, conversation, automation_run):
        decision = automation_run.get("decision") or {}
        body = str(decision.get("reply_text", "")).strip()
        if not body or len(body) > 480:
            raise ApiError(
                422,
                "invalid_automation_decision",
                "The stored AI reply is missing or invalid.",
            )

        channel = self.repository.get_channel_by_id(
            conversation["company_id"], conversation.get("channel_id")
        )
        if channel is None:
            raise ApiError(
                409,
                "company_channel_unavailable",
                "No active Twilio channel is available for this conversation.",
            )

        delivery = self.repository.create_outbound_delivery(
            automation_run["id"],
            conversation["company_id"],
            conversation["id"],
            channel["id"],
        )
        if delivery is None:
            delivery = self.repository.get_outbound_delivery(automation_run["id"])
            if delivery and delivery.get("status") == "completed":
                return self._result(delivery), True
            if delivery and delivery.get("status") == "accepted":
                return self._finalize(
                    delivery, conversation, body, delivery["provider_status"]
                ), True
            if delivery and delivery.get("status") == "failed":
                delivery = self.repository.retry_outbound_delivery(delivery)
            else:
                delivery = None
            if delivery is None:
                raise ApiError(
                    409,
                    "outbound_delivery_busy",
                    "This reply is already being delivered or needs reconciliation.",
                )

        send_args = {
            "body": body,
            "to": conversation["contact_address"],
        }
        if channel.get("messaging_service_sid"):
            send_args["messaging_service_sid"] = channel["messaging_service_sid"]
        else:
            send_args["from_"] = channel["address"]
        if self.public_base_url:
            send_args["status_callback"] = (
                f"{self.public_base_url}/webhooks/twilio/status"
            )

        try:
            provider_message = self.client.messages.create(**send_args)
        except TwilioRestException as exc:
            self.repository.mark_outbound_delivery(
                delivery["id"], "failed", f"twilio_rejected:{exc.status}"
            )
            raise ApiError(
                502,
                "twilio_message_rejected",
                "Twilio rejected the outbound message.",
            ) from exc
        except Exception as exc:
            self.repository.mark_outbound_delivery(
                delivery["id"], "unknown", "twilio_result_unknown"
            )
            raise ApiError(
                502,
                "twilio_delivery_unknown",
                "The Twilio delivery result is unknown and requires reconciliation.",
            ) from exc

        provider_status = str(getattr(provider_message, "status", "accepted"))
        accepted = self.repository.accept_outbound_delivery(
            delivery["id"], provider_message.sid, provider_status
        )
        if accepted is None:
            raise ApiError(
                502,
                "delivery_persistence_error",
                "The accepted Twilio message could not be recorded.",
            )
        return self._finalize(accepted, conversation, body, provider_status), False

    def _finalize(self, delivery, conversation, body, provider_status):
        sent_at = datetime.now(timezone.utc).isoformat()
        message = self.repository.get_message_by_provider_id(
            "twilio", delivery["provider_message_id"]
        )
        if message is None:
            message = self.repository.create_outbound_message(
                {
                    "company_id": conversation["company_id"],
                    "conversation_id": conversation["id"],
                    "sender_type": "ai",
                    "direction": "outbound",
                    "content": body,
                    "raw_payload": {
                        "automation_run_id": delivery["automation_run_id"]
                    },
                    "provider": "twilio",
                    "provider_message_id": delivery["provider_message_id"],
                    "delivery_status": provider_status,
                    "media_count": 0,
                    "sent_at": sent_at,
                }
            )
        if message is None:
            message = self.repository.get_message_by_provider_id(
                "twilio", delivery["provider_message_id"]
            )
        if message is None:
            raise ApiError(
                502,
                "message_persistence_error",
                "The outbound message could not be stored.",
            )

        completed = self.repository.complete_outbound_delivery(
            delivery["id"], message["id"], sent_at
        )
        if completed is None:
            current = self.repository.get_outbound_delivery(
                delivery["automation_run_id"]
            )
            if not current or current.get("status") != "completed":
                raise ApiError(
                    502,
                    "delivery_persistence_error",
                    "The outbound delivery could not be completed.",
                )
            completed = current
        self.repository.update_conversation_from_inbound(
            conversation["company_id"],
            conversation["id"],
            {"last_message_at": sent_at},
        )
        return self._result(completed)

    @staticmethod
    def _result(delivery):
        return {
            "delivery_id": delivery["id"],
            "message_id": delivery.get("message_id"),
            "provider_message_id": delivery.get("provider_message_id"),
            "provider_status": delivery.get("provider_status"),
            "status": delivery["status"],
        }
