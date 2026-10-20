from flask import Blueprint

api_bp = Blueprint("api", __name__, url_prefix="/api")

from app.api import account, admin, auth, sync  # noqa: E402,F401
