from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Task:
    id: int
    title: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
