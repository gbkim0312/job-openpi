from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import select

from .persistence import SearchProfileRow


class SearchProfile(BaseModel):
    id: str
    display_name: str
    queries: list[str] = Field(min_length=1)
    include_keywords: list[str] = []
    exclude_keywords: list[str] = []
    source_queries: dict[str, list[str]] = {}
    company_queries: dict[str, list[str]] = {}


class ProfileStore:
    def __init__(self, directory: Path):
        self.directory, self.items = directory, {}

    def reload(self) -> None:
        self.items = {
            p.id: p
            for path in self.directory.glob("*.yml")
            if (p := SearchProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))))
        }

    def get(self, profile_id: str) -> SearchProfile:
        return self.items[profile_id]

    async def seed_and_load(self, session) -> None:
        """Seed YAML defaults once; database becomes the editable source of truth."""
        self.reload()
        for profile in self.items.values():
            if await session.get(SearchProfileRow, profile.id) is None:
                session.add(
                    SearchProfileRow(
                        id=profile.id,
                        display_name=profile.display_name,
                        config=profile.model_dump(),
                    )
                )
        await session.commit()
        rows = (
            await session.execute(
                select(SearchProfileRow).where(SearchProfileRow.enabled.is_(True))
            )
        ).scalars()
        self.items = {row.id: SearchProfile.model_validate(row.config) for row in rows}

    def set(self, profile: SearchProfile) -> None:
        self.items[profile.id] = profile

    def remove(self, profile_id: str) -> None:
        self.items.pop(profile_id, None)
