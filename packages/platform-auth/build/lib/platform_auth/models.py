from dataclasses import dataclass


@dataclass
class AuthenticatedUser:
    id: str
    role: str
    scopes: list[str]

    def has_scope(self, scope: str) -> bool:
        return self.role == "admin" or scope in self.scopes
