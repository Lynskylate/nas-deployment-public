from __future__ import annotations

import json
from typing import Any, Dict

from ..llm import DashScopeCompatibleClient, extract_json_block
from ..models import QualitativeAssessment
from ..utils import to_float


def run_qualitative_assessment(ticker: str, market: str, input_brief: Dict[str, Any]) -> QualitativeAssessment:
    system_prompt = (
        "你是静态价值型烟蒂股分析助手。"
        "只返回JSON，禁止额外输出。"
        "字段: business_model, cyclicality, pricing_power, moat, governance_score, governance_notes。"
    )
    user_prompt = json.dumps(
        {
            "ticker": ticker,
            "market": market,
            "input_brief": input_brief,
            "task": ["总结赚钱逻辑", "判断周期性", "判断提价权", "判断护城河", "给出治理评分和备注"],
        },
        ensure_ascii=False,
    )

    try:
        client = DashScopeCompatibleClient()
        content = client.chat_json(system_prompt, user_prompt)
        payload = extract_json_block(content)
        notes = payload.get("governance_notes", [])
        if not isinstance(notes, list):
            notes = [str(notes)]
        return QualitativeAssessment(
            business_model=str(payload.get("business_model", "")),
            cyclicality=str(payload.get("cyclicality", "")),
            pricing_power=str(payload.get("pricing_power", "")),
            moat=str(payload.get("moat", "")),
            governance_score=to_float(payload.get("governance_score")),
            governance_notes=[str(item) for item in notes],
        )
    except Exception as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        return QualitativeAssessment(
            business_model="LLM unavailable; requires manual review.",
            cyclicality="UNKNOWN",
            pricing_power="UNKNOWN",
            moat="UNKNOWN",
            governance_score=None,
            governance_notes=[
                f"DashScope unavailable ({reason}); governance qualitative blocks marked as WARNING-Data."
            ],
        )
