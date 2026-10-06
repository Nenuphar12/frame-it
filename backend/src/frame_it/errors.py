"""RFC 9457 problem details. The frontend maps `code` to an i18n key (`errors.<code>`)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_BASE = "https://frame-it/errors/"
PROBLEM_MEDIA_TYPE = "application/problem+json"


class Problem(BaseModel):
    type: str
    code: str
    title: str
    status: int
    detail: str | None = None
    extra: dict[str, Any] | None = None


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"{status} {code}: {detail or title}")
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.extra = extra
        self.headers = headers

    def to_problem(self) -> Problem:
        return Problem(
            type=PROBLEM_BASE + self.code,
            code=self.code,
            title=self.title,
            status=self.status,
            detail=self.detail,
            extra=self.extra,
        )


def problem_response(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ProblemError(status, code, title, detail, extra).to_problem()
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


# Convenience constructors ----------------------------------------------------------------------


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "not_found", "Not found", f"{what} not found")


def forbidden(detail: str = "Insufficient permissions") -> ProblemError:
    return ProblemError(403, "forbidden", "Forbidden", detail)


def unauthorized() -> ProblemError:
    return ProblemError(401, "unauthorized", "Authentication required")


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(_: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            exc.status, exc.code, exc.title, exc.detail, exc.extra, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return problem_response(
            422, "validation_error", "Invalid request", extra={"errors": errors}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        detail = exc.detail if isinstance(exc.detail, str) else None
        return problem_response(exc.status_code, code, code.replace("_", " ").capitalize(), detail)
