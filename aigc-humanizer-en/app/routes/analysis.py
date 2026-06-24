"""
Analysis routes — text analysis, suggestion details, and preview rewrite.
"""

import uuid
import os
import logging
from flask import Blueprint, request, jsonify, session
from app.extensions import limiter
from app.helpers import get_db, login_required, derive_risk_level, \
    generate_modification_suggestions, extract_text
from config import ALLOWED_UPLOAD_MIMETYPES, PRICE_PER_1000_WORDS, FREE_WORD_LIMIT

analysis_bp = Blueprint('analysis', __name__)


@analysis_bp.route('/api/analyze', methods=['POST'])
@limiter.limit("60 per minute")
def api_analyze():
    """
    Analyze text for AI content.
    Accepts: text (direct paste) OR file (upload)
    Returns: AI score, paragraph analysis, suggestions
    """
    text = None
    filename = None
    original_format = 'txt'
    original_filename = None
    from flask import current_app
    app = current_app

    # Check if file was uploaded
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            if file.content_type and file.content_type not in ALLOWED_UPLOAD_MIMETYPES:
                return jsonify({"error": "不支持的文件格式，仅支持 .docx、.pdf、.txt、.md"}), 400

            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ['.docx', '.pdf', '.txt', '.md']:
                return jsonify({"error": "仅支持 .docx、.pdf、.txt、.md 格式"}), 400

            original_filename = file.filename
            original_format = ext[1:]
            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            try:
                text = extract_text(filepath)
            except Exception:
                logging.exception(f"Failed to extract text from {filepath}")
                return jsonify({"error": "文件解析失败，请确认文件格式正确"}), 400
            finally:
                try:
                    os.remove(filepath)
                except OSError:
                    logging.warning(f"Failed to remove temp file: {filepath}")

    # Check if text was pasted
    if not text:
        data = request.get_json(silent=True) or {}
        text = data.get('text', '').strip()
        if not text:
            return jsonify({"error": "请上传文档或粘贴英文文本"}), 400

    text = text.strip()

    # Store original format info in session
    session['last_original_format'] = original_format
    session['last_original_filename'] = original_filename
    session['last_text'] = text

    if len(text) < 50:
        return jsonify({"error": "文本太短，请提供至少 50 个字符"}), 400

    word_count = len(text.split())

    # Calculate price: free for up to FREE_WORD_LIMIT words
    is_paid = word_count > FREE_WORD_LIMIT
    over_limit = word_count > FREE_WORD_LIMIT
    
    # Price is 0 for free words, otherwise calculate based on word count
    if word_count <= FREE_WORD_LIMIT:
        price = 0
    else:
        price = round(PRICE_PER_1000_WORDS * (word_count / 1000), 2)

    # Run AI detection (always run, even for over-limit texts)
    from app.extensions import ai_detector, ai_paragraph_detector
    try:
        full_analysis = ai_detector(text)
        paragraph_analysis = ai_paragraph_detector(text)
    except Exception:
        logging.exception("AI analysis failed")
        return jsonify({"error": "分析出错，请稍后重试"}), 500

    suggestions = generate_modification_suggestions(full_analysis, text)

    session['last_text'] = text

    return jsonify({
        "success": True,
        "analysis": {
            "overall": full_analysis,
            "paragraphs": paragraph_analysis,
            "suggestions": suggestions
        },
        "text": text,
        "text_preview": text[:500] + "..." if len(text) > 500 else text,
        "word_count": word_count,
        "price": round(price, 2),
        "is_paid": is_paid,
        "over_limit": over_limit,
        "max_free_words": FREE_WORD_LIMIT,
        "has_extracted_text": original_format != 'txt',
        "original_format": original_format,
        "original_filename": original_filename
    })


@analysis_bp.route('/api/suggestion-detail', methods=['POST'])
@limiter.limit("10 per minute")
def api_suggestion_detail():
    """Get detailed suggestions for a specific paragraph or section."""
    data = request.get_json(silent=True) or {}
    paragraph_text = data.get('text', '').strip()
    paragraph_index = data.get('paragraph_index', 0)

    if not paragraph_text or len(paragraph_text) < 50:
        return jsonify({"error": "段落文本太短"}), 400

    from app.extensions import ai_detector as run_analysis
    try:
        analysis = run_analysis(paragraph_text)
        suggestions = generate_modification_suggestions(analysis, paragraph_text)
    except Exception:
        logging.exception("AI analysis failed")
        return jsonify({"error": "分析出错，请稍后重试"}), 500

    return jsonify({
        "success": True,
        "analysis": analysis,
        "suggestions": suggestions,
        "paragraph_index": paragraph_index
    })


@analysis_bp.route('/api/extracted-text', methods=['GET'])
@login_required
def api_extracted_text():
    """Get the last analyzed text from session (on-demand, avoids leaking in analyze response)."""
    text = session.get('last_text', '')
    if not text:
        return jsonify({"error": "没有找到已分析的文本"}), 404
    return jsonify({"text": text})


@analysis_bp.route('/api/preview-rewrite', methods=['POST'])
def api_preview_rewrite():
    """Preview what the rewritten text would look like (free preview, limited)."""
    from app.extensions import humanizer_adapter
    from app.extensions import ai_detector as run_analysis

    data = request.get_json(silent=True) or {}
    text = data.get('text', '')

    if not text:
        return jsonify({"error": "没有可预览改写的文本"}), 400

    word_count = len(text.split())

    # Only preview first paragraph if too long
    if word_count > 200:
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if paragraphs:
            text = paragraphs[0]
        else:
            text = ' '.join(text.split()[:200])

    try:
        humanized = humanizer_adapter.humanize(text, mode='academic')
        original_analysis = run_analysis(text)
        rewritten_analysis = run_analysis(humanized)

        return jsonify({
            "success": True,
            "original_excerpt": text,
            "rewritten_excerpt": humanized,
            "original_score": round(original_analysis['ai_score'], 1),
            "rewritten_score": round(rewritten_analysis['ai_score'], 1),
            "note": "此为免费预览，仅展示部分内容。支付后可改写全文。"
        })
    except Exception:
        logging.exception("Preview rewrite failed")
        return jsonify({"error": "预览出错，请稍后重试"}), 500