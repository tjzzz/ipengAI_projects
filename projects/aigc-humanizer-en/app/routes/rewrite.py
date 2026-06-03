"""
Rewrite routes — execute text humanization and save order record.
"""

import uuid
import logging
from flask import Blueprint, request, jsonify, session
from app.extensions import limiter
from app.helpers import get_db, login_required
from app.config import PRICE_PER_1000_WORDS

rewrite_bp = Blueprint('rewrite', __name__)


@rewrite_bp.route('/api/rewrite', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def api_rewrite():
    """
    Rewrite text to reduce AI detection score.
    Executes the humanization immediately and saves the order record.
    Requires login.
    """
    from app.extensions import humanizer_adapter as humanizer
    from app.ai_checker import analyze_text as run_analysis
    from app.models import Order

    data = request.get_json(silent=True) or {}
    text = data.get('text') or session.get('last_text', '')
    mode = data.get('mode', 'academic')

    if not text:
        return jsonify({"error": "没有可改写的文本，请先分析"}), 400

    word_count = len(text.split())
    price = max(PRICE_PER_1000_WORDS * (word_count / 1000), PRICE_PER_1000_WORDS)
    price = round(price, 2)

    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

    try:
        humanized = humanizer.humanize(text, mode=mode)

        original_analysis = run_analysis(text)
        rewritten_analysis = run_analysis(humanized)

        # Build paragraph comparison for frontend display
        original_paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        rewritten_paragraphs = [p.strip() for p in humanized.split('\n\n') if p.strip()]

        paragraph_comparison = []
        for i, (orig_p, new_p) in enumerate(zip(original_paragraphs, rewritten_paragraphs)):
            if len(orig_p) >= 100 and len(new_p) >= 100:
                paragraph_comparison.append({
                    "index": i,
                    "original_preview": orig_p[:150] + "..." if len(orig_p) > 150 else orig_p,
                    "rewritten_preview": new_p[:150] + "..." if len(new_p) > 150 else new_p,
                    "original_score": round(original_analysis['ai_score'], 1),
                    "rewritten_score": round(rewritten_analysis['ai_score'], 1),
                    "reduction": round(original_analysis['ai_score'] - rewritten_analysis['ai_score'], 1)
                })

        # Save order record
        user_id = session.get('user_id')
        original_format = session.get('last_original_format', 'txt')
        original_filename = session.get('last_original_filename', None)
        try:
            conn = get_db()
            Order.create(
                conn,
                user_id=user_id,
                order_id=order_id,
                original_text=text,
                rewritten_text=humanized,
                original_format=original_format,
                original_filename=original_filename,
                word_count=word_count,
                price=price,
                mode=mode,
                original_score=original_analysis.get('ai_score', 0),
                rewritten_score=rewritten_analysis.get('ai_score', 0)
            )
        except Exception:
            logging.exception("Failed to save order record, but rewrite result was returned")

        # Store in session for unauthenticated download fallback
        session['last_rewritten'] = {
            'original': text,
            'rewritten': humanized,
            'original_score': original_analysis.get('ai_score', 0),
            'rewritten_score': rewritten_analysis.get('ai_score', 0),
            'order_id': order_id
        }

        return jsonify({
            "success": True,
            "order_id": order_id,
            "original": {
                "text": text,
                "ai_score": round(original_analysis['ai_score'], 1),
                "risk_level": original_analysis['risk_level']
            },
            "rewritten": {
                "text": humanized,
                "ai_score": round(rewritten_analysis['ai_score'], 1),
                "risk_level": rewritten_analysis['risk_level']
            },
            "improvement": round(original_analysis['ai_score'] - rewritten_analysis['ai_score'], 1),
            "paragraph_comparison": paragraph_comparison,
            "original_format": original_format,
            "original_filename": original_filename
        })

    except Exception:
        logging.exception("Rewrite failed")
        return jsonify({"error": "改写出错，请稍后重试"}), 500
