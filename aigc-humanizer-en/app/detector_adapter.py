"""
AI Detector Adapter — 根据配置返回对应的 analyze_text 函数。

用法：在 create_app() 中调用 create_detector(name)，
然后把返回的函数注册到 app.extensions.ai_detector。

适配的 adapter_name：
  - "rule_based"  → 本地规则 (ai_checker.py)
  - "sapling"     → Sapling.ai API
  - "originality"  → Originality.ai API
"""

from app.ai_checker import analyze_text as _rule_detect
from app.ai_checker import analyze_by_paragraphs as _rule_paragraphs
from app.ai_checker_api import analyze_text as _api_detect


def _make_paragraph_analyzer(detect_fn):
    """用给定的 detect_fn 生成 analyze_by_paragraphs。"""
    def _para(text: str):
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        results = []
        for i, para in enumerate(paragraphs, 1):
            if len(para) >= 100:
                analysis = detect_fn(para)
                results.append({
                    "paragraph": i,
                    "preview": para[:100] + "..." if len(para) > 100 else para,
                    "ai_score": analysis.get("ai_score", 0),
                    "risk_level": analysis.get("risk_level", "Unknown"),
                })
        return results
    return _para


def _make_api_detect(backend: str):
    """
    API 检测 + 规则子评分 = 混合模式。
    主分用 API，子分（perplexity / 句式 / 可读性等）仍用规则，
    这样 generate_modification_suggestions() 不受影响。
    """
    def _detect(text: str) -> dict:
        api = _api_detect(text, backend=backend)
        if "error" in api:
            return _rule_detect(text)          # API 失败时降级到规则
        rule = _rule_detect(text)
        rule["ai_score"] = api["ai_score"]
        rule["risk_level"] = api["risk_level"]
        rule["risk_description"] = api["risk_description"]
        rule["backend"] = backend
        return rule
    return _detect


def create_detector(adapter_name: str = "rule_based"):
    """
    返回 (analyze_text, analyze_by_paragraphs) 两个可调用对象。

    adapter_name 取值：
      rule_based  → 本地规则检测
      sapling     → Sapling.ai
      originality → Originality.ai
    """
    if adapter_name == "rule_based":
        return _rule_detect, _rule_paragraphs
    elif adapter_name in ("sapling", "originality"):
        fn = _make_api_detect(adapter_name)
        return fn, _make_paragraph_analyzer(fn)
    raise ValueError(f"Unknown AI_DETECTOR_ADAPTER: {adapter_name}")