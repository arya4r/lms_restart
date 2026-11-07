import os
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .auth import hash_password
from .db import Base, engine, SessionLocal, add_missing_columns
from .logs import setup as setup_logging, log as lms_log
import time as _time
from .models import User, LoanProduct


origins = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o]


def startup():
    setup_logging(engine)
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    with SessionLocal() as db:
        if not db.query(User).first():
            db.add(User(username=os.getenv("ADMIN_USERNAME", "admin"), full_name="Administrator",
                        role="ADMIN",
                        password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "ChangeMe@123"))))
        if not db.query(LoanProduct).first():
            db.add(LoanProduct(code="PL-STD", name="Personal Loan", interest_method="REDUCING",
                               default_rate=18, min_tenure=3, max_tenure=60, min_amount=10000,
                               max_amount=2500000, apportion_mode="HEAD_WISE", excess_mode="HOLD",
                               late_fee=500, grace_days=3, bounce_charge=590,
                               foreclosure_fee_pct=4, processing_fee_pct=2))
        db.commit()


@asynccontextmanager
async def lifespan(_app):
    startup()
    yield


app = FastAPI(title="LMS", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
@app.middleware("http")
async def log_requests(request, call_next):
    """One terminal line per request that matters: uploads, reports and exports, with timing."""
    watched = request.url.path.startswith(("/api/import", "/api/reports", "/api/export", "/api/loans/"))
    t0 = _time.perf_counter()
    if watched and request.method != "GET" or request.url.path.startswith(("/api/import", "/api/reports")):
        lms_log.info("start  %s %s", request.method, request.url.path)
    response = await call_next(request)
    if watched and (request.method != "GET" or request.url.path.startswith(("/api/import", "/api/reports"))):
        lms_log.info("done   %s %s  status %s  in %.2fs", request.method, request.url.path,
                     response.status_code, _time.perf_counter() - t0)
    return response


app.include_router(router)


@app.get("/api/health")
def health():
    return {"ok": True}


# Serve the built React app from the same container (frontend/dist copied to ./static)
STATIC = Path(__file__).resolve().parent.parent / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (STATIC / path).resolve()
        ok = path and f.is_file() and f.is_relative_to(STATIC.resolve())
        return FileResponse(f if ok else STATIC / "index.html")
