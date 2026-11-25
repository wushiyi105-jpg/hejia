"""离线模式:没有 key 时的问题清单与风险提示,全部由本地结果拼出。"""

from __future__ import annotations

from . import rules


def offline(result: dict) -> dict:
    risks = []
    kinds: dict[str, int] = {}
    for i in result["issues"]:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    if kinds.get("重复"):
        risks.append("存在疑似重复计费,签字前要求按工序合并报价")
    if kinds.get("漏项"):
        risks.append("有工序没列出子项,进场后容易变成增项")
    if kinds.get("单价"):
        risks.append("部分单价偏离参考区间,先问材料品牌与工艺再谈价")
    if kinds.get("复算"):
        risks.append("有小计与数量×单价不一致,按哪个金额结算要书面确认")
    return {
        "summary": rules.local_summary(result),
        "questions": rules.local_questions(result),
        "risks": risks,
        "note": "离线模式:问题与风险由本地规则生成,未经过模型。",
    }
