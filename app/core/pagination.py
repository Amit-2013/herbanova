"""Server-side pagination helpers.

Lists stay JSON arrays for compatibility with existing callers, but every
paginated request also returns `X-Total-Count`. A caller that omits `page`
still gets the full (bounded) list, which the selector endpoints need.
The sort column is always chosen from an explicit whitelist, never from the
raw query string.
"""
from typing import Any

from fastapi import Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def page_params(page: int | None = Query(None, ge=1),
                page_size: int = Query(50, ge=1, le=200)) -> tuple[int | None, int]:
    return page, page_size


def sort_column(model, sort: str | None, allowed: dict[str, Any], default):
    return allowed.get(sort or "", default)


def paginate(db: Session, stmt, response: Response, page: int | None, page_size: int,
             count_stmt=None) -> list:
    total = db.scalar(count_stmt if count_stmt is not None
                      else select(func.count()).select_from(stmt.order_by(None).subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    if page is None:
        return list(db.scalars(stmt).all())
    return list(db.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).all())
