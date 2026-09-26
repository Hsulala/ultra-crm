from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import ItemCatalogEntry


class ItemCatalogError(Exception):
    pass


def create_item(
    db: Session, *, item_category: str, item_name: str, default_price: Optional[float] = None
) -> ItemCatalogEntry:
    if item_category not in ("service", "venue_rental", "membership", "beverage", "coaching", "custom"):
        raise ItemCatalogError("item_category 不合法")

    entry = ItemCatalogEntry(item_category=item_category, item_name=item_name, default_price=default_price)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_item(
    db: Session, *, item_id: int, item_name: Optional[str] = None, default_price: Optional[float] = None
) -> ItemCatalogEntry:
    entry = db.get(ItemCatalogEntry, item_id)
    if entry is None:
        raise ItemCatalogError("找不到這個品項")
    if item_name is not None:
        entry.item_name = item_name
    entry.default_price = default_price
    db.commit()
    db.refresh(entry)
    return entry


def deactivate_item(db: Session, *, item_id: int) -> None:
    entry = db.get(ItemCatalogEntry, item_id)
    if entry is None:
        raise ItemCatalogError("找不到這個品項")
    entry.is_active = False
    db.commit()


def list_active_items(db: Session) -> List[ItemCatalogEntry]:
    return (
        db.query(ItemCatalogEntry)
        .filter(ItemCatalogEntry.is_active == True)  # noqa: E712
        .order_by(ItemCatalogEntry.item_category, ItemCatalogEntry.item_name)
        .all()
    )


def get_items_grouped_by_category(db: Session) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {
        "service": [], "venue_rental": [], "membership": [], "beverage": [], "coaching": [], "custom": [],
    }
    for item in list_active_items(db):
        grouped.setdefault(item.item_category, []).append(
            {
                "id": item.id,
                "name": item.item_name,
                "price": float(item.default_price) if item.default_price is not None else None,
            }
        )
    return grouped
