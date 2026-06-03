"""
Filesystem-based session storage — avoids Flask's 4KB cookie limit.
"""

import os
import logging
from datetime import datetime
from uuid import uuid4
import pickle as _pickle
from flask.sessions import SessionInterface, SessionMixin


class FileSystemSession(dict, SessionMixin):
    """Minimal server-side session stored on the filesystem."""

    def __init__(self, data=None, sid=None, new=False):
        super().__init__(data or {})
        self.sid = sid or uuid4().hex
        self.new = new
        self.modified = True


class FileSystemSessionInterface(SessionInterface):
    """Filesystem-based session interface using pickle serialization."""

    def __init__(self, session_dir):
        self.session_dir = session_dir
        os.makedirs(session_dir, exist_ok=True)

    def open_session(self, app, request):
        _cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        try:
            sid = request.cookies.get(_cookie_name)
        except Exception:
            sid = None
        if sid:
            path = os.path.join(self.session_dir, sid)
            if os.path.exists(path):
                try:
                    with open(path, 'rb') as f:
                        data = _pickle.load(f)
                    return FileSystemSession(data=data, sid=sid)
                except Exception:
                    logging.warning("Failed to load session file for sid=%s, creating new session", sid)
        return FileSystemSession(new=True)

    def save_session(self, app, session, response):
        _cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        if not session or not hasattr(session, 'sid'):
            response.delete_cookie(_cookie_name)
            return

        # If session is empty (cleared), delete the file and cookie
        if not dict(session):
            path = os.path.join(self.session_dir, session.sid)
            if os.path.exists(path):
                os.remove(path)
            response.delete_cookie(_cookie_name)
            return

        path = os.path.join(self.session_dir, session.sid)
        with open(path, 'wb') as f:
            _pickle.dump(dict(session), f)

        # Convert Flask's get_expiration_time to int seconds for Werkzeug >=3.0
        expiry = self.get_expiration_time(app, session)
        max_age = None
        if expiry is not None and not isinstance(expiry, datetime):
            max_age = int(expiry.total_seconds())

        response.set_cookie(
            _cookie_name, session.sid,
            max_age=max_age,
            httponly=self.get_cookie_httponly(app),
            domain=self.get_cookie_domain(app),
            path=self.get_cookie_path(app),
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
        )