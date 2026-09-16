import logging
import uuid

from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .auth import SupabaseAuthVerifier
from .config import load_settings
from .errors import ApiError
from .repositories import CRMRepository, SupabaseRestClient
from .routes import api_bp, health_bp, integration_bp, webhook_bp


def create_app(
    test_config=None,
    *,
    auth_verifier=None,
    repository=None,
    openai_client=None,
    twilio_client=None,
):
    """Application factory: cria instancias independentes e testaveis do Flask."""
    import os
    public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
    app = Flask(__name__, static_folder=public_dir, static_url_path="")
    app.config.from_mapping(load_settings())
    if test_config:
        app.config.update(test_config)

    if not app.config["TESTING"]:
        missing = [
            name
            for name in (
                "SUPABASE_URL",
                "SUPABASE_PUBLIC_KEY",
                "SUPABASE_SERVICE_ROLE_KEY",
            )
            if not app.config.get(name)
        ]
        if missing:
            raise RuntimeError(
                "Variaveis obrigatorias ausentes: " + ", ".join(missing)
            )

    app.config["MAX_CONTENT_LENGTH"] = int(app.config["MAX_CONTENT_LENGTH"])
    origins = app.config["ALLOWED_ORIGINS"]
    CORS(
        app,
        resources={r"/api/*": {"origins": origins}},
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        expose_headers=["X-Request-ID"],
        supports_credentials=False,
        max_age=600,
    )

    if auth_verifier is None:
        auth_verifier = SupabaseAuthVerifier(
            app.config["SUPABASE_URL"],
            app.config["SUPABASE_PUBLIC_KEY"],
            app.config["SUPABASE_TIMEOUT_SECONDS"],
        )
    if repository is None:
        rest_client = SupabaseRestClient(
            app.config["SUPABASE_URL"],
            app.config["SUPABASE_SERVICE_ROLE_KEY"],
            app.config["SUPABASE_TIMEOUT_SECONDS"],
        )
        repository = CRMRepository(rest_client)

    app.extensions["auth_verifier"] = auth_verifier
    app.extensions["crm_repository"] = repository
    if openai_client is None and app.config.get("OPENAI_API_KEY"):
        from openai import OpenAI

        openai_client = OpenAI(api_key=app.config["OPENAI_API_KEY"])
    app.extensions["openai_client"] = openai_client
    if (
        twilio_client is None
        and app.config.get("TWILIO_ACCOUNT_SID")
        and app.config.get("TWILIO_AUTH_TOKEN")
    ):
        from twilio.rest import Client

        twilio_client = Client(
            app.config["TWILIO_ACCOUNT_SID"],
            app.config["TWILIO_AUTH_TOKEN"],
        )
    app.extensions["twilio_client"] = twilio_client

    app.register_blueprint(health_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(integration_bp)
    app.register_blueprint(webhook_bp)

    @app.get("/auth/config")
    def auth_config():
        # Explicit allowlist: service credentials must never reach the browser.
        from .config import public_auth_settings
        return jsonify(public_auth_settings(app.config))

    @app.route("/")
    def serve_index():
        if os.path.exists(os.path.join(public_dir, "index.html")):
            return app.send_static_file("index.html")
        return jsonify({"message": "23e Gestão API Operational"})


    @app.before_request
    def assign_request_id():
        supplied = str(request.headers.get("X-Request-ID", ""))
        g.request_id = supplied[:80] if supplied else str(uuid.uuid4())

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        payload = {
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": getattr(g, "request_id", None),
            }
        }
        if error.details is not None:
            payload["error"]["details"] = error.details
        return jsonify(payload), error.status_code

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return (
            jsonify(
                {
                    "error": {
                        "code": error.name.lower().replace(" ", "_"),
                        "message": error.description,
                        "request_id": getattr(g, "request_id", None),
                    }
                }
            ),
            error.code,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception(
            "Unhandled API error",
            extra={"request_id": getattr(g, "request_id", None)},
        )
        return (
            jsonify(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Erro interno. Tente novamente.",
                        "request_id": getattr(g, "request_id", None),
                    }
                }
            ),
            500,
        )

    logging.basicConfig(level=logging.INFO)
    return app
