import pytest

from app.repositories import CRMRepository


LEAD_ID = "66666666-6666-4666-8666-666666666666"
COMPANY_ID = "11111111-1111-4111-8111-111111111111"


class CardContextClient:
    def request(self, method, resource, *, params=None, **kwargs):
        if resource == "leads":
            return [
                {
                    "id": LEAD_ID,
                    "stage": "contacted",
                    "created_at": "2026-09-01T00:00:00+00:00",
                    "estimated_value": "1250.00",
                }
            ]
        if resource == "lead_stage_events":
            return [
                {
                    "lead_id": LEAD_ID,
                    "to_stage": "contacted",
                    "created_at": "2026-09-10T00:00:00+00:00",
                }
            ]
        if resource == "conversations":
            return [
                {
                    "id": "88888888-8888-4888-8888-888888888888",
                    "lead_id": LEAD_ID,
                    "last_message_at": "2026-09-11T00:00:00+00:00",
                }
            ]
        raise AssertionError(resource)


def test_list_leads_adds_stage_time_and_conversation_link():
    rows = CRMRepository(CardContextClient()).list_leads(COMPANY_ID)
    assert rows[0]["stage_entered_at"] == "2026-09-10T00:00:00+00:00"
    assert rows[0]["conversation_id"] == "88888888-8888-4888-8888-888888888888"


class MissingOptionalContextClient(CardContextClient):
    def request(self, method, resource, *, params=None, **kwargs):
        if resource in {"lead_stage_events", "conversations"}:
            raise RuntimeError("optional table unavailable")
        row = super().request(method, resource, params=params, **kwargs)[0]
        row["stage"] = "new"
        return [row]


def test_lead_card_context_failure_is_not_hidden():
    with pytest.raises(RuntimeError, match="optional table unavailable"):
        CRMRepository(MissingOptionalContextClient()).list_leads(COMPANY_ID)
