"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from frame_it.auth.principal import Principal, resolve_principal
from frame_it.context import AppContext
from frame_it.errors import forbidden, unauthorized


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


def get_session(ctx: Ctx) -> Iterator[Session]:
    with ctx.db.session() as session:
        yield session


DbSession = Annotated[Session, Depends(get_session)]


def get_principal(request: Request, ctx: Ctx) -> Principal:
    cached: Principal | None = getattr(request.state, "principal", None)
    if cached is None:
        cached = resolve_principal(request, ctx.settings, ctx.db)
        request.state.principal = cached
    return cached


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_uploader(principal: CurrentPrincipal) -> Principal:
    """Any authenticated device (uploader or admin)."""
    if not principal.is_authenticated:
        raise unauthorized()
    return principal


def require_admin(principal: CurrentPrincipal) -> Principal:
    if not principal.is_authenticated:
        raise unauthorized()
    if not principal.is_admin:
        raise forbidden()
    return principal


Uploader = Annotated[Principal, Depends(require_uploader)]
Admin = Annotated[Principal, Depends(require_admin)]
