"""
Authentication routes — register, login, logout, user info.
"""

import re
import logging
from flask import Blueprint, request, jsonify, session
from app.extensions import limiter
from app.helpers import get_db

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/register', methods=['POST'])
@limiter.limit("60 per hour")
def api_register():
    """Register a new user account."""
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not email or not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        return jsonify({"error": "请输入有效的邮箱地址"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码长度至少 6 位"}), 400
    if not re.search(r'[A-Z]', password):
        return jsonify({"error": "密码必须包含至少一个大写字母"}), 400
    if not re.search(r'[a-z]', password):
        return jsonify({"error": "密码必须包含至少一个小写字母"}), 400
    if not re.search(r'[0-9]', password):
        return jsonify({"error": "密码必须包含至少一个数字"}), 400
    if password != confirm_password:
        return jsonify({"error": "两次密码输入不一致"}), 400

    from app.models import User
    conn = get_db()
    existing = User.get_by_email(conn, email)
    if existing:
        return jsonify({"error": "该邮箱已被注册"}), 409

    try:
        user = User.create(conn, email, password)
        session['user_id'] = user['id']
        session.permanent = True
        return jsonify({
            "success": True,
            "user": {"id": user['id'], "email": user['email']}
        }), 201
    except Exception:
        logging.exception("注册失败")
        return jsonify({"error": "注册失败，请稍后重试"}), 500


@auth_bp.route('/api/login', methods=['POST'])
@limiter.limit("60 per hour")
def api_login():
    """Log in an existing user."""
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({"error": "请填写邮箱和密码"}), 400

    from app.models import User
    conn = get_db()
    user = User.verify_password(conn, email, password)
    if not user:
        return jsonify({"error": "邮箱或密码错误"}), 401

    session['user_id'] = user['id']
    session.permanent = True
    return jsonify({
        "success": True,
        "user": {"id": user['id'], "email": user['email']}
    })


@auth_bp.route('/api/logout', methods=['POST'])
def api_logout():
    """Log out the current user."""
    session.clear()
    return jsonify({"success": True})


@auth_bp.route('/api/me')
def api_me():
    """Get current logged-in user info."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "未登录"}), 401

    from app.models import User
    conn = get_db()
    user = User.get_by_id(conn, user_id)
    if not user:
        session.pop('user_id', None)
        return jsonify({"error": "未登录"}), 401

    return jsonify({
        "user": {"id": user['id'], "email": user['email']}
    })