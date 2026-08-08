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
from app.ai_checker_api import analyze_text as _api_detect


def _make_api_detect(backend: str):
    """
    API 检测 + 规则子评分 = 混合模式。
    主分用 API，子分（perplexity / 句式 / 可读性等）仍用规则。
    """
    def _detect(text: str) -> dict:
        import logging
        _logger = logging.getLogger("detector_adapter")
        api = _api_detect(text, backend=backend)
        if "error" in api:
            _logger.warning(
                "API %s failed (%s), falling back to rule_based for %d chars",
                backend, api.get("error", "unknown"), len(text)
            )
            return _rule_detect(text)          # API 失败时降级到规则
        _logger.info("API %s OK, ai_score=%.1f", backend, api.get("ai_score", 0))
        rule = _rule_detect(text)
        rule["ai_score"] = api["ai_score"]
        rule["risk_level"] = api["risk_level"]
        rule["risk_description"] = api["risk_description"]
        rule["backend"] = backend
        return rule
    return _detect


def create_detector(adapter_name: str = "rule_based"):
    """
    返回一个 analyze_text 可调用对象（仅整篇 AI 率检测）。

    adapter_name 取值：
      rule_based  → 本地规则检测
      sapling     → Sapling.ai
      originality → Originality.ai
    """
    if adapter_name == "rule_based":
        return _rule_detect
    elif adapter_name in ("sapling", "originality"):
        return _make_api_detect(adapter_name)
    raise ValueError(f"Unknown AI_DETECTOR_ADAPTER: {adapter_name}")