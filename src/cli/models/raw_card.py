from dataclasses import dataclass
from typing import Optional

@dataclass
class RawCard:
    hidden: bool
    url: Optional[str]
    image: Optional[str]
    start_iso: Optional[str]
    title: str
    venue: Optional[str]
    city: Optional[str]
    region: Optional[str]
    pill: Optional[str]