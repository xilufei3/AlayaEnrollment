from pydantic import BaseModel


class Config(BaseModel):
    alaya_api_base: str = "http://localhost:8008"
    alaya_api_key: str = ""
    alaya_trigger_prefix: str = ""
    alaya_allowed_groups: list[str] = []
