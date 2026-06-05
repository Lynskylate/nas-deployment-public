from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import (
    Decision,
    FactCheckItem,
    FactCheckResult,
    FinancialPeriod,
    OwnershipProfile,
    PillarMetrics,
    WarningClass,
)
from ..utils import to_float


def warning_data(num: int, title: str, detail: str) -> FactCheckItem:
    return FactCheckItem(num, title, Decision.WARNING, detail, WarningClass.DATA)


def warning_risk(num: int, title: str, detail: str) -> FactCheckItem:
    return FactCheckItem(num, title, Decision.WARNING, detail, WarningClass.RISK)


def pass_item(num: int, title: str, detail: str) -> FactCheckItem:
    return FactCheckItem(num, title, Decision.PASS, detail)


def veto_item(num: int, title: str, detail: str) -> FactCheckItem:
    return FactCheckItem(num, title, Decision.VETO, detail)


def bool_value(payload: Dict[str, Any], key: str) -> Optional[bool]:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def rating_from_counts(warning_risk: int, veto_count: int) -> str:
    if veto_count > 0:
        return "D"
    if warning_risk == 0:
        return "A"
    if warning_risk <= 3:
        return "B"
    return "C"


def apply_bonus(base_rating: str, bonus_points: int) -> str:
    if base_rating == "D":
        return "D"
    if base_rating == "B" and bonus_points >= 2:
        return "B+"
    if base_rating == "C" and bonus_points >= 3:
        return "B"
    return base_rating


def run_fact_check(latest_period: FinancialPeriod, pillar: PillarMetrics, ownership: OwnershipProfile, supplemental: Dict[str, Any]) -> FactCheckResult:
    items: List[FactCheckItem] = []

    cash_pool = pillar.cash_pool
    restricted_cash = latest_period.metric("restricted_cash")
    if cash_pool in (None, 0) or restricted_cash is None:
        items.append(warning_data(1, "受限现金占比", "缺少受限现金或现金池数据"))
    else:
        ratio = restricted_cash / cash_pool
        if ratio > 0.20:
            items.append(veto_item(1, "受限现金占比", f"受限现金占比{ratio:.1%} > 20%"))
        elif ratio > 0.05:
            items.append(warning_risk(1, "受限现金占比", f"受限现金占比{ratio:.1%}，需剔除后重算"))
        else:
            items.append(pass_item(1, "受限现金占比", f"受限现金占比{ratio:.1%}"))

    pledged_assets_ratio = to_float(supplemental.get("pledged_assets_ratio"))
    if pledged_assets_ratio is None:
        items.append(warning_data(2, "质押资产", "缺少质押资产占比"))
    elif pledged_assets_ratio > 0.30:
        items.append(veto_item(2, "质押资产", f"核心资产质押占比{pledged_assets_ratio:.1%}"))
    elif pledged_assets_ratio > 0.10:
        items.append(warning_risk(2, "质押资产", f"质押资产占比较高：{pledged_assets_ratio:.1%}"))
    else:
        items.append(pass_item(2, "质押资产", "未见显著质押风险"))

    goodwill = latest_period.metric("goodwill")
    total_assets = latest_period.metric("total_assets")
    if goodwill is None or total_assets in (None, 0):
        items.append(warning_data(3, "商誉占比", "缺少商誉或总资产数据"))
    else:
        ratio = goodwill / total_assets
        if ratio > 0.30:
            items.append(veto_item(3, "商誉占比", f"商誉占总资产{ratio:.1%} > 30%"))
        elif ratio > 0.15:
            items.append(warning_risk(3, "商誉占比", f"商誉占比{ratio:.1%}处于预警区间"))
        else:
            items.append(pass_item(3, "商誉占比", f"商誉占比{ratio:.1%}"))

    goodwill_impairment = bool_value(supplemental, "goodwill_impairment_major")
    if goodwill_impairment is None:
        items.append(warning_data(4, "商誉减值历史", "缺少10年减值历史"))
    elif goodwill_impairment:
        items.append(warning_risk(4, "商誉减值历史", "历史存在重大商誉减值"))
    else:
        items.append(pass_item(4, "商誉减值历史", "未发现重大历史减值"))

    ar_90d = to_float(supplemental.get("ar_90d_ratio"))
    related_ar = to_float(supplemental.get("related_party_ar_ratio"))
    if ar_90d is None and related_ar is None:
        items.append(warning_data(5, "应收账款质量", "缺少账龄或关联方应收数据"))
    elif (ar_90d is not None and ar_90d > 0.30) or (related_ar is not None and related_ar > 0.20):
        items.append(warning_risk(5, "应收账款质量", "应收质量风险超阈值"))
    else:
        items.append(pass_item(5, "应收账款质量", "应收账龄与集中度可接受"))

    dio_up = bool_value(supplemental, "dio_three_year_up")
    dio_gap = to_float(supplemental.get("dio_vs_industry_gap"))
    if dio_up is None or dio_gap is None:
        items.append(warning_data(6, "存货周转", "缺少DIO趋势或行业偏离数据"))
    elif dio_up and dio_gap > 0.50:
        items.append(warning_risk(6, "存货周转", "DIO连续上升且偏离行业>50%"))
    else:
        items.append(pass_item(6, "存货周转", "DIO趋势可接受"))

    intangible = latest_period.metric("intangible_assets")
    equity = latest_period.metric("equity")
    if intangible is None or equity in (None, 0):
        items.append(warning_data(7, "无形资产合理性", "缺少无形资产或净资产数据"))
    else:
        ratio = intangible / abs(equity)
        if ratio > 0.40:
            items.append(veto_item(7, "无形资产合理性", f"无形资产/净资产={ratio:.1%} > 40%"))
        elif ratio > 0.25:
            items.append(warning_risk(7, "无形资产合理性", f"无形资产占比偏高：{ratio:.1%}"))
        else:
            items.append(pass_item(7, "无形资产合理性", f"无形资产占比{ratio:.1%}"))

    off_balance = to_float(supplemental.get("off_balance_liabilities_to_mcap"))
    if off_balance is None:
        items.append(warning_data(8, "表外负债", "缺少表外负债披露"))
    elif off_balance > 0.15:
        items.append(veto_item(8, "表外负债", f"表外负债/市值={off_balance:.1%} > 15%"))
    else:
        items.append(pass_item(8, "表外负债", f"表外负债/市值={off_balance:.1%}"))

    cap_commit = to_float(supplemental.get("cap_commit_to_net_cash"))
    if cap_commit is None:
        items.append(warning_data(9, "资本承诺", "缺少资本承诺数据"))
    elif cap_commit > 0.30:
        items.append(veto_item(9, "资本承诺", f"资本承诺/净现金={cap_commit:.1%} > 30%"))
    else:
        items.append(pass_item(9, "资本承诺", f"资本承诺/净现金={cap_commit:.1%}"))

    related_guarantee = bool_value(supplemental, "related_guarantee_major")
    if related_guarantee is None:
        items.append(warning_data(10, "担保/互保", "缺少对外担保披露"))
    elif related_guarantee:
        items.append(warning_risk(10, "担保/互保", "存在关联方大额担保"))
    else:
        items.append(pass_item(10, "担保/互保", "未发现关联方大额担保"))

    pension_gap = to_float(supplemental.get("pension_gap_to_mcap"))
    if pension_gap is None:
        items.append(warning_data(11, "养老金缺口", "缺少养老金义务数据"))
    elif pension_gap > 0.10:
        items.append(veto_item(11, "养老金缺口", f"养老金缺口/市值={pension_gap:.1%} > 10%"))
    else:
        items.append(pass_item(11, "养老金缺口", f"养老金缺口/市值={pension_gap:.1%}"))

    major_litigation = bool_value(supplemental, "major_litigation_unresolved")
    if major_litigation is None:
        items.append(warning_data(12, "环境/法律负债", "缺少重大诉讼状态"))
    elif major_litigation:
        items.append(veto_item(12, "环境/法律负债", "存在重大未决诉讼且金额不确定"))
    else:
        items.append(pass_item(12, "环境/法律负债", "未发现重大未决诉讼"))

    other_payables = to_float(supplemental.get("other_payables_ratio"))
    other_unexplained = bool_value(supplemental, "other_payables_unexplained")
    if other_payables is None or other_unexplained is None:
        items.append(warning_data(13, "其他应付款异常", "缺少其他应付款结构明细"))
    elif other_payables > 0.30 and other_unexplained:
        items.append(warning_risk(13, "其他应付款异常", "其他应付款占比高且来源不明"))
    else:
        items.append(pass_item(13, "其他应付款异常", "其他应付款结构可解释"))

    related_trade = to_float(supplemental.get("related_trade_revenue_ratio"))
    related_mispricing = bool_value(supplemental, "related_trade_mispricing")
    if related_trade is None and related_mispricing is None:
        items.append(warning_data(14, "关联交易", "缺少关联交易比例和定价信息"))
    elif (related_trade is not None and related_trade > 0.30) or related_mispricing:
        items.append(veto_item(14, "关联交易", "关联交易占比过高或定价异常"))
    else:
        items.append(pass_item(14, "关联交易", "关联交易水平可接受"))

    top5_customer = to_float(supplemental.get("top5_customer_ratio"))
    is_soe = ownership.controller_level is not None and "国企" in ownership.controller_level
    if top5_customer is None:
        items.append(warning_data(15, "收入集中度", "缺少前五客户收入占比"))
    elif top5_customer > 0.60 and not is_soe:
        items.append(veto_item(15, "收入集中度", f"前五客户占比{top5_customer:.1%}，且非国企"))
    else:
        items.append(pass_item(15, "收入集中度", f"前五客户占比{top5_customer:.1%}"))

    q4_ratio = to_float(supplemental.get("q4_revenue_ratio"))
    if q4_ratio is None:
        items.append(warning_data(16, "Q4收入突增", "缺少Q4收入占比"))
    elif q4_ratio > 0.40:
        items.append(veto_item(16, "Q4收入突增", f"Q4收入占比{q4_ratio:.1%} > 40%"))
    else:
        items.append(pass_item(16, "Q4收入突增", f"Q4收入占比{q4_ratio:.1%}"))

    non_standard = bool_value(supplemental, "non_standard_audit")
    if non_standard is None:
        items.append(warning_data(17, "审计意见", "缺少年度审计意见"))
    elif non_standard:
        items.append(veto_item(17, "审计意见", "审计意见非标准"))
    else:
        items.append(pass_item(17, "审计意见", "审计意见标准无保留"))

    integrity_issue = bool_value(supplemental, "management_integrity_issue")
    if integrity_issue is None:
        items.append(warning_data(18, "管理层诚信", "缺少管理层诚信记录"))
    elif integrity_issue:
        items.append(veto_item(18, "管理层诚信", "发现欺诈/内幕交易/挪用记录"))
    else:
        items.append(pass_item(18, "管理层诚信", "未发现诚信红旗"))

    subsidy_ratio = to_float(supplemental.get("subsidy_profit_ratio"))
    subsidy_three_year = bool_value(supplemental, "subsidy_high_three_year")
    if subsidy_ratio is None or subsidy_three_year is None:
        items.append(warning_data(19, "政府补贴依赖", "缺少政府补贴趋势数据"))
    elif subsidy_ratio > 0.50 and subsidy_three_year:
        items.append(warning_risk(19, "政府补贴依赖", "政府补贴占净利润>50%且持续三年"))
    else:
        items.append(pass_item(19, "政府补贴依赖", "补贴依赖度可接受"))

    bonus_points = 0

    holding_coverage = to_float(supplemental.get("holding_value_coverage"))
    if holding_coverage is None:
        items.append(warning_data(20, "上市子公司持股价值", "缺少持股价值覆盖率"))
    else:
        if holding_coverage > 1.0:
            bonus = 3
        elif holding_coverage >= 0.5:
            bonus = 2
        elif holding_coverage >= 0.2:
            bonus = 1
        else:
            bonus = 0
        bonus_points += bonus
        items.append(pass_item(20, "上市子公司持股价值", f"覆盖率={holding_coverage:.1%}，加分+{bonus}"))

    controller_ratio = ownership.controller_ratio
    controller_level = ownership.controller_level
    if controller_ratio is None or controller_level is None:
        items.append(warning_data(21, "国企/央企属性", "缺少实控人层级或持股比例"))
    else:
        if "央企" in controller_level:
            base = 3
        elif "省" in controller_level or "直辖市" in controller_level:
            base = 2
        elif "市" in controller_level or "区" in controller_level:
            base = 1
        else:
            base = 0
        if controller_ratio < 0.10:
            bonus = 0
        elif controller_ratio < 0.30:
            bonus = base // 2
        else:
            bonus = base
        bonus_points += bonus
        items.append(pass_item(21, "国企/央企属性", f"层级={controller_level} 持股={controller_ratio:.1%}，加分+{bonus}"))

    bonus_points = min(bonus_points, 5)

    warning_data_count = sum(1 for item in items if item.warning_class == WarningClass.DATA)
    warning_risk_count = sum(1 for item in items if item.warning_class == WarningClass.RISK)
    veto_count = sum(1 for item in items if item.decision == Decision.VETO)

    base_rating = rating_from_counts(warning_risk_count, veto_count)
    final_rating = apply_bonus(base_rating, bonus_points)

    return FactCheckResult(items, warning_data_count, warning_risk_count, veto_count, bonus_points, base_rating, final_rating)
