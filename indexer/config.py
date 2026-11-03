"""Settings come from environment variables (D13)."""
import os
from dataclasses import dataclass

SCHEMA = "indexer"


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    name: str
    user: str
    password: str

    @classmethod
    def from_env(cls, prefix: str = "INDEXER_DB_") -> "DbSettings":
        env = os.environ
        return cls(
            host=env.get(prefix + "HOST", "127.0.0.1"),
            port=int(env.get(prefix + "PORT", "5432")),
            name=env.get(prefix + "NAME", "indexer"),
            user=env.get(prefix + "USER", "indexer"),
            password=env.get(prefix + "PASSWORD", "indexer"),
        )

    def as_env(self, prefix: str = "INDEXER_DB_") -> dict:
        return {
            prefix + "HOST": self.host,
            prefix + "PORT": str(self.port),
            prefix + "NAME": self.name,
            prefix + "USER": self.user,
            prefix + "PASSWORD": self.password,
        }
