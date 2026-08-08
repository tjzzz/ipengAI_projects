"""Authentication helpers (login decorator)."""

from functools import wraps
from flask import session, jsonify


def login_required(f):
    """Require user to be logged in. Returns 401 with login_required flag."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({"error": "请先登录", "login_required": True}), 401
        return f(*args, **kwargs)
    return decorated_function
