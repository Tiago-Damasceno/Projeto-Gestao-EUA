"""Configure the imported 23e workflow in a local n8n Community instance."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
N8N_API_BASE = "http://127.0.0.1:5678/api/v1"
WORKFLOW_ID = "E2x7G9mK4pQ8rT6v"
WORKFLOW_NAME = "23e - Inbound SMS Intake"
CREDENTIAL_NAME = "23e Backend Authorization"
LOCAL_BACKEND_URL = "http://host.docker.internal:5000"
LOCAL_N8N_WEBHOOK_URL = (
    "http://127.0.0.1:5678/webhook/23e-inbound-event"
)
HTTP_NODE_NAMES = {
    "Process Immediate Event",
    "Get Pending Events",
    "Process Recovered Event",
    "Qualify and Draft Reply",
    "Send AI Reply",
}
ALLOWED_WORKFLOW_SETTINGS = {
    "saveExecutionProgress",
    "saveManualExecutions",
    "saveDataErrorExecution",
    "saveDataSuccessExecution",
    "executionTimeout",
    "errorWorkflow",
    "timezone",
    "executionOrder",
    "callerPolicy",
    "callerIds",
    "timeSavedPerExecution",
    "availableInMCP",
}


def read_env() -> tuple[list[str], dict[str, str]]:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
    for line in lines:
        match = pattern.match(line)
        if match:
            values[match.group(1)] = match.group(2)
    return lines, values


def write_env_value(lines: list[str], name: str, value: str) -> list[str]:
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=")
    replacement = f"{name}={value}"
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = replacement
            return lines
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(replacement)
    return lines


def checked(response: requests.Response) -> requests.Response:
    if response.ok:
        return response
    detail = response.text[:500].replace("\n", " ")
    raise RuntimeError(
        f"n8n API request failed: {response.request.method} "
        f"{response.request.url} returned HTTP {response.status_code}: {detail}"
    )


def main() -> None:
    lines, values = read_env()
    api_key = values.get("N8N_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("N8N_API_KEY is missing from .env")

    shared_secret = values.get("N8N_SHARED_SECRET", "").strip()
    secret_created = not shared_secret
    if secret_created:
        shared_secret = secrets.token_urlsafe(48)
        lines = write_env_value(lines, "N8N_SHARED_SECRET", shared_secret)

    lines = write_env_value(
        lines,
        "N8N_INBOUND_WEBHOOK_URL",
        LOCAL_N8N_WEBHOOK_URL,
    )
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    session = requests.Session()
    session.headers.update(
        {
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json",
        }
    )

    credential_rows = checked(
        session.get(f"{N8N_API_BASE}/credentials", params={"limit": 100}, timeout=10)
    ).json().get("data", [])
    matches = [
        row
        for row in credential_rows
        if row.get("name") == CREDENTIAL_NAME
        and row.get("type") == "httpHeaderAuth"
    ]
    if len(matches) > 1:
        raise RuntimeError("More than one 23e Header Auth credential exists.")

    if matches:
        credential = matches[0]
        checked(
            session.patch(
                f"{N8N_API_BASE}/credentials/{credential['id']}",
                json={
                    "name": CREDENTIAL_NAME,
                    "data": {
                        "name": "Authorization",
                        "value": f"Bearer {shared_secret}",
                    },
                },
                timeout=10,
            )
        )
        credential_created = False
    else:
        credential = checked(
            session.post(
                f"{N8N_API_BASE}/credentials",
                json={
                    "name": CREDENTIAL_NAME,
                    "type": "httpHeaderAuth",
                    "data": {
                        "name": "Authorization",
                        "value": f"Bearer {shared_secret}",
                    },
                },
                timeout=10,
            )
        ).json()
        credential_created = True

    workflow = checked(
        session.get(f"{N8N_API_BASE}/workflows/{WORKFLOW_ID}", timeout=10)
    ).json()
    if workflow.get("name") != WORKFLOW_NAME:
        raise RuntimeError("The expected 23e workflow was not found.")

    assigned_nodes = []
    replaced_urls = 0
    credential_ref = {
        "httpHeaderAuth": {
            "id": credential["id"],
            "name": CREDENTIAL_NAME,
        }
    }
    for node in workflow["nodes"]:
        if node.get("name") == "Immediate Event" or node.get("name") in HTTP_NODE_NAMES:
            node["credentials"] = credential_ref
            assigned_nodes.append(node["name"])
        if node.get("name") in HTTP_NODE_NAMES:
            url = node.get("parameters", {}).get("url")
            if isinstance(url, str) and "$vars.BACKEND_BASE_URL" in url:
                node["parameters"]["url"] = url.replace(
                    "$vars.BACKEND_BASE_URL",
                    f"'{LOCAL_BACKEND_URL}'",
                )
                replaced_urls += 1

    if set(assigned_nodes) != {"Immediate Event", *HTTP_NODE_NAMES}:
        raise RuntimeError("The credential was not assigned to every required node.")
    if replaced_urls not in (0, len(HTTP_NODE_NAMES)):
        raise RuntimeError("Only some backend URLs were converted for local Docker.")

    update_body = {
        "name": workflow["name"],
        "nodes": workflow["nodes"],
        "connections": workflow["connections"],
        "settings": {
            key: value
            for key, value in workflow.get("settings", {}).items()
            if key in ALLOWED_WORKFLOW_SETTINGS
        },
    }
    checked(
        session.put(
            f"{N8N_API_BASE}/workflows/{WORKFLOW_ID}",
            json=update_body,
            timeout=15,
        )
    )
    activation = checked(
        session.post(
            f"{N8N_API_BASE}/workflows/{WORKFLOW_ID}/activate",
            json={},
            timeout=15,
        )
    ).json()

    print(f"shared_secret={'created' if secret_created else 'preserved'}")
    print(
        f"header_auth_credential="
        f"{'created' if credential_created else 'updated'}"
    )
    print(f"credential_nodes={len(assigned_nodes)}")
    print(f"local_backend_urls={len(HTTP_NODE_NAMES)}")
    print(f"workflow_active={str(bool(activation.get('active'))).lower()}")


if __name__ == "__main__":
    main()
