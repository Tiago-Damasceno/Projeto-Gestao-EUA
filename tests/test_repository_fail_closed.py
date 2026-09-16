import pytest

from app.errors import UpstreamError
from app.repositories import CRMRepository


COMPANY_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "33333333-3333-4333-8333-333333333333"
CONVERSATION_ID = "88888888-8888-4888-8888-888888888888"


class FailingClient:
    def request(self, *args, **kwargs):
        raise UpstreamError("database unavailable")


@pytest.mark.parametrize(
    "operation",
    [
        lambda repo: repo.get_membership(COMPANY_ID, USER_ID),
        lambda repo: repo.get_profile(USER_ID),
        lambda repo: repo.get_onboarding_progress(COMPANY_ID),
        lambda repo: repo.get_automation_settings(COMPANY_ID),
        lambda repo: repo.list_conversations(COMPANY_ID),
        lambda repo: repo.update_conversation_automation(
            COMPANY_ID, CONVERSATION_ID, USER_ID, {"automation_status": "paused"}
        ),
        lambda repo: repo.create_invitation(
            COMPANY_ID, USER_ID, "operator@example.com", "operator"
        ),
        lambda repo: repo.log_activity(COMPANY_ID, USER_ID, "test", {}),
    ],
)
def test_required_repository_operations_propagate_database_failures(operation):
    with pytest.raises(UpstreamError, match="database unavailable"):
        operation(CRMRepository(FailingClient()))
