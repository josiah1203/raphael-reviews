"""Raphael reviews service."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from raphael_contracts.errors import ErrorResponse
from raphael_reviews.routes import router

app = FastAPI(title="raphael-reviews", version="0.1.0")
app.include_router(router, prefix="/v1/reviews")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "raphael-reviews"}


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content=ErrorResponse(code="internal_error", message=str(exc)).model_dump())
