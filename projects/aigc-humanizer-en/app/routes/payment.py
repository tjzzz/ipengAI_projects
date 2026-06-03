"""
Payment routes — create payment order, check payment status,
Alipay webhook handler, and test mock payment.
"""

import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from app.extensions import limiter
from app.helpers import get_db, login_required, process_payment_success
from app.config import PRICE_PER_1000_WORDS

payment_bp = Blueprint('payment', __name__)


@payment_bp.route('/api/payment-config', methods=['GET'])
def api_payment_config():
    """
    Get payment configuration info (adapter type).
    """
    from flask import current_app
    
    adapter_type = current_app.config.get('PAYMENT_ADAPTER', 'mock')
    
    return jsonify({
        "adapter_type": adapter_type,
        "is_mock": adapter_type == 'mock'
    })


@payment_bp.route('/api/create-payment', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def api_create_payment():
    """
    Create a payment order and return QR code for scanning.
    """
    from app.extensions import payment_adapter as adapter
    from app.models import Order

    data = request.get_json(silent=True) or {}
    text = data.get('text') or session.get('last_text', '')
    mode = data.get('mode', 'academic')

    if not text:
        return jsonify({"error": "没有可改写的文本，请先分析"}), 400

    word_count = len(text.split())
    price = max(PRICE_PER_1000_WORDS * (word_count / 1000), PRICE_PER_1000_WORDS)
    price = round(price, 2)

    # 生成格式: order_YYYYMMDD_随机字符
    date_str = datetime.now().strftime("%Y%m%d")
    random_str = uuid.uuid4().hex[:6].lower()
    order_id = f"order_{date_str}_{random_str}"

    original_format = session.get('last_original_format', 'txt')
    original_filename = session.get('last_original_filename', None)
    user_id = session.get('user_id')

    conn = get_db()
    try:
        Order.create_payment_record(
            conn, user_id, order_id, text, original_format, original_filename,
            word_count, price, mode
        )
        logging.info(f"[PAYMENT] Order created in DB: {order_id}, user={user_id}, words={word_count}, price={price}")
    except Exception:
        logging.exception("Failed to create payment order")
        return jsonify({"error": "创建订单失败，请稍后重试"}), 500

    logging.info(f"[PAYMENT] Calling adapter.create_prepay_order for {order_id}")
    result = adapter.create_prepay_order(
        order_id, price, f"AI降AI率服务 - {word_count}词"
    )
    logging.info(f"[PAYMENT] Adapter result for {order_id}: has_error={bool(result.get('error'))}, has_qr={bool(result.get('qr_code'))}")

    if result.get('error'):
        logging.error(
            f"Payment adapter create_prepay_order failed: "
            f"error={result.get('error')}, "
            f"code={result.get('code')}, "
            f"sub_code={result.get('sub_code')}, "
            f"order_id={result.get('order_id')}"
        )
        return jsonify({"error": result['error']}), 500

    qr_code = result.get('qr_code')
    if qr_code:
        Order.save_qr_code(conn, order_id, qr_code)

    return jsonify({
        "success": True,
        "order": {
            "order_id": order_id,
            "word_count": word_count,
            "price": price,
            "qr_code": qr_code,
            "mode": mode,
            "expires_in": result.get('expires_in', 600)
        }
    })


@payment_bp.route('/api/payment-status/<order_id>')
@limiter.limit("20 per minute")
@login_required
def api_payment_status(order_id):
    """Check payment status for an order (used by frontend polling)."""
    from app.extensions import payment_adapter as adapter
    from app.models import Order

    user_id = session.get('user_id')
    conn = get_db()

    Order.expire_old_orders(conn)

    order = Order.get_by_order_id(conn, order_id)
    logging.info(f"[POLL] order_id={order_id}, user={user_id}, found={order is not None}")
    if not order:
        return jsonify({"error": "订单不存在"}), 404

    if order['user_id'] != user_id:
        return jsonify({"error": "无权访问该订单"}), 403

    payment_status = order.get('payment_status', 'pending')
    status = order.get('status', 'pending')

    if payment_status == 'pending':
        try:
            query_result = adapter.query_payment(order_id)
            logging.info(
                f"Payment query for {order_id}: "
                f"trade_status={query_result.get('trade_status')}, "
                f"status={query_result.get('status')}"
            )
            if query_result.get('status') == 'paid':
                trade_no = query_result.get('trade_no') or f"QUERY_{order_id}"
                process_payment_success(conn, order_id, trade_no)
                # Refresh order from DB to get updated status
                order = Order.get_by_order_id(conn, order_id)
                payment_status = order.get('payment_status', 'paid')
                status = order.get('status', 'processing')
        except Exception:
            logging.warning("Payment query failed, returning current status", exc_info=True)

    response = {
        "order_id": order_id,
        "payment_status": payment_status,
        "status": status,
        "price": order.get('price'),
        "word_count": order.get('word_count')
    }

    if status == 'completed' and order.get('rewritten_text'):
        from app.helpers import derive_risk_level
        original_score = order.get('original_score', 0) or 0
        rewritten_score = order.get('rewritten_score', 0) or 0
        response.update({
            "success": True,
            "original": {
                "text": order['original_text'],
                "ai_score": round(original_score, 1),
                "risk_level": derive_risk_level(original_score)
            },
            "rewritten": {
                "text": order['rewritten_text'],
                "ai_score": round(rewritten_score, 1),
                "risk_level": derive_risk_level(rewritten_score) if order['rewritten_text'] else 'unknown'
            },
            "improvement": round((order.get('original_score', 0) or 0) - (order.get('rewritten_score', 0) or 0), 1),
            "original_format": order.get('original_format', 'txt'),
            "original_filename": order.get('original_filename')
        })

    return jsonify(response)


@payment_bp.route('/api/webhook/alipay', methods=['POST'])
def api_webhook_alipay():
    """
    Alipay async notification webhook.
    Called by Alipay servers after payment is completed.
    """
    from app.extensions import payment_adapter as adapter
    from app.models import Order

    params = request.form.to_dict()
    sign = params.pop('sign', None)
    sign_type = params.pop('sign_type', None)

    is_valid, order_id, trade_no, amount = adapter.verify_notification(params, sign)

    if not is_valid:
        return "fail", 200

    conn = get_db()
    order = Order.get_by_order_id(conn, order_id)
    if not order:
        return "fail", 200

    if order.get('payment_status') != 'pending':
        return "success", 200

    if amount and abs(round(amount * 100) - round((order.get('price') or 0) * 100)) > 1:
        return "fail", 200

    if trade_no:
        existing = conn.execute(
            "SELECT order_id FROM orders WHERE alipay_trade_no = ? AND order_id != ?",
            (trade_no, order_id)
        ).fetchone()
        if existing:
            logging.warning(f"Duplicate trade_no {trade_no} attempted for order {order_id}, already used by {existing['order_id']}")
            return "fail", 200

    try:
        process_payment_success(conn, order_id, trade_no)
    except Exception:
        logging.exception(f"Payment processing failed for order {order_id}")
        return "fail", 200

    return "success", 200


@payment_bp.route('/api/test/mock-payment/<order_id>', methods=['POST'])
@limiter.limit("3 per minute")
def api_test_mock_payment(order_id):
    """
    Simulate a successful payment for testing purposes.
    Only available when PAYMENT_ADAPTER=mock.
    """
    from flask import current_app
    from app.models import Order

    if current_app.config.get('PAYMENT_ADAPTER') != 'mock':
        return jsonify({"error": "仅在 mock 模式下可用"}), 403

    conn = get_db()
    order = Order.get_by_order_id(conn, order_id)
    if not order:
        return jsonify({"error": "订单不存在"}), 404

    if order.get('payment_status') != 'pending':
        return jsonify({"error": f"订单状态不是 pending，当前: {order.get('payment_status')}"}), 400

    trade_no = f"MOCK_TRADE_{order_id}"
    try:
        process_payment_success(conn, order_id, trade_no)
        return jsonify({"success": True, "message": "支付模拟成功，正在后台改写...", "order_id": order_id})
    except Exception:
        logging.exception("Mock payment processing failed")
        return jsonify({"error": "支付处理失败，请稍后重试"}), 500