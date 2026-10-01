from errors.base_error import QIException


class InvalidCredentials(QIException):
    code = "KOD002001"

    def __init__(self):
        super().__init__(
            "Invalid credentials",
            self.code,
            401,
            "Invalid email or password.",
            "E-mail ou senha inválidos.",
        )


class InvalidAccessToken(QIException):
    code = "KOD002002"

    def __init__(self):
        super().__init__(
            "Invalid access token",
            self.code,
            401,
            "A valid access token is required.",
            "É necessário um token de acesso válido.",
        )