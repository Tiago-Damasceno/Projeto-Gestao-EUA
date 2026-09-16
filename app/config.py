import os
import base64
import json

from dotenv import load_dotenv


def public_auth_settings(settings):
    """Publish only a publishable key or legacy anon JWT; fail closed."""
    key = settings["SUPABASE_PUBLIC_KEY"]
    safe = key.startswith("sb_publishable_")
    if not safe:
        try:
            payload = key.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            safe = isinstance(claims, dict) and claims.get("role") == "anon"
        except (ValueError, IndexError, TypeError):
            safe = False
    if not safe or key == settings["SUPABASE_SERVICE_ROLE_KEY"]:
        from .errors import ApiError
        raise ApiError(503, "auth_configuration_error", "Configure uma chave pública Supabase válida no servidor.")
    return {"url": settings["SUPABASE_URL"], "publicKey": key}


def load_settings():
    load_dotenv()

    settings = {
        "TESTING": os.getenv("TESTING", "false").lower() == "true",
        "SUPABASE_URL": os.getenv("SUPABASE_URL", "").rstrip("/"),
        "SUPABASE_PUBLIC_KEY": os.getenv("SUPABASE_PUBLIC_KEY", ""),
        "SUPABASE_SERVICE_ROLE_KEY": os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        "ALLOWED_ORIGINS": [
            origin.strip()
            for origin in os.getenv(
                "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(",")
            if origin.strip()
        ],
        "MAX_CONTENT_LENGTH": int(os.getenv("MAX_CONTENT_LENGTH", "1048576")),
        "SUPABASE_TIMEOUT_SECONDS": float(
            os.getenv("SUPABASE_TIMEOUT_SECONDS", "8")
        ),
        "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "PUBLIC_BASE_URL": os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
        "N8N_SHARED_SECRET": os.getenv("N8N_SHARED_SECRET", ""),
        "N8N_INBOUND_WEBHOOK_URL": os.getenv("N8N_INBOUND_WEBHOOK_URL", ""),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
    }

    return settings
