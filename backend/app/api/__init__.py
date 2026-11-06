from flask import Blueprint

api_bp = Blueprint("api", __name__, url_prefix="/api")

from app.api import account, admin, auth, edge_store, sync  # noqa: E402,F401
