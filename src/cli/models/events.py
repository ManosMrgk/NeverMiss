from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pydantic import AnyUrl, BaseModel, Field

@dataclass
class Event:
    title: str
    url: str
    start_date: Optional[str]
    venue: Optional[str]
    city: Optional[str]
    region: Optional[str]
    image: Optional[str]
    def to_row(self):
        return (self.start_date or "", self.venue or "", self.title, self.url)
    
# ========== Pydantic validator mirroring Event ==========
class EventModel(BaseModel):
    title: str
    url: AnyUrl
    start_date: Optional[str] = Field(default=None)  # Expect ISO 8601 date or datetime string
    venue: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    image: Optional[AnyUrl] = None

    # Optional: light format check for start_date (ISO-like)
    @classmethod
    def _is_iso_like(cls, s: str) -> bool:
        try:
            # Accept both date-only and datetime
            if "T" in s:
                datetime.fromisoformat(s.replace("Z", "+00:00"))
            else:
                datetime.fromisoformat(s)
            return True
        except Exception:
            return False

    @classmethod
    def validate_start_date(cls, v):
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("start_date must be a string (ISO 8601).")
        if not cls._is_iso_like(v):
            raise ValueError("start_date should be ISO 8601 (e.g., 2025-10-25 or 2025-10-25T20:00:00Z).")
        return v

    def model_post_init(self, __context) -> None:
        # Run the custom validation for start_date
        if "start_date" in self.model_fields_set:
            object.__setattr__(self, "start_date", self.validate_start_date(self.start_date))

