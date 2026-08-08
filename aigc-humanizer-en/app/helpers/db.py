"""Database connection helpers and order-id generation."""

import uuid
from datetime import datetime
from flask import g


def generate_order_id():
    """Generate one consistent, human-readable order identifier."""
    date_str = datetime.now().strftime("%Y%m%d")
    random_str = uuid.uuid4().hex[:6].upper()
    return f"ORD-{date_str}-{random_str}"


def get_db():
    """Get a database connection scoped to the current request context."""
    if 'db_conn' not in g:
        from app.models import get_connection
        g.db_conn = get_connection()
    return g.db_conn


def close_db(exception=None):
    """Close the database connection at the end of each request."""
    conn = g.pop('db_conn', None)
    if conn is not None:
        conn.close()
