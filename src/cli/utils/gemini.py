import re
from typing import List
import google.generativeai as genai
from pydantic import TypeAdapter, ValidationError

from models.events import EventModel, Event

EventListAdapter = TypeAdapter(List[EventModel])

def strip_code_fences(s: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip(), flags=re.IGNORECASE)

def call_gemini(api_key: str, system_prompt: str, user_prompt: str, model_name: str = "gemini-1.5-pro") -> List[Event]:
    if not api_key:
        raise RuntimeError("Missing GOOGLE_API_KEY in environment (.env).")

    genai.configure(api_key=api_key, transport="rest")

    model = genai.GenerativeModel(
        model_name,
        system_instruction=system_prompt,
        generation_config={
            "response_mime_type": "application/json",  # force raw JSON
        },
    )

    resp = model.generate_content(user_prompt)
    raw = getattr(resp, "text", None) or str(resp)
    raw = strip_code_fences(raw)

    # Validate -> EventModel[] -> Event[]
    try:
        validated: List[EventModel] = EventListAdapter.validate_json(raw)
    except ValidationError as ve:
        raise ValueError(
            "Gemini returned invalid JSON for Event[].\n"
            f"Pydantic error:\n{ve}\n\nRaw output:\n{raw}"
        ) from ve

    # Convert to your dataclass
    events: List[Event] = [
        Event(
            title=e.title,
            url=str(e.url),
            start_date=e.start_date,
            venue=e.venue,
            city=e.city,
            region=e.region,
            image=(str(e.image) if e.image is not None else None),
        )
        for e in validated
    ]
    return events