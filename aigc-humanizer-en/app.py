#!/usr/bin/env python3
"""
AI Humanizer - Web Application
Entry point. App creation is delegated to app.create_app().
"""

from app import create_app

app = create_app()

if __name__ == '__main__':
    print("=" * 50)
    print("AI Humanizer - Starting on http://127.0.0.1:5100")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5100)
