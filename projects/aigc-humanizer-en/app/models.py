#!/usr/bin/env python3
"""
Data models for AI Humanizer.
SQLite database operations using sqlite3 module.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash

DB_DIR = os.path.join(os.path.dirname(__file__), 'instance')
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
        conn.commit()

    @classmethod
    def create(cls, conn, user_id, order_id, original_text, rewritten_text,
               original_format, original_filename, word_count, price, mode,
               original_score, rewritten_score):
        """Create a new order record."""
        created_at = datetime.now(timezone.utc).isoformat()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        conn.execute(
            """INSERT INTO orders
               (user_id, order_id, original_text, rewritten_text,
                original_format, original_filename, word_count, price, mode,
                original_score, rewritten_score, status, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
            (user_id, order_id, original_text, rewritten_text,
             original_format, original_filename, word_count, price, mode,
             original_score, rewritten_score, created_at, expires_at)
        )
        conn.commit()

    @classmethod
    def get_by_user_id(cls, conn, user_id, page=1, per_page=10):
        """Get paginated orders for a user. Returns (orders_list, total_count)."""
        # Get total count
        count_row = conn.execute(
            "SELECT COUNT(*) as total FROM orders WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        total = count_row['total'] if count_row else 0

        # Get page
        offset = (page - 1) * per_page
        cursor = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, per_page, offset)
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
                               original_format, original_filename, word_count, price, mode):
        """Create a pending payment order (status='pending', payment_status='pending')."""
        created_at = datetime.now(timezone.utc).isoformat()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        conn.execute(
            """INSERT INTO orders
               (user_id, order_id, original_text, rewritten_text,
                original_format, original_filename, word_count, price, mode,
                original_score, rewritten_score, status, payment_status,
                alipay_amount, created_at, expires_at)
               VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, NULL, 'pending', 'pending', ?, ?, ?)""",
            (user_id, order_id, original_text, original_format, original_filename,
             word_count, price, mode, price, created_at, expires_at)
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
        """Mark order as paid after Alipay notification."""
        conn.execute(
            """UPDATE orders 
               SET payment_status = 'paid', 
                   alipay_trade_no = ?, 
                   paid_at = ?, 
                   status = 'processing'
               WHERE order_id = ?""",
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
            "UPDATE orders SET status = 'failed', payment_status = 'failed' WHERE order_id = ?",
            (order_id,)
        )
        conn.commit()

    @classmethod
    def get_payment_status(cls, conn, order_id):
        """Get payment and processing status for an order."""
        cursor = conn.execute(
            "SELECT order_id, payment_status, status, paid_at, price, alipay_trade_no FROM orders WHERE order_id = ?",
            (order_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @classmethod
    def expire_old_orders(cls, conn, max_age_minutes=30):
        """Mark orders as expired if payment pending for too long."""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat()
        conn.execute(
            """UPDATE orders 
               SET payment_status = 'expired', status = 'expired'
               WHERE payment_status = 'pending' AND created_at < ?""",
            (cutoff,)
        )
        conn.commit()
