"""
Configuration constants for AI Humanizer.
"""

import os

# Project root path (parent of app/)
PROJ_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Pricing
PRICE_PER_1000_WORDS = 14.9  # ¥14.9 / 1000 words
FREE_WORD_LIMIT = 500  # Words requiring payment for rewrite (also max words for free analysis)

# Allowed upload content types
ALLOWED_UPLOAD_MIMETYPES = {
    'text/plain',                     # .txt
    'text/markdown',                  # .md
    'application/pdf',                # .pdf
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
}