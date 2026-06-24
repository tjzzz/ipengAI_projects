"""
配置示例 — 部署时复制为 config.py 并填入真实值。
"""

import os

PROJ_ROOT = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = 'your-secret-key-here'

AI_DETECTOR_ADAPTER = 'rule_based'  # rule_based | sapling | originality
HUMANIZER_ADAPTER = 'rule_based'    # rule_based | api
PAYMENT_ADAPTER = 'mock'            # mock | alipay

SAPLING_API_KEY = ''
ORIGINALITY_API_KEY = ''

AI_TEXT_HUMANIZER_EMAIL = ''
AI_TEXT_HUMANIZER_PASSWORD = ''

PRICE_PER_1000_WORDS = 14.9
FREE_WORD_LIMIT = 500

ALLOWED_UPLOAD_MIMETYPES = {
    'text/plain', 'text/markdown', 'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

ADMIN_PASSWORD = 'admin123'

ALIPAY_APP_ID = ''
ALIPAY_PID = ''
ALIPAY_PRIVATE_KEY = ''
ALIPAY_PUBLIC_KEY = ''
ALIPAY_GATEWAY_URL = 'https://openapi.alipay.com/gateway.do'
ALIPAY_NOTIFY_URL = ''
ALIPAY_RETURN_URL = ''
