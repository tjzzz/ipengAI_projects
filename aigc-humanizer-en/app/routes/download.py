"""
Download route — download rewritten text in various formats.
"""

import logging

from flask import Blueprint, request, jsonify, session
from app.helpers import get_db, generate_file_response

logger = logging.getLogger(__name__)

download_bp = Blueprint('download', __name__)


@download_bp.route('/api/download/<order_id>')
def api_download(order_id):
    """
    Download rewritten text in the specified format.
    Requires login (or the order must belong to the current user's session).
    Query params: ?format=docx|pdf|txt|md (default: original_format)
    """
    from app.models import Order

    user_id = session.get('user_id')
    conn = get_db()

    order = Order.get_by_order_id(conn, order_id)
    if not order:
        logger.warning("Download requested for non-existent order: %s (user_id=%s)", order_id, user_id)
        return jsonify({"error": "订单不存在"}), 404

    if user_id and order['user_id'] != user_id:
        logger.warning("Download denied: user %s attempted to access order %s owned by %s",
                        user_id, order_id, order['user_id'])
        return jsonify({"error": "无权访问该订单"}), 403

    if not user_id:
        last = session.get('last_rewritten', {})
        if last.get('order_id') != order_id:
            logger.warning("Download denied: unauthenticated session without matching last_rewritten (order=%s)", order_id)
            return jsonify({"error": "请登录后下载"}), 401

    req_format = request.args.get('format', order.get('original_format', 'txt'))
    if req_format not in ['docx', 'pdf', 'txt', 'md']:
        logger.info("Unsupported download format '%s' for order %s, falling back to '%s'",
                     req_format, order_id, order.get('original_format', 'txt'))
        req_format = order.get('original_format', 'txt')

    rewritten_text = order['rewritten_text']
    filename = order.get('original_filename', 'humanized')

    try:
        logger.info("Download order=%s, user=%s, format=%s, filename=%s (words=%s)",
                    order_id, user_id, req_format, filename,
                    len(rewritten_text.split()) if rewritten_text else 0)
        return generate_file_response(rewritten_text, req_format, filename)
    except Exception:
        logger.exception("Failed to generate download file for order %s (format=%s)", order_id, req_format)
        return jsonify({"error": "文件生成失败，请稍后重试"}), 500