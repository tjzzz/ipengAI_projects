"""
Download route — download rewritten text in various formats.
"""

from flask import Blueprint, request, jsonify, session
from app.helpers import get_db, generate_file_response

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
        return jsonify({"error": "订单不存在"}), 404

    if user_id and order['user_id'] != user_id:
        return jsonify({"error": "无权访问该订单"}), 403

    if not user_id:
        last = session.get('last_rewritten', {})
        if last.get('order_id') != order_id:
            return jsonify({"error": "请登录后下载"}), 401

    req_format = request.args.get('format', order.get('original_format', 'txt'))
    if req_format not in ['docx', 'pdf', 'txt', 'md']:
        req_format = order.get('original_format', 'txt')

    rewritten_text = order['rewritten_text']
    filename = order.get('original_filename', 'humanized')
    return generate_file_response(rewritten_text, req_format, filename)