from __future__ import annotations

from pydantic import BaseModel, Field


class GridMeta(BaseModel):
    total: int
    page: int
    page_size: int
    sort: str
    order: str
    pages: int


class GridResponse[T](BaseModel):
    items: list[T]
    meta: GridMeta


class GridQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    sort: str = "updated_at"
    order: str = "desc"
    q: str | None = Field(default=None, max_length=120)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def descending(self) -> bool:
        return self.order.lower() != "asc"
