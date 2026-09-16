from conftest import COMPANY_A_ID, CONV_A_ID, MESSAGE_A_ID


def test_member_can_read_messages_from_own_company_conversation(
    client, repository, auth_headers_user_a
):
    repository.messages.append(
        {
            "id": MESSAGE_A_ID,
            "company_id": COMPANY_A_ID,
            "conversation_id": CONV_A_ID,
            "direction": "inbound",
            "sender_type": "lead",
            "content": "Hello",
        }
    )

    response = client.get(
        f"/api/v1/conversations/{CONV_A_ID}/messages",
        headers=auth_headers_user_a,
    )

    assert response.status_code == 200
    assert response.json["data"][0]["content"] == "Hello"


def test_conversation_messages_are_isolated_by_company(
    client, auth_headers_user_b
):
    response = client.get(
        f"/api/v1/conversations/{CONV_A_ID}/messages",
        headers=auth_headers_user_b,
    )

    assert response.status_code == 404
    assert response.json["error"]["code"] == "conversation_not_found"


def test_conversation_messages_require_user_authentication(client):
    response = client.get(f"/api/v1/conversations/{CONV_A_ID}/messages")

    assert response.status_code == 401
