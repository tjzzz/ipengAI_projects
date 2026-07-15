"""
Filesystem-based session storage — avoids Flask's 4KB cookie limit.
"""

import os
import logging
import re
import tempfile
from datetime import datetime
from uuid import uuid4
import pickle as _pickle
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict


class FileSystemSession(CallbackDict, SessionMixin):
    """Minimal server-side session stored on the filesystem."""

    def __init__(self, data=None, sid=None, new=False):
        def on_update(session):
            session.modified = True

        super().__init__(data or {}, on_update)
        self.sid = sid or uuid4().hex
        self.new = new
        self.modified = False


class FileSystemSessionInterface(SessionInterface):
    """Filesystem-based session interface using pickle serialization."""

    def __init__(self, session_dir):
        self.session_dir = session_dir
        os.makedirs(session_dir, exist_ok=True)

    @staticmethod
    def _valid_sid(sid):
        return bool(sid and re.fullmatch(r'[0-9a-f]{32}', sid))

    def _session_path(self, sid):
        return os.path.join(self.session_dir, sid)

    def open_session(self, app, request):
        _cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        try:
            sid = request.cookies.get(_cookie_name)
        except Exception:
            sid = None
        if self._valid_sid(sid):
            path = self._session_path(sid)
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
            sid = getattr(session, 'sid', None)
            if self._valid_sid(sid):
                try:
                    os.unlink(self._session_path(sid))
                except FileNotFoundError:
                    pass
            response.delete_cookie(_cookie_name)
            return

        # Read-only requests must not rewrite the same session file. Rewriting
        # every request made concurrent /api/me and /api/user/balance calls
        # race with each other and occasionally exposed a partially-written
        # pickle, which looked like a random logout.
        if session.modified or session.new:
            path = self._session_path(session.sid)
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode='wb', dir=self.session_dir, delete=False
                ) as tmp:
                    tmp_path = tmp.name
                    _pickle.dump(dict(session), tmp)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(tmp_path, path)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        # Convert Flask's get_expiration_time to int seconds for Werkzeug >=3.0
        expiry = self.get_expiration_time(app, session)
        max_age = None
        if expiry is not None and not isinstance(expiry, datetime):
            max_age = int(expiry.total_seconds())

        if self.should_set_cookie(app, session):
            response.set_cookie(
                _cookie_name, session.sid,
                expires=expiry,
                max_age=max_age,
                httponly=self.get_cookie_httponly(app),
                domain=self.get_cookie_domain(app),
                path=self.get_cookie_path(app),
                secure=self.get_cookie_secure(app),
                samesite=self.get_cookie_samesite(app),
            )
