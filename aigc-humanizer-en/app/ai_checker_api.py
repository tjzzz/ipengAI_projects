#!/usr/bin/env python3
"""
直接调用外部 API 检测英文 AI 率。

支持的接口：
  - sapling:     Sapling.ai (免费50次/月, 之后 $25/月起)
                 https://sapling.ai/docs/api/detector/
  - originality: Originality.ai (付费 $14.95/月)
                 https://originality.ai/

用法：
    from ai_checker_api import analyze_text
    result = analyze_text("text", backend="sapling")

环境变量：
    SAPLING_API_KEY
    ORIGINALITY_API_KEY

日志：每次调用结果自动保存到 logs/ai_detector/ 目录
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

from config import SAPLING_API_KEY as _CFG_SAPLING_KEY, ORIGINALITY_API_KEY as _CFG_ORIGINALITY_KEY, PROJ_ROOT

# 日志目录
_LOG_DIR = os.path.join(PROJ_ROOT, "logs", "ai_detector")


# ---------- 结果落盘 ----------

def _save(text: str, result: dict):
    """把检测结果写到日志文件。"""
    ts = datetime.now(timezone.utc)
    # 用文本前 40 字符的 hash 做摘要，方便去重
    sig = hashlib.md5(text.encode()[:200]).hexdigest()[:8]
    filename = f"{result.get('backend', 'unknown')}_{ts.strftime('%Y%m%d_%H%M%S')}_{sig}.json"
    os.makedirs(_LOG_DIR, exist_ok=True)
    path = os.path.join(_LOG_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts.isoformat(),
            "word_count": len(text.split()),
            "char_count": len(text),
            "text_preview": text[:300],
            "result": result,
        }, f, indent=2, ensure_ascii=False)
    return path


# ---------- 评分转风险等级 ----------

def _risk_level(score: float) -> tuple:
    if score < 20:
        return "Safe", "No action needed. Your text is unlikely to be flagged."
    elif score < 40:
        return "Warning", "Consider reviewing. Some sections may trigger flags."
    elif score < 60:
        return "Moderate Risk", "Humanization recommended to reduce detection risk."
    else:
        return "High Risk", "Strong humanization recommended before submission."


# ---------- Sapling.ai ----------

def _sapling(text: str, api_key: str) -> dict:
    resp = requests.post(
        "https://api.sapling.ai/api/v1/aidetect",
        json={"key": api_key, "text": text, "session_id": f"humanizer-{int(time.time())}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    score = data.get("score", 0.5) * 100  # 0-1 → 0-100

    # 逐句评分
    sentences = []
    for s in data.get("sentence_scores", []):
        sentences.append({
            "text": s.get("sentence", ""),
            "score": round(s.get("score", 0.5) * 100, 1),
        })

    level, desc = _risk_level(score)
    result = {
        "ai_score": round(score, 1),
        "risk_level": level,
        "risk_description": desc,
        "backend": "sapling",
        "details": {
            "sentence_count": len(sentences),
            "avg_sentence_score": round(
                sum(s["score"] for s in sentences) / len(sentences), 1
            ) if sentences else 0,
            "sentence_scores": sentences,
            "raw_score": data.get("score"),      # 原始 0-1 分
        },
    }
    _save(text, result)
    return result


# ---------- Originality.ai ----------

def _originality(text: str, api_key: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
    }
    resp = requests.post(
        "https://api.originality.ai/v1/scan",
        json={"content": text, "aiModelVersion": "latest"},
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    raw = data.get("aiScore", 50)
    if isinstance(raw, float) and raw <= 1.0:
        raw *= 100

    level, desc = _risk_level(float(raw))
    result = {
        "ai_score": round(float(raw), 1),
        "risk_level": level,
        "risk_description": desc,
        "backend": "originality",
        "details": {
            "credits_used": data.get("creditsUsed", 0),
            "scan_id": data.get("scanId", ""),
            "raw_response": data,
        },
    }
    _save(text, result)
    return result


# ---------- 统一入口 ----------

KEY_MAP = {
    "sapling": _CFG_SAPLING_KEY,
    "originality": _CFG_ORIGINALITY_KEY,
}

BACKENDS = {
    "sapling": _sapling,
    "originality": _originality,
}


def analyze_text(text: str, backend: str = "sapling", api_key: str = "") -> dict:
    """
    分析英文文本的 AI 生成概率。结果自动保存到 logs/ai_detector/。

    Parameters
    ----------
    text : str
        待检测文本（建议 ≥50 字符）。
    backend : str
        "sapling"（默认）或 "originality"。
    api_key : str
        留空则从 config.py 读取。

    Returns
    -------
    dict
        含 ai_score / risk_level / risk_description / backend / details。
        出错时含 error 字段，ai_score=50，也会落盘。
    """
    if not text or len(text.strip()) < 50:
        return {
            "error": "Text too short (minimum 50 characters)",
            "ai_score": 0,
            "risk_level": "Unknown",
            "backend": backend,
        }

    if backend not in BACKENDS:
        return {
            "error": f"Unknown backend '{backend}'",
            "ai_score": 0,
            "risk_level": "Unknown",
            "backend": backend,
        }

    key = api_key or KEY_MAP.get(backend, "")
    if not key:
        return {
            "error": f"Missing API key for {backend}. Set it in config.py.",
            "ai_score": 50,
            "risk_level": "Unknown",
            "backend": backend,
        }

    try:
        return handler(text, key)
    except requests.Timeout:
        err = {"error": f"Timeout from {backend}", "ai_score": 50, "risk_level": "Unknown", "backend": backend}
        _save(text, err)
        return err
    except requests.HTTPError as e:
        err = {"error": f"HTTP {e.response.status_code} from {backend}", "ai_score": 50, "risk_level": "Unknown", "backend": backend}
        _save(text, err)
        return err
    except Exception as e:
        err = {"error": f"{backend}: {e}", "ai_score": 50, "risk_level": "Unknown", "backend": backend}
        _save(text, err)
        return err


# ---------- CLI ----------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="AI content detector via API")
    p.add_argument("--text", "-t", help="Text to analyze")
    p.add_argument("--file", "-f", help="Read text from file")
    p.add_argument("--backend", "-b", default="sapling", choices=list(BACKENDS))
    p.add_argument("--api-key", help="Override API key")
    p.add_argument("--no-save", action="store_true", help="不落盘（默认自动保存）")
    args = p.parse_args()

    if args.file:
        with open(args.file) as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        p.print_help()
        sys.exit(1)

    result = analyze_text(text, backend=args.backend, api_key=args.api_key)
    print(json.dumps(result, indent=2, ensure_ascii=False))