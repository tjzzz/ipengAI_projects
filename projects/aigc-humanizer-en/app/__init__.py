"""
AI Humanizer - Application Factory
Creates and configures the Flask application instance.
"""

import os
import logging
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()

# Configure logging: structured format for production debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Project root path (parent of app/)
_PROJ_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__,
                root_path=_PROJ_ROOT,
                template_folder=os.path.join(_PROJ_ROOT, 'templates'),
                static_folder=os.path.join(_PROJ_ROOT, 'static'),
                static_url_path='/static')

    # ── Secret key ──
    if not os.environ.get('SECRET_KEY'):
        raise RuntimeError(
            "SECRET_KEY environment variable must be set. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    app.secret_key = os.environ['SECRET_KEY']

    # ── Configuration ──
    app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
    app.config['UPLOAD_FOLDER'] = os.path.join(_PROJ_ROOT, 'uploads')
    app.config['PAYMENT_ADAPTER'] = os.environ.get('PAYMENT_ADAPTER', 'mock')
    app.config['HUMANIZER_ADAPTER'] = 'rule_based'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)

    # ── Filesystem session ──
    from app.session import FileSystemSessionInterface
    _session_dir = os.path.join(_PROJ_ROOT, 'instance', 'flask_session')
    os.makedirs(_session_dir, exist_ok=True)
    app.session_interface = FileSystemSessionInterface(_session_dir)

    # ── Upload folder ──
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # ── Database ──
    from app.models import init_db
    init_db()

    # ── Adapters ──
    from app.extensions import set_adapters
    from app.payment_adapter import create_payment_adapter
    from app.humanizer_adapter import RuleBasedHumanizer, ApiHumanizer

    payment_adapter = create_payment_adapter()
    if app.config.get('HUMANIZER_ADAPTER') == 'api':
        humanizer_adapter = ApiHumanizer()
        logging.info("Using ApiHumanizer (ai-text-humanizer.com)")
    else:
        humanizer_adapter = RuleBasedHumanizer()
    set_adapters(payment_adapter, humanizer_adapter)

    # ── Safety check: mock adapter in production ──
    if app.config.get('PAYMENT_ADAPTER') == 'mock' and os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError(
            "Refusing to start: PAYMENT_ADAPTER=mock is not allowed in production. "
            "Set PAYMENT_ADAPTER=alipay and configure Alipay credentials."
        )
    if app.config.get('PAYMENT_ADAPTER') == 'mock':
        logging.warning("PAYMENT_ADAPTER=mock is enabled. This should only be used for development.")

    # ── Extensions (csrf, limiter) ──
    from app.extensions import csrf, limiter
    csrf.init_app(app)
    limiter.init_app(app)

    # ── Startup: recover stuck processing orders ──
    from app.helpers import recover_processing_orders
    from app.extensions import rewrite_executor
    rewrite_executor.submit(recover_processing_orders)

    # ── Register all blueprints ──
    from app.routes import main_bp, auth_bp, analysis_bp, rewrite_bp, \
        payment_bp, download_bp, orders_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(rewrite_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(orders_bp)

    # ── Teardown: close database connection ──
    from app.helpers import close_db
    app.teardown_appcontext(close_db)

    # ── Security headers ──
    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses."""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '0'  # Deprecated, kept for legacy compat
        return response

    # ── Global error handlers ──
    @app.errorhandler(400)
    def handle_400(e):
        return jsonify({"error": "请求格式错误"}), 400

    @app.errorhandler(401)
    def handle_401(e):
        return jsonify({"error": "需要登录", "login_required": True}), 401

    @app.errorhandler(413)
    def handle_413(e):
        return jsonify({"error": "文件过大，最大支持 20MB"}), 413

    @app.errorhandler(403)
    def handle_403(e):
        return jsonify({"error": "无权访问"}), 403

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify({"error": "请求的资源不存在"}), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify({"error": "请求方法不允许"}), 405

    @app.errorhandler(500)
    def handle_500(e):
        logging.exception("Internal server error")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500

    # ── CSRF Exemptions ──
    # Only the Alipay webhook needs CSRF exemption (called by Alipay servers, not browsers)
    # All other API routes are protected by CSRF via X-CSRFToken header from frontend
    webhook_endpoint = 'payment.api_webhook_alipay'
    _webhook_func = app.view_functions.get(webhook_endpoint)
    if _webhook_func:
        csrf.exempt(_webhook_func)

    return app