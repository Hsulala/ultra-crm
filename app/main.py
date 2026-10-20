from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers import internal, line_webhook, remote
from app.routers.admin import accounts as admin_accounts
from app.routers.admin import auth as admin_auth
from app.routers.admin import bookings as admin_bookings
from app.routers.admin import cash as admin_cash
from app.routers.admin import class_records as admin_class_records
from app.routers.admin import contracts as admin_contracts
from app.routers.admin import legacy_import as admin_legacy_import
from app.routers.admin import members as admin_members
from app.routers.admin import revenue as admin_revenue
from app.routers.admin import schedule as admin_schedule
from app.routers.admin import settings as admin_settings
from app.routers.admin import venue_bookings as admin_venue_bookings
from app.routers.admin import venue_coaches as admin_venue_coaches
from app.routers.liff_api import binding as liff_binding
from app.routers.liff_api import bookings as liff_bookings
from app.routers.liff_api import class_records as liff_class_records
from app.routers.liff_api import contracts as liff_contracts
from app.routers.liff_api import schedule as liff_schedule
from app.routers.liff_api import venue_bookings as liff_venue_bookings

app = FastAPI(title="Ultra Fitness CRM")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key, same_site="lax")

app.include_router(admin_auth.router)
app.include_router(admin_accounts.router)
app.include_router(admin_bookings.router)
app.include_router(admin_members.router)
app.include_router(admin_legacy_import.router)
app.include_router(admin_contracts.router)
app.include_router(admin_class_records.router)
app.include_router(admin_schedule.router)
app.include_router(admin_venue_coaches.router)
app.include_router(admin_revenue.router)
app.include_router(admin_cash.router)
app.include_router(admin_settings.router)
app.include_router(admin_venue_bookings.router)
app.include_router(liff_binding.router)
app.include_router(liff_contracts.router)
app.include_router(liff_class_records.router)
app.include_router(liff_bookings.router)
app.include_router(liff_schedule.router)
app.include_router(liff_venue_bookings.router)
app.include_router(line_webhook.router)
app.include_router(internal.router)
app.include_router(remote.router)
app.add_exception_handler(remote.RemoteError, remote.remote_error_handler)

# LIFF 靜態頁面：本機/測試用同源掛載，正式環境通常會改放到 CDN 或另外的靜態網站服務，
# 但保留這個掛載點對本機開發沒有壞處。
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/liff", StaticFiles(directory="liff", html=True), name="liff")


@app.get("/healthz")
def health_check():
    return {"status": "ok"}
