#!/usr/bin/env python3
"""
Data models for AI Humanizer.
SQLite database operations using sqlite3 module.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from config import PROJ_ROOT

DB_DIR = os.path.join(PROJ_ROOT, 'instance')
DB_PATH = os.path.join(DB_DIR, 'aigc_humanizer.db')


def get_connection():
    """Get a new SQLite database connection."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database and create all tables."""
    conn = get_connection()
    try:
        User.init_table(conn)
        Order.init_table(conn)
        ActivationCode.init_table(conn)
        BalanceTransaction.init_table(conn)
    finally:
        conn.close()


class User:
    """User model — class methods for database operations."""

    @classmethod
    def init_table(cls, conn):
        """Create the users table if it does not exist."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

        # Add columns to existing table (backward compatibility)
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'word_balance' not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN word_balance INTEGER DEFAULT 0")
        if 'last_login_at' not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
        conn.commit()

    @classmethod
    def create(cls, conn, email, password):
        """Create a new user. Password is hashed via werkzeug.security."""
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        created_at = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, created_at)
        )
        conn.commit()
        return cls.get_by_id(conn, cursor.lastrowid)

    @classmethod
    def get_by_email(cls, conn, email):
        """Look up a user by email. Returns dict or None."""
        cursor = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        return dict(row) if row else None

    @classmethod
    def get_by_id(cls, conn, user_id):
        """Look up a user by primary key. Returns dict or None."""
        cursor = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    @classmethod
    def verify_password(cls, conn, email, password):
        """Verify password for a given email. Returns user dict or None."""
        cursor = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if row and check_password_hash(row['password_hash'], password):
            return dict(row)
        return None

    # ========== Word balance methods ==========

    @classmethod
    def get_balance(cls, conn, user_id):
        """Get user's current word balance. Returns int."""
        row = conn.execute(
            "SELECT word_balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return row['word_balance'] if row else 0

    @classmethod
    def add_balance(cls, conn, user_id, words):
        """Add word balance to a user's account."""
        conn.execute(
            "UPDATE users SET word_balance = word_balance + ? WHERE id = ?",
            (words, user_id)
        )

    @classmethod
    def deduct_balance(cls, conn, user_id, words):
        """Deduct balance without committing; the caller owns the transaction."""
        cursor = conn.execute(
            "UPDATE users SET word_balance = word_balance - ? WHERE id = ? AND word_balance >= ?",
            (words, user_id, words)
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT word_balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return row['word_balance'] if row else 0


class Order:
    """Order model — class methods for database operations."""

    @classmethod
    def init_table(cls, conn):
        """Create the orders table if it does not exist. Add payment columns if missing."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                order_id TEXT UNIQUE NOT NULL,
                original_text TEXT NOT NULL,
                rewritten_text TEXT,
                original_format TEXT DEFAULT 'txt',
                original_filename TEXT,
                word_count INTEGER,
                price REAL,
                mode TEXT DEFAULT 'academic',
                original_score REAL,
                rewritten_score REAL,
                status TEXT DEFAULT 'pending',
                payment_status TEXT DEFAULT 'pending',
                alipay_trade_no TEXT,
                alipay_amount REAL,
                alipay_qr_code TEXT,
                paid_at TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()

        # Add payment columns to existing table (backward compatibility)
        cursor = conn.execute("PRAGMA table_info(orders)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'payment_status' not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN payment_status TEXT DEFAULT 'pending'")
        if 'alipay_trade_no' not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN alipay_trade_no TEXT")
        if 'alipay_amount' not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN alipay_amount REAL")
        if 'alipay_qr_code' not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN alipay_qr_code TEXT")
        if 'paid_at' not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN paid_at TEXT")
        if 'recharge_words' not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN recharge_words INTEGER DEFAULT 0")
        if 'balance_words_used' not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN balance_words_used INTEGER DEFAULT 0")
        if 'balance_after' not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN balance_after INTEGER")
        conn.commit()

    @classmethod
    def create(cls, conn, user_id, order_id, original_text, rewritten_text,
               original_format, original_filename, word_count, price, mode,
               original_score, rewritten_score):
        """Create a free rewrite order record (payment_status='free')."""
        created_at = datetime.now(timezone.utc).isoformat()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        conn.execute(
            """INSERT INTO orders
               (user_id, order_id, original_text, rewritten_text,
                original_format, original_filename, word_count, price, mode,
                original_score, rewritten_score, status, payment_status,
                created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', 'free', ?, ?)""",
            (user_id, order_id, original_text, rewritten_text,
             original_format, original_filename, word_count, price, mode,
             original_score, rewritten_score, created_at, expires_at)
        )
        conn.commit()

    @classmethod
    def create_balance_order(cls, conn, user_id, order_id, original_text, rewritten_text,
                              original_format, original_filename, word_count, price, mode,
                              original_score, rewritten_score):
        """Create a balance-deducted rewrite order record (payment_status='balance')."""
        created_at = datetime.now(timezone.utc).isoformat()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        conn.execute(
            """INSERT INTO orders
               (user_id, order_id, original_text, rewritten_text,
                original_format, original_filename, word_count, price, mode,
                original_score, rewritten_score, status, payment_status,
                balance_words_used, balance_after, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', 'balance', ?, ?, ?, ?)""",
            (user_id, order_id, original_text, rewritten_text,
             original_format, original_filename, word_count, price, mode,
             original_score, rewritten_score, word_count,
             User.get_balance(conn, user_id), created_at, expires_at)
        )
        conn.commit()

    @classmethod
    def count_free_rewrites_today(cls, conn, user_id):
        """统计今天已免费改写的次数（payment_status='free' 的订单）。"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM orders
               WHERE user_id = ? AND payment_status = 'free'
               AND created_at >= ?""",
            (user_id, today)
        ).fetchone()
        return row['cnt'] if row else 0

    @classmethod
    def get_by_user_id(cls, conn, user_id, page=1, per_page=10,
                       payment_status=None, history_only=False):
        """Get paginated orders for a user. Returns (orders_list, total_count)."""
        where = "user_id = ?"
        params = [user_id]
        if payment_status:
            where += " AND payment_status = ?"
            params.append(payment_status)
        if history_only:
            where += " AND status IN ('completed', 'processing', 'failed', 'awaiting_balance')"

        count_row = conn.execute(
            f"SELECT COUNT(*) as total FROM orders WHERE {where}", params
        ).fetchone()
        total = count_row['total'] if count_row else 0

        offset = (page - 1) * per_page
        cursor = conn.execute(
            f"SELECT * FROM orders WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]
        )
        orders = [dict(row) for row in cursor.fetchall()]
        return orders, total

    @classmethod
    def get_by_order_id(cls, conn, order_id):
        """Look up an order by order_id. Returns dict or None."""
        cursor = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    @classmethod
    def update_rewrite(cls, conn, order_id, rewritten_text, rewritten_score):
        """Update the rewritten text and score for an existing order."""
        conn.execute(
            "UPDATE orders SET rewritten_text = ?, rewritten_score = ? WHERE order_id = ?",
            (rewritten_text, rewritten_score, order_id)
        )
        conn.commit()

    # ========== Payment-related methods ==========

    @classmethod
    def create_payment_record(cls, conn, user_id, order_id, original_text,
                               original_format, original_filename, word_count,
                               price, mode, recharge_words, balance_words_used):
        """Create a pending auto-recharge order tied to a rewrite task."""
        created_at = datetime.now(timezone.utc).isoformat()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        conn.execute(
            """INSERT INTO orders
               (user_id, order_id, original_text, rewritten_text,
                original_format, original_filename, word_count, price, mode,
                original_score, rewritten_score, status, payment_status,
                alipay_amount, recharge_words, balance_words_used,
                created_at, expires_at)
               VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, NULL, 'pending', 'pending', ?, ?, ?, ?, ?)""",
            (user_id, order_id, original_text, original_format, original_filename,
             word_count, price, mode, price, recharge_words, balance_words_used,
             created_at, expires_at)
        )
        conn.commit()
        return cls.get_by_order_id(conn, order_id)

    @classmethod
    def save_qr_code(cls, conn, order_id, qr_code):
        """Save the Alipay QR code string for an order."""
        conn.execute(
            "UPDATE orders SET alipay_qr_code = ? WHERE order_id = ?",
            (qr_code, order_id)
        )
        conn.commit()

    @classmethod
    def mark_paid(cls, conn, order_id, alipay_trade_no, paid_at):
        """Mark order as paid after Alipay notification.

        The WHERE payment_status = 'pending' guard makes this idempotent:
        if two callers race (e.g. webhook + polling), the second UPDATE
        affects zero rows and is a safe no-op.
        """
        conn.execute(
            """UPDATE orders
               SET payment_status = 'paid',
                   alipay_trade_no = ?,
                   paid_at = ?,
                   status = 'processing'
               WHERE order_id = ? AND payment_status = 'pending'""",
            (alipay_trade_no, paid_at, order_id)
        )
        conn.commit()

    @classmethod
    def update_result(cls, conn, order_id, rewritten_text, rewritten_score, original_score=None):
        """Update order with rewrite result (called after humanization completes)."""
        if original_score is not None:
            conn.execute(
                """UPDATE orders 
                   SET rewritten_text = ?, 
                       rewritten_score = ?, 
                       original_score = ?,
                       status = 'completed'
                   WHERE order_id = ?""",
                (rewritten_text, rewritten_score, original_score, order_id)
            )
        else:
            conn.execute(
                """UPDATE orders 
                   SET rewritten_text = ?, 
                       rewritten_score = ?, 
                       status = 'completed'
                   WHERE order_id = ?""",
                (rewritten_text, rewritten_score, order_id)
            )
        conn.commit()

    @classmethod
    def mark_failed(cls, conn, order_id):
        """Mark order as failed when background rewrite encounters an error."""
        conn.execute(
            "UPDATE orders SET status = 'failed' WHERE order_id = ?",
            (order_id,)
        )
        conn.commit()

    @classmethod
    def expire_old_orders(cls, conn, max_age_minutes=10):
        """Mark orders as expired if payment pending for too long.
        10 分钟 = 与支付宝 timeout_express 和前端 QR 过期时间保持一致（P6）"""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat()
        conn.execute(
            """UPDATE orders 
               SET payment_status = 'expired', status = 'expired'
               WHERE payment_status = 'pending' AND created_at < ?""",
            (cutoff,)
        )
        conn.commit()


class ActivationCode:
    """Activation/recharge code model for Xianyu channel."""

    @classmethod
    def init_table(cls, conn):
        """Create the activation_codes table if it does not exist."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activation_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                word_quota INTEGER NOT NULL,
                status TEXT DEFAULT 'unused',
                created_at TEXT NOT NULL,
                redeemed_by INTEGER REFERENCES users(id),
                redeemed_at TEXT
            )
        """)
        conn.commit()

    @classmethod
    def generate(cls, conn, code, word_quota):
        """Insert a new unredeemed activation code. Returns the record dict."""
        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO activation_codes (code, word_quota, created_at) VALUES (?, ?, ?)",
            (code, word_quota, created_at)
        )
        conn.commit()
        cursor = conn.execute("SELECT * FROM activation_codes WHERE code = ?", (code,))
        return dict(cursor.fetchone())

    @classmethod
    def get_by_code(cls, conn, code):
        """Look up an activation code. Returns dict or None."""
        cursor = conn.execute("SELECT * FROM activation_codes WHERE code = ?", (code,))
        row = cursor.fetchone()
        return dict(row) if row else None

    @classmethod
    def redeem(cls, conn, code, user_id):
        """Redeem an activation code for a user. Returns (success, message)."""
        try:
            ac = cls.get_by_code(conn, code)
            if not ac:
                return False, "兑换码不存在"
            if ac['status'] != 'unused':
                return False, "该兑换码已被使用"
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "UPDATE activation_codes SET status = 'redeemed', redeemed_by = ?, redeemed_at = ? WHERE code = ? AND status = 'unused'",
                (user_id, now, code)
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False, "该兑换码已被使用"
            User.add_balance(conn, user_id, ac['word_quota'])
            balance_after = User.get_balance(conn, user_id)
            BalanceTransaction.create(
                conn, user_id, 'activation_recharge', ac['word_quota'], balance_after,
                reference_id=code, description='兑换码充值'
            )
            conn.commit()
            return True, f"兑换成功！已添加 {ac['word_quota']} 词到你的账户"
        except Exception:
            conn.rollback()
            raise

    @classmethod
    def list_all(cls, conn, limit=50, offset=0):
        """List all activation codes. Returns (list, total_count)."""
        count_row = conn.execute("SELECT COUNT(*) as total FROM activation_codes").fetchone()
        total = count_row['total'] if count_row else 0
        cursor = conn.execute(
            "SELECT * FROM activation_codes ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        return [dict(row) for row in cursor.fetchall()], total

    @classmethod
    def stats(cls, conn):
        """Get activation code stats. Returns dict."""
        total = conn.execute("SELECT COUNT(*) as c FROM activation_codes").fetchone()['c']
        used = conn.execute("SELECT COUNT(*) as c FROM activation_codes WHERE status = 'redeemed'").fetchone()['c']
        unused = conn.execute("SELECT COUNT(*) as c FROM activation_codes WHERE status = 'unused'").fetchone()['c']
        total_words = conn.execute(
            "SELECT COALESCE(SUM(word_quota), 0) as s FROM activation_codes WHERE status = 'redeemed'"
        ).fetchone()['s']
        return {
            'total': total, 'used': used, 'unused': unused, 'total_redeemed_words': total_words
        }


class BalanceTransaction:
    """Immutable word-balance ledger for recharge, consumption and refunds."""

    @classmethod
    def init_table(cls, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balance_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                transaction_type TEXT NOT NULL,
                words INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                order_id TEXT,
                reference_id TEXT,
                description TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_balance_transactions_user "
            "ON balance_transactions(user_id, created_at DESC)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_balance_transactions_order_type "
            "ON balance_transactions(order_id, transaction_type) WHERE order_id IS NOT NULL"
        )
        conn.commit()

    @classmethod
    def create(cls, conn, user_id, transaction_type, words, balance_after,
               order_id=None, reference_id=None, description=None):
        conn.execute(
            """INSERT INTO balance_transactions
               (user_id, transaction_type, words, balance_after, order_id,
                reference_id, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, transaction_type, words, balance_after, order_id,
             reference_id, description, datetime.now(timezone.utc).isoformat())
        )
