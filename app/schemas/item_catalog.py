from typing import Optional

from pydantic import BaseModel, ConfigDict


class ItemCatalogCreateRequest(BaseModel):
    item_category: str
    item_name: str
    default_price: Optional[float] = None


class ItemCatalogUpdateRequest(BaseModel):
    item_name: Optional[str] = None
    default_price: Optional[float] = None


class ItemCatalogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_category: str
    item_name: str
    default_price: Optional[float]
