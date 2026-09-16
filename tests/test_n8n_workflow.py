import json
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / "n8n"
    / "workflows"
    / "23e-inbound-sms-intake.json"
)


def load_workflow():
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def destinations(workflow, node_name, output=0):
    return [
        item["node"]
        for item in workflow["connections"][node_name]["main"][output]
    ]


def test_workflow_is_importable_inactive_and_contains_no_credentials():
    workflow = load_workflow()
    serialized = json.dumps(workflow)

    assert workflow["active"] is False
    assert workflow["id"] == "E2x7G9mK4pQ8rT6v"
    assert workflow["pinData"] == {}
    assert '"credentials"' not in serialized
    assert "test-n8n-shared-secret" not in serialized
    assert "sk-" not in serialized
    assert "AC00000000000000000000000000000000" not in serialized


def test_both_event_paths_use_the_same_type_gate():
    workflow = load_workflow()

    assert destinations(workflow, "Process Immediate Event") == ["Inbound Message?"]
    assert destinations(workflow, "Process Recovered Event") == ["Inbound Message?"]
    assert destinations(workflow, "Inbound Message?", 0) == [
        "Qualify and Draft Reply"
    ]
    assert destinations(workflow, "Inbound Message?", 1) == [
        "Delivery Status Stored"
    ]


def test_only_completed_qualification_reaches_outbound_send():
    workflow = load_workflow()

    assert destinations(workflow, "Qualify and Draft Reply") == ["Reply Ready?"]
    assert destinations(workflow, "Reply Ready?", 0) == ["Send AI Reply"]
    assert destinations(workflow, "Reply Ready?", 1) == ["No Automated Reply"]

    nodes = {node["name"]: node for node in workflow["nodes"]}
    qualify = nodes["Qualify and Draft Reply"]["parameters"]
    send = nodes["Send AI Reply"]["parameters"]

    assert "$vars.BACKEND_BASE_URL" in qualify["url"]
    assert "/qualify" in qualify["url"]
    assert "message_id" in qualify["body"]
    assert "$vars.BACKEND_BASE_URL" in send["url"]
    assert "/send-ai-reply" in send["url"]
    assert "inbound_message_id" in send["body"]
