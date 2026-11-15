from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from main.domain.category import all_categories, get_category
from main.domain.event import INT_MAX
from main.router.schemas import CategoryList, CategoryOut

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


@router.get("", response_model=CategoryList)
async def list_categories() -> CategoryList:
    """Wszystkie kategorie (id i nazwa). Z tej listy formularz bierze id do wydarzenia."""
    items = [CategoryOut(id=c.id, name=c.name) for c in all_categories()]
    return CategoryList(items=items, total=len(items))


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category_by_id(
    category_id: Annotated[int, Path(gt=0, le=INT_MAX)],
) -> CategoryOut:
    category = get_category(category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono kategorii")
    return CategoryOut(id=category.id, name=category.name)
