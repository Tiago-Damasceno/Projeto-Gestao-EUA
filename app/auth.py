from functools import wraps

import requests
from flask import current_app, g, request

from .errors import ApiError, UpstreamError


class SupabaseAuthVerifier:
    """Valida a sessao no servidor do Supabase Auth.

    Este caminho funciona tanto com chaves de assinatura assimetricas quanto com
    projetos legados HS256 e respeita revogacao de sessao imediatamente.
    """

    def __init__(self, supabase_url, public_key, timeout_seconds=8):
        self.user_url = f"{supabase_url}/auth/v1/user"
        self.public_key = public_key
        self.timeout_seconds = timeout_seconds

    def verify(self, token):
        try:
            response = requests.get(
                self.user_url,
                headers={
                    "apikey": self.public_key,
                    "Authorization": f"Bearer {token}",
                },
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise UpstreamError("Nao foi possivel validar a sessao.") from exc

        if response.status_code in (401, 403):
            raise ApiError(401, "invalid_token", "Sessao invalida ou expirada.")
        if response.status_code != 200:
            raise UpstreamError("O servico de autenticacao nao respondeu corretamente.")

        user = response.json()
        if not user.get("id"):
            raise ApiError(401, "invalid_token", "Sessao invalida ou expirada.")
        return user


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise ApiError(
                401,
                "authentication_required",
                "Envie um access token em Authorization: Bearer <token>.",
            )
        if len(token) > 8192:
            raise ApiError(401, "invalid_token", "Token invalido.")

        verifier = current_app.extensions["auth_verifier"]
        g.current_user = verifier.verify(token.strip())
        return view(*args, **kwargs)

    return wrapped


def require_membership(organization_id, allowed_roles=None):
    repository = current_app.extensions["crm_repository"]
    user_id = str(g.current_user["id"])
    email = g.current_user.get("email")

    first_membership = repository.get_user_first_membership(user_id)
    if first_membership is None and not repository.is_email_authorized(email):
        raise ApiError(403, "access_not_granted", "Seu acesso ainda não foi liberado.")

    membership = repository.get_membership(str(organization_id), user_id)
    
    # Se o usuario tiver um papel global (platform_admin ou marketing_admin na empresa matriz)
    if first_membership and first_membership.get("role") == "platform_admin":
        membership = {"role": "platform_admin"}
    elif membership is None and first_membership and first_membership.get("role") == "marketing_admin":
        membership = {"role": first_membership["role"]}

    if membership is None:
        raise ApiError(404, "organization_not_found", "Empresa nao encontrada.")

    role = membership["role"]
    if role in ("owner", "admin"):
        role = "company_owner"
    elif role == "member":
        role = "operator"

    if allowed_roles:
        effective_allowed = set(allowed_roles)
        if "owner" in effective_allowed or "admin" in effective_allowed:
            effective_allowed.add("company_owner")
        if "company_owner" in effective_allowed:
            effective_allowed.update({"owner", "admin", "platform_admin"})
        if "member" in effective_allowed:
            effective_allowed.add("operator")
        if "operator" in effective_allowed:
            effective_allowed.add("member")
        if "platform_admin" in effective_allowed:
            effective_allowed.add("platform_admin")

        # Se a acao exigir permissao de escrita e o usuario for marketing_admin, negar com 403
        if role == "marketing_admin" and "marketing_admin" not in effective_allowed:
            raise ApiError(403, "forbidden", "A equipe de marketing possui acesso somente leitura.")

        if role not in effective_allowed and role != "platform_admin":
            raise ApiError(403, "forbidden", "Voce nao tem permissao para esta acao.")
    return membership



