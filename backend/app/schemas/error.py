from pydantic import BaseModel


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorPayload
