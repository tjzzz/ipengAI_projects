"""
Main page routes — index, orders page, health check.
"""

from flask import Blueprint, render_template, session, jsonify
from datetime import datetime, timezone

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Landing page."""
    return render_template('index.html')


@main_bp.route('/orders')
def orders_page():
    """Order history page — requires login."""
    user_id = session.get('user_id')
    if not user_id:
        return render_template('orders.html', needs_login=True)
    return render_template('orders.html', needs_login=False)


@main_bp.route('/api/health')
def api_health():
    """Health check endpoint for monitoring and load balancers."""
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})