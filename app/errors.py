class ApiError(Exception):
    def __init__(self, status_code, code, message, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class UpstreamError(ApiError):
    def __init__(self, message="Falha temporaria ao acessar os dados."):
        super().__init__(502, "upstream_error", message)

