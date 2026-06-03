"""
Orders routes — list orders, get order detail, re-humanize.
"""

import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, session
from app.extensions import limiter
from app.helpers import get_db, login_required

orders_bp = Blueprint('orders', __name__)


@orders_bp.route('/api/orders')
@limiter.limit("30 per minute")
def api_orders():
    """Get user's order list with pagination. Requires login."""
    from app.models import Order

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "未登录"}), 401

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 50)

    conn = get_db()
    orders, total = Order.get_by_user_id(conn, user_id, page=page, per_page=per_page)

    _safe_keys = ['id', 'order_id', 'user_id', 'original_format', 'original_filename',
                  'word_count', 'price', 'mode', 'original_score', 'rewritten_score',
                  'status', 'payment_status',
                  'paid_at', 'created_at', 'expires_at']
    orders_safe = [
        {k: o[k] for k in _safe_keys if k in o}
        for o in orders
    ]

    total_pages = max(1, (total + per_page - 1) // per_page)

    return jsonify({
        "orders": orders_safe,
        "total": total,
        "page": page,
        "pages": total_pages
    })


@orders_bp.route('/api/orders/<order_id>')
def api_order_detail(order_id):
    """Get details for a specific order. Requires login."""
    from app.models import Order

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "未登录"}), 401

    conn = get_db()
    order = Order.get_by_order_id(conn, order_id)
    if not order:
        return jsonify({"error": "订单不存在"}), 404

    if order['user_id'] != user_id:
        return jsonify({"error": "无权访问该订单"}), 403

    return jsonify({"order": order})


@orders_bp.route('/api/orders/<order_id>/rehumanize', methods=['POST'])
def api_rehumanize(order_id):
    """
    Re-humanize an existing order (free within 7 days).
    Requires login and non-expired order.
    """
    from app.extensions import humanizer_adapter as humanizer
    from app.ai_checker import analyze_text as run_analysis
    from app.models import Order

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "未登录"}), 401

    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'academic')

    conn = get_db()
    order = Order.get_by_order_id(conn, order_id)
    if not order:
        return jsonify({"error": "订单不存在"}), 404

    if order['user_id'] != user_id:
        return jsonify({"error": "无权操作该订单"}), 403

    expires_at = order['expires_at']
    try:
        expires_dt = datetime.fromisoformat(expires_at)
    except (ValueError, TypeError):
        return jsonify({"error": "订单日期异常"}), 500

    if datetime.now(timezone.utc).replace(tzinfo=None) > expires_dt:
        return jsonify({"error": "订单已过期（超过 7 天），请重新购买"}), 410

    try:
        original_text = order['original_text']
        humanized = humanizer.humanize(original_text, mode=mode)
        rewritten_analysis = run_analysis(humanized)

        Order.update_rewrite(conn, order_id, humanized, rewritten_analysis.get('ai_score', 0))

        original_score = order.get('original_score', 0)

        return jsonify({
            "success": True,
            "order_id": order_id,
            "original": {
                "text": original_text,
                "ai_score": round(original_score, 1)
            },
            "rewritten": {
                "text": humanized,
                "ai_score": round(rewritten_analysis['ai_score'], 1),
                "risk_level": rewritten_analysis['risk_level']
            },
            "improvement": round(original_score - rewritten_analysis['ai_score'], 1)
        })
    except Exception:
        logging.exception("Re-humanize failed")
        return jsonify({"error": "改写出错，请稍后重试"}), 500