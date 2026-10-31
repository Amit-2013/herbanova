"""The module register behind the Overview screen (COR-007 rule 4).

The screen shows what this endpoint returns; it no longer carries its own copy of
the list. Reading needs a signed-in user - the Overview is part of the normal
navigation, so no extra permission applies - and the response contains no
personal data.
"""
from fastapi import APIRouter, Depends

from ..core import module_register
from ..core.rbac import require_login

router = APIRouter(prefix="/api/modules", tags=["modules"])


@router.get("")
def get_modules(_=Depends(require_login)):
    """Every tracked module, its group, and the figures derived from them."""
    return module_register.payload()
