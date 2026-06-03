"""
Configuration constants for AI Humanizer.
"""

# Pricing
PRICE_PER_1000_WORDS = 14.9  # ¥14.9 / 1000 words
FREE_WORD_LIMIT = 500  # Words requiring payment for rewrite
MAX_FREE_ANALYSIS_WORDS = 500  # Max words for free analysis

# Allowed upload content types
ALLOWED_UPLOAD_MIMETYPES = {
    'text/plain',                     # .txt
    'text/markdown',                  # .md
    'application/pdf',                # .pdf
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
}