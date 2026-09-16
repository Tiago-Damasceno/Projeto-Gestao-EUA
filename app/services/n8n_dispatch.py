import requests


def dispatch_integration_event(app, event):
    """Notify n8n after durable storage without exposing message content."""
    webhook_url = app.config.get("N8N_INBOUND_WEBHOOK_URL", "")
    if not webhook_url:
        return "disabled"

    shared_secret = app.config.get("N8N_SHARED_SECRET", "")
    if not shared_secret:
        app.logger.error("n8n webhook URL is configured without N8N_SHARED_SECRET")
        return "configuration_error"

    try:
        response = requests.post(
            webhook_url,
            json={
                "event_id": event["id"],
                "provider": event["provider"],
                "event_type": event["event_type"],
                "company_id": event["company_id"],
            },
            headers={
                "Authorization": f"Bearer {shared_secret}",
                "Content-Type": "application/json",
            },
            timeout=3,
        )
        response.raise_for_status()
    except requests.RequestException:
        app.logger.warning(
            "n8n event notification failed; scheduled recovery can retry event %s",
            event["id"],
        )
        return "failed"
    return "delivered"
