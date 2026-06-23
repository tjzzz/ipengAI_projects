#!/usr/bin/env python3
"""
Admin dashboard for AI Humanizer — standalone app, zero coupling with main app.

Usage:
    python admin.py                     # default port 5001
    ADMIN_PORT=5002 python admin.py    # custom port

Authentication:
    Set ADMIN_PASSWORD in .env, otherwise defaults to 'admin123'.
    Login via session cookie, auto-expires after 2 hours of inactivity.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ---------- Config ----------
PROJ_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJ_ROOT, 'instance', 'aigc_humanizer.db')
ADMIN_PORT = int(os.environ.get('ADMIN_PORT', 5001))
ADMIN_SECRET_KEY = os.environ.get('ADMIN_SECRET_KEY', os.urandom(24).hex())
ADMIN_PASSWORD_HASH = generate_password_hash(
    os.environ.get('ADMIN_PASSWORD', 'admin123'), method='pbkdf2:sha256'
)
SESSION_LIFETIME_MINUTES = 120  # 2 hours

# ---------- App ----------
admin_app = Flask(__name__, template_folder=os.path.join(PROJ_ROOT, 'templates'))
admin_app.secret_key = ADMIN_SECRET_KEY
admin_app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=SESSION_LIFETIME_MINUTES)


def get_db():
    """Get a read-only SQLite connection to the main database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def login_required(f):
    """Decorator: redirect to login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ============================================================
#  Routes
# ============================================================

@admin_app.route('/admin/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.permanent = True
            session['admin_authenticated'] = True
            session['admin_login_time'] = datetime.now(timezone.utc).isoformat()
            return redirect(url_for('dashboard'))
        error = '密码错误'
    return render_template_string(LOGIN_TEMPLATE, error=error)


@admin_app.route('/admin/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@admin_app.route('/admin')
@login_required
def dashboard():
    return render_template_string(DASHBOARD_TEMPLATE)


# ---------- API ----------

@admin_app.route('/admin/api/orders')
@login_required
def api_orders():
    """Return orders for a given date range as JSON."""
    start_date = request.args.get('start', '')
    end_date = request.args.get('end', '')
    page = int(request.args.get('page', 1))

    # Validate dates
    try:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'error': '请提供有效的日期，格式 YYYY-MM-DD'}), 400

    if start_dt > end_dt:
        return jsonify({'error': '开始日期不能晚于结束日期'}), 400

    start_iso = datetime.combine(start_dt, datetime.min.time()).isoformat()
    end_iso = datetime.combine(end_dt + timedelta(days=1), datetime.min.time()).isoformat()

    conn = get_db()
    per_page = 50

    try:
        # Total count
        count_row = conn.execute(
            "SELECT COUNT(*) as total FROM orders WHERE created_at >= ? AND created_at < ?",
            (start_iso, end_iso)
        ).fetchone()
        total = count_row['total'] if count_row else 0

        # Summary stats
        paid_count = conn.execute(
            "SELECT COUNT(*) as total FROM orders WHERE created_at >= ? AND created_at < ? AND payment_status = 'paid'",
            (start_iso, end_iso)
        ).fetchone()['total']

        total_revenue = conn.execute(
            "SELECT COALESCE(SUM(price), 0) as total FROM orders "
            "WHERE created_at >= ? AND created_at < ? AND payment_status = 'paid'",
            (start_iso, end_iso)
        ).fetchone()['total']

        # Status breakdown
        status_counts = {}
        for row in conn.execute(
            "SELECT payment_status, COUNT(*) as cnt FROM orders "
            "WHERE created_at >= ? AND created_at < ? "
            "GROUP BY payment_status",
            (start_iso, end_iso)
        ).fetchall():
            status_counts[row['payment_status']] = row['cnt']

        # Orders page
        offset = (page - 1) * per_page
        cursor = conn.execute(
            """SELECT o.*, u.email as user_email
               FROM orders o
               LEFT JOIN users u ON o.user_id = u.id
               WHERE o.created_at >= ? AND o.created_at < ?
               ORDER BY o.created_at DESC
               LIMIT ? OFFSET ?""",
            (start_iso, end_iso, per_page, offset)
        )
        orders = []
        for row in cursor.fetchall():
            order = dict(row)
            if order.get('original_text'):
                order['original_text_preview'] = order['original_text'][:200]
            if order.get('rewritten_text'):
                order['rewritten_text_preview'] = order['rewritten_text'][:200]
            orders.append(order)

        return jsonify({
            'start_date': start_date,
            'end_date': end_date,
            'summary': {
                'total_orders': total,
                'paid_orders': paid_count,
                'pending_orders': status_counts.get('pending', 0),
                'expired_orders': status_counts.get('expired', 0),
                'failed_orders': status_counts.get('failed', 0),
                'total_revenue': round(total_revenue, 2),
            },
            'orders': orders,
            'page': page,
            'per_page': per_page,
            'total_pages': max((total + per_page - 1) // per_page, 1),
        })
    finally:
        conn.close()


@admin_app.route('/admin/api/order/<order_id>')
@login_required
def api_order_detail(order_id):
    """Return full detail for a single order."""
    conn = get_db()
    try:
        cursor = conn.execute(
            """SELECT o.*, u.email as user_email
               FROM orders o
               LEFT JOIN users u ON o.user_id = u.id
               WHERE o.order_id = ?""",
            (order_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': '订单不存在'}), 404
        return jsonify(dict(row))
    finally:
        conn.close()


# ============================================================
#  Jinja2 Templates (inline to keep everything in one file)
# ============================================================

LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>管理后台 - 登录</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f1f5f9;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh;
        }
        .login-card {
            background: #fff; border-radius: 12px; padding: 40px; width: 380px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08);
        }
        .login-card h1 {
            font-size: 1.5rem; font-weight: 700; color: #1e293b;
            margin-bottom: 8px; text-align: center;
        }
        .login-card p {
            font-size: 0.875rem; color: #94a3b8; text-align: center;
            margin-bottom: 28px;
        }
        .form-group { margin-bottom: 20px; }
        .form-group label {
            display: block; font-size: 0.875rem; font-weight: 600;
            color: #334155; margin-bottom: 6px;
        }
        .form-group input {
            width: 100%; padding: 10px 14px; border: 1px solid #e2e8f0;
            border-radius: 8px; font-size: 1rem; color: #1e293b;
            outline: none; transition: border-color 0.15s;
        }
        .form-group input:focus { border-color: #4f46e5; box-shadow: 0 0 0 3px rgba(79,70,229,0.1); }
        .btn {
            width: 100%; padding: 10px; background: #4f46e5; color: #fff;
            border: none; border-radius: 8px; font-size: 1rem; font-weight: 600;
            cursor: pointer; transition: background 0.15s;
        }
        .btn:hover { background: #4338ca; }
        .error {
            background: #fef2f2; color: #dc2626; padding: 10px 14px;
            border-radius: 8px; font-size: 0.875rem; margin-bottom: 16px;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>🔐 管理后台</h1>
        <p>AI Humanizer Admin</p>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <div class="form-group">
                <label for="password">管理员密码</label>
                <input type="password" id="password" name="password" placeholder="请输入密码" autofocus required>
            </div>
            <button type="submit" class="btn">登 录</button>
        </form>
    </div>
</body>
</html>"""


DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>管理后台 - AI Humanizer</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f1f5f9; color: #1e293b; min-height: 100vh;
        }
        .header {
            background: #fff; border-bottom: 1px solid #e2e8f0;
            padding: 0 24px; height: 60px; display: flex;
            align-items: center; justify-content: space-between;
        }
        .header h1 { font-size: 1.125rem; font-weight: 700; }
        .header-right { display: flex; align-items: center; gap: 16px; }
        .btn-logout {
            background: #fee2e2; color: #dc2626; border: none;
            padding: 6px 16px; border-radius: 6px; font-size: 0.875rem;
            cursor: pointer; font-weight: 500;
        }
        .btn-logout:hover { background: #fecaca; }
        .main { max-width: 1400px; margin: 0 auto; padding: 24px; }
        /* Toolbar */
        .toolbar {
            display: flex; align-items: center; gap: 10px; margin-bottom: 24px;
            flex-wrap: wrap;
        }
        .toolbar label {
            font-size: 0.875rem; font-weight: 600; color: #475569;
        }
        .toolbar input[type="date"] {
            padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px;
            font-size: 0.9rem; color: #1e293b; outline: none;
        }
        .toolbar input[type="date"]:focus { border-color: #4f46e5; }
        .date-sep { color: #94a3b8; font-weight: 500; }
        .btn-query {
            padding: 8px 20px; background: #4f46e5; color: #fff;
            border: none; border-radius: 8px; font-size: 0.9rem; font-weight: 600;
            cursor: pointer;
        }
        .btn-query:hover { background: #4338ca; }
        .btn-preset {
            padding: 6px 14px; background: #fff; color: #475569;
            border: 1px solid #e2e8f0; border-radius: 8px; font-size: 0.825rem;
            cursor: pointer; white-space: nowrap;
        }
        .btn-preset:hover { background: #f1f5f9; border-color: #cbd5e1; }
        .btn-preset.active { background: #eef2ff; color: #4f46e5; border-color: #4f46e5; }
        /* Summary cards */
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 14px; margin-bottom: 24px;
        }
        .summary-card {
            background: #fff; border-radius: 12px; padding: 18px 20px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.04);
        }
        .summary-card .label {
            font-size: 0.75rem; color: #94a3b8; margin-bottom: 4px;
            text-transform: uppercase; letter-spacing: 0.05em;
        }
        .summary-card .value {
            font-size: 1.5rem; font-weight: 700; color: #1e293b;
        }
        .summary-card .value.revenue { color: #059669; }
        .summary-card .value.pending { color: #ca8a04; }
        /* Loading */
        .loading { text-align: center; padding: 60px 0; color: #94a3b8; }
        .spinner {
            display: inline-block; width: 28px; height: 28px;
            border: 3px solid #e2e8f0; border-top-color: #4f46e5;
            border-radius: 50%; animation: spin 0.8s linear infinite;
            margin-bottom: 12px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        /* Table */
        .table-wrapper {
            background: #fff; border-radius: 12px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.04); overflow: hidden;
        }
        .table-header {
            padding: 16px 20px; display: flex; align-items: center;
            justify-content: space-between; border-bottom: 1px solid #f1f5f9;
        }
        .table-header h2 { font-size: 1rem; font-weight: 600; }
        .count-badge {
            background: #eef2ff; color: #4f46e5; font-size: 0.8rem;
            padding: 2px 12px; border-radius: 12px; font-weight: 600;
        }
        table {
            width: 100%; border-collapse: collapse;
        }
        th {
            text-align: left; padding: 10px 16px;
            font-size: 0.725rem; font-weight: 600; color: #94a3b8;
            text-transform: uppercase; letter-spacing: 0.05em;
            background: #f8fafc; border-bottom: 1px solid #e2e8f0;
            white-space: nowrap;
        }
        td {
            padding: 10px 16px; font-size: 0.85rem;
            border-bottom: 1px solid #f1f5f9; vertical-align: top;
        }
        tr.row-order { cursor: pointer; transition: background 0.1s; }
        tr.row-order:hover { background: #f8fafc; }
        tr.row-detail { background: #f8fafc; }
        tr.row-detail td { padding: 16px; }
        .detail-grid {
            display: grid; grid-template-columns: 1fr 1fr; gap: 20px;
        }
        @media (max-width: 768px) {
            .detail-grid { grid-template-columns: 1fr; }
            .summary { grid-template-columns: repeat(2, 1fr); }
        }
        .detail-box h4 {
            font-size: 0.75rem; font-weight: 700; color: #64748b;
            text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px;
        }
        .detail-box .text-content {
            background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
            padding: 12px; font-size: 0.85rem; line-height: 1.6;
            color: #334155; white-space: pre-wrap; word-break: break-word;
            max-height: 300px; overflow-y: auto;
        }
        .detail-meta {
            display: flex; flex-wrap: wrap; gap: 8px;
            font-size: 0.78rem; color: #64748b;
        }
        .detail-meta span {
            background: #f1f5f9; padding: 2px 10px; border-radius: 4px;
        }
        .badge {
            display: inline-block; padding: 2px 10px; border-radius: 12px;
            font-size: 0.725rem; font-weight: 600; white-space: nowrap;
        }
        .badge-paid { background: #dcfce7; color: #16a34a; }
        .badge-pending { background: #fef9c3; color: #ca8a04; }
        .badge-expired { background: #f1f5f9; color: #64748b; }
        .badge-failed { background: #fee2e2; color: #dc2626; }
        .badge-completed { background: #dbeafe; color: #2563eb; }
        .badge-processing { background: #f3e8ff; color: #9333ea; }
        /* Pagination */
        .pagination {
            display: flex; align-items: center; justify-content: center;
            gap: 12px; padding: 16px 20px; border-top: 1px solid #f1f5f9;
        }
        .pagination button {
            padding: 6px 16px; border: 1px solid #e2e8f0; border-radius: 6px;
            background: #fff; font-size: 0.875rem; cursor: pointer; color: #334155;
        }
        .pagination button:hover:not(:disabled) { background: #f1f5f9; }
        .pagination button:disabled { opacity: 0.4; cursor: not-allowed; }
        .pagination .page-info { font-size: 0.875rem; color: #64748b; }
        /* Empty */
        .empty { text-align: center; padding: 60px 20px; color: #94a3b8; }
        .empty-icon { font-size: 2.5rem; margin-bottom: 12px; }
        /* Error */
        .error-banner {
            background: #fef2f2; color: #dc2626; padding: 12px 20px;
            border-radius: 8px; margin-bottom: 16px; font-size: 0.875rem;
        }
        /* Links */
        .header a { text-decoration: none; color: #4f46e5; font-size: 0.875rem; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 管理后台</h1>
        <div class="header-right">
            <a href="/orders" target="_blank">用户端 →</a>
            <button class="btn-logout" onclick="location.href='/admin/logout'">退出登录</button>
        </div>
    </div>

    <div class="main">
        <!-- Date range picker -->
        <div class="toolbar">
            <label>时间范围：</label>
            <input type="date" id="date-start">
            <span class="date-sep">至</span>
            <input type="date" id="date-end">
            <button class="btn-query" onclick="loadOrders()">查询</button>
            <button class="btn-preset" onclick="setPreset('today')">今天</button>
            <button class="btn-preset" onclick="setPreset('yesterday')">昨天</button>
            <button class="btn-preset" onclick="setPreset('7days')">近7天</button>
            <button class="btn-preset" onclick="setPreset('30days')">近30天</button>
            <button class="btn-preset" onclick="setPreset('thisMonth')">本月</button>
            <span style="font-size:0.8rem;color:#94a3b8;margin-left:auto;">
                点击订单行展开/折叠详情
            </span>
        </div>

        <div class="error-banner" id="error-banner" style="display:none;"></div>

        <!-- Summary cards -->
        <div class="summary" id="summary" style="display:none;">
            <div class="summary-card">
                <div class="label">订单总数</div>
                <div class="value" id="stat-total">0</div>
            </div>
            <div class="summary-card">
                <div class="label">已支付</div>
                <div class="value" id="stat-paid" style="color:#16a34a;">0</div>
            </div>
            <div class="summary-card">
                <div class="label">待支付</div>
                <div class="value pending" id="stat-pending">0</div>
            </div>
            <div class="summary-card">
                <div class="label">已过期</div>
                <div class="value" id="stat-expired" style="color:#64748b;">0</div>
            </div>
            <div class="summary-card">
                <div class="label">失败</div>
                <div class="value" id="stat-failed" style="color:#dc2626;">0</div>
            </div>
            <div class="summary-card">
                <div class="label">营收 (¥)</div>
                <div class="value revenue" id="stat-revenue">0.00</div>
            </div>
        </div>

        <!-- Loading -->
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <div>加载中</div>
        </div>

        <!-- Table -->
        <div class="table-wrapper" id="table-wrapper" style="display:none;">
            <div class="table-header">
                <h2>订单明细</h2>
                <span class="count-badge" id="count-badge">0 条</span>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>订单号</th>
                        <th>用户</th>
                        <th>来源</th>
                        <th>字数</th>
                        <th>金额</th>
                        <th>支付</th>
                        <th>状态</th>
                        <th>创建时间</th>
                    </tr>
                </thead>
                <tbody id="orders-tbody"></tbody>
            </table>
            <div class="pagination" id="pagination" style="display:none;">
                <button id="btn-prev" onclick="goPage(-1)">← 上一页</button>
                <span class="page-info" id="page-info">第 1 / 1 页</span>
                <button id="btn-next" onclick="goPage(1)">下一页 →</button>
            </div>
        </div>

        <!-- Empty -->
        <div class="table-wrapper" id="empty-state" style="display:none;">
            <div class="empty">
                <div class="empty-icon">📭</div>
                <p>该时间范围暂无订单</p>
            </div>
        </div>
    </div>

    <script>
        let currentPage = 1;
        let totalPages = 1;
        let expandedOrderId = null;

        const STATUS_BADGE = {
            paid: 'badge-paid', pending: 'badge-pending',
            expired: 'badge-expired', failed: 'badge-failed'
        };
        const STATUS_LABEL = {
            paid: '已支付', pending: '待支付', expired: '已过期', failed: '失败'
        };
        const ORDER_STATUS_BADGE = {
            completed: 'badge-completed', processing: 'badge-processing',
            pending: 'badge-pending', failed: 'badge-failed', expired: 'badge-expired'
        };
        const ORDER_STATUS_LABEL = {
            completed: '已完成', processing: '处理中', pending: '待处理',
            failed: '失败', expired: '已过期'
        };

        function fmtDate(d) {
            return d.toISOString().split('T')[0];
        }

        // Init: default to today
        const today = fmtDate(new Date());
        document.getElementById('date-start').value = today;
        document.getElementById('date-end').value = today;

        function setPreset(type) {
            const now = new Date();
            let start, end;
            switch (type) {
                case 'today':
                    start = end = fmtDate(now);
                    break;
                case 'yesterday':
                    const y = new Date(now); y.setDate(y.getDate() - 1);
                    start = end = fmtDate(y);
                    break;
                case '7days':
                    start = new Date(now); start.setDate(start.getDate() - 6);
                    start = fmtDate(start); end = fmtDate(now);
                    break;
                case '30days':
                    start = new Date(now); start.setDate(start.getDate() - 29);
                    start = fmtDate(start); end = fmtDate(now);
                    break;
                case 'thisMonth':
                    start = new Date(now.getFullYear(), now.getMonth(), 1);
                    start = fmtDate(start); end = fmtDate(now);
                    break;
            }
            document.getElementById('date-start').value = start;
            document.getElementById('date-end').value = end;
            // Highlight active preset
            document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            loadOrders();
        }

        function showError(msg) {
            const el = document.getElementById('error-banner');
            el.textContent = msg;
            el.style.display = 'block';
        }

        function hideError() {
            document.getElementById('error-banner').style.display = 'none';
        }

        async function loadOrders(page) {
            if (page !== undefined) currentPage = page;
            const start = document.getElementById('date-start').value;
            const end = document.getElementById('date-end').value;
            if (!start || !end) return;

            hideError();
            document.getElementById('loading').style.display = 'block';
            document.getElementById('table-wrapper').style.display = 'none';
            document.getElementById('summary').style.display = 'none';
            document.getElementById('empty-state').style.display = 'none';

            try {
                const resp = await fetch(
                    `/admin/api/orders?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&page=${currentPage}`
                );
                if (!resp.ok) {
                    const data = await resp.json();
                    throw new Error(data.error || '请求失败');
                }
                const data = await resp.json();

                // Summary
                document.getElementById('stat-total').textContent = data.summary.total_orders;
                document.getElementById('stat-paid').textContent = data.summary.paid_orders;
                document.getElementById('stat-pending').textContent = data.summary.pending_orders;
                document.getElementById('stat-expired').textContent = data.summary.expired_orders;
                document.getElementById('stat-failed').textContent = data.summary.failed_orders;
                document.getElementById('stat-revenue').textContent = data.summary.total_revenue.toFixed(2);
                document.getElementById('summary').style.display = 'grid';

                // Table
                if (data.orders.length === 0) {
                    document.getElementById('empty-state').style.display = 'block';
                } else {
                    document.getElementById('count-badge').textContent = data.summary.total_orders + ' 条';
                    document.getElementById('table-wrapper').style.display = 'block';
                    renderOrders(data.orders);
                    currentPage = data.page;
                    totalPages = data.total_pages;
                    updatePagination();
                }
            } catch (e) {
                showError(e.message);
            } finally {
                document.getElementById('loading').style.display = 'none';
            }
        }

        function renderOrders(orders) {
            const tbody = document.getElementById('orders-tbody');
            let html = '';

            for (const o of orders) {
                const ps = o.payment_status || 'pending';
                const ss = o.status || 'pending';
                html += `<tr class="row-order" onclick="toggleDetail('${escapeHtml(o.order_id)}')" id="row-${escapeHtml(o.order_id)}">
                    <td style="font-family:monospace;font-size:0.78rem;">${escapeHtml(o.order_id)}</td>
                    <td>${escapeHtml(o.user_email || '游客')}</td>
                    <td style="font-family:monospace;font-size:0.75rem;color:#64748b;">${escapeHtml(o.original_format || 'txt')}</td>
                    <td>${o.word_count || '-'}</td>
                    <td>¥${(o.price || 0).toFixed(2)}</td>
                    <td><span class="badge ${STATUS_BADGE[ps] || 'badge-pending'}">${STATUS_LABEL[ps] || ps}</span></td>
                    <td><span class="badge ${ORDER_STATUS_BADGE[ss] || 'badge-pending'}">${ORDER_STATUS_LABEL[ss] || ss}</span></td>
                    <td style="font-size:0.78rem;color:#64748b;">${formatTime(o.created_at)}</td>
                </tr>`;
                html += `<tr class="row-detail" id="detail-${escapeHtml(o.order_id)}" style="display:none;">
                    <td colspan="8">
                        <div class="detail-meta">
                            <span>文件: ${escapeHtml(o.original_filename || '-')}</span>
                            <span>模式: ${escapeHtml(o.mode || 'academic')}</span>
                            <span>原始评分: ${o.original_score != null ? o.original_score + '%' : '-'}</span>
                            <span>改写评分: ${o.rewritten_score != null ? o.rewritten_score + '%' : '-'}</span>
                            <span>支付时间: ${o.paid_at ? formatTime(o.paid_at) : '-'}</span>
                            <span>交易号: ${escapeHtml(o.alipay_trade_no || '-')}</span>
                        </div>
                        <div class="detail-grid" style="margin-top:16px;">
                            <div class="detail-box">
                                <h4>📄 原始文本</h4>
                                <div class="text-content">${escapeHtml(o.original_text || '')}</div>
                            </div>
                            <div class="detail-box">
                                <h4>✨ 改写结果</h4>
                                <div class="text-content">${escapeHtml(o.rewritten_text || '（暂无）')}</div>
                            </div>
                        </div>
                    </td>
                </tr>`;
            }
            tbody.innerHTML = html;
        }

        function toggleDetail(orderId) {
            const detailRow = document.getElementById('detail-' + orderId);
            if (!detailRow) return;

            if (expandedOrderId === orderId) {
                detailRow.style.display = 'none';
                expandedOrderId = null;
            } else {
                if (expandedOrderId) {
                    const prev = document.getElementById('detail-' + expandedOrderId);
                    if (prev) prev.style.display = 'none';
                }
                detailRow.style.display = 'table-row';
                expandedOrderId = orderId;
            }
        }

        function updatePagination() {
            document.getElementById('pagination').style.display = totalPages > 1 ? 'flex' : 'none';
            document.getElementById('page-info').textContent = `第 ${currentPage} / ${totalPages} 页`;
            document.getElementById('btn-prev').disabled = currentPage <= 1;
            document.getElementById('btn-next').disabled = currentPage >= totalPages;
        }

        function goPage(delta) {
            const newPage = currentPage + delta;
            if (newPage >= 1 && newPage <= totalPages) {
                loadOrders(newPage);
            }
        }

        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatTime(isoStr) {
            if (!isoStr) return '-';
            try {
                const d = new Date(isoStr);
                return d.toLocaleString('zh-CN', {
                    month: '2-digit', day: '2-digit',
                    hour: '2-digit', minute: '2-digit', second: '2-digit'
                });
            } catch (e) { return isoStr; }
        }

        // Load on page ready
        loadOrders();
    </script>
</body>
</html>"""


# ============================================================
#  Main
# ============================================================
if __name__ == '__main__':
    print(f"\n  🔐 Admin dashboard → http://127.0.0.1:{ADMIN_PORT}/admin")
    print(f"  📁 Database: {DB_PATH}")
    print(f"  🔑 Login:  http://127.0.0.1:{ADMIN_PORT}/admin/login\n")
    admin_app.run(host='0.0.0.0', port=ADMIN_PORT, debug=True)
