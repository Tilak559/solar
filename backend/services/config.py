import pydantic_settings
from typing import List

class config(pydantic_settings.BaseSettings):

    google_api_key: str
    google_credentials_path: str
    google_scopes: str = "https://www.googleapis.com/auth/solar"
    project_id: str

    @property
    def google_scopes_list(self) -> List[str]:
        return [scope.strip() for scope in self.google_scopes.split(",")]

    class Config:
        env_file = ".env"

config = config()