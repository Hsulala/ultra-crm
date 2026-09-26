from fastapi.templating import Jinja2Templates

from app.models import ADMIN_ROLE_LABELS

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["ADMIN_ROLE_LABELS"] = ADMIN_ROLE_LABELS
