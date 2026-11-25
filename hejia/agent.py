"""核心编排:复算与对标全在本地,模型只写问题与风险提示。

硬约束:模型输出不允许出现金额。任何「xx 元」「¥xx」都会被剥掉,
答案里的数字只来自报价单本身(行号、数量、单价、小计)。
"""

from __future__ import annotations

import re

from . import llm, mock, rules

JSON_ONLY = "只输出 JSON,不要输出解释或多余文字。"
MONEY_RE = re.compile(r"(¥|￥)?\s*\d+(?:\.\d+)?\s*(?:元|块)(?:/(?:㎡|平|延米|项|套|个))?")


def _use_model(config: dict | None, force_mock: bool) -> bool:
    if force_mock:
        return False
    cfg = {**llm.default_config(), **(config or {})}
    return bool(cfg.get("api_key"))


def _cfg(config: dict | None) -> dict:
    return {**llm.default_config(), **(config or {})}


def strip_money(text: str) -> str:
    """剥掉金额,只留文字。金额一律以本地复算为准。"""
    return MONEY_RE.sub("该金额", text).replace("该金额该金额", "该金额")


def _model_questions(result: dict, config: dict | None) -> dict:
    cfg = _cfg(config)
    lines = [x for x in result["lines"] if x["ok"]]
    table = "\n".join(
        f"第{x['line_no']}行 {x['name']} {x['qty']:g}{x['unit']} × {x['price']:g} = {x['subtotal']:g}"
        for x in lines
    )
    issues = "\n".join(f"[{i['kind']}] {i['detail']}" for i in result["issues"][:12])
    raw = llm.chat([{
        "role": "system",
        "content": ("你是装修报价审阅助手。只根据给出的报价行、本地疑点和标准工序说话;"
                    "不要输出任何金额数字,不要编造报价单里没有的项目;引用原文时逐字照抄。"),
    }, {
        "role": "user",
        "content": (
            f"报价行:\n{table}\n\n本地疑点:\n{issues}\n\n含糊话术:{[v['phrase'] for v in result['vague']]}\n"
            f"{JSON_ONLY}\n输出格式:"
            '{"summary":"三句话内说明这份报价的主要问题",'
            '"questions":[{"quote":"报价单原文片段","question":"要问施工方的具体问题"}],'
            '"risks":["增项或结算风险"]}'
        ),
    }], config=cfg, temperature=0.2, max_tokens=2400)
    data = llm.extract_json(raw)

    text = "\n".join(x["raw"] for x in lines)
    questions = []
    for q in data.get("questions", []):
        quote = str(q.get("quote") or "").strip()
        question = strip_money(str(q.get("question") or ""))
        if not question or (quote and quote not in text):
            continue
        questions.append({"quote": quote or "报价单", "question": question})
    return {
        "summary": strip_money(str(data.get("summary") or rules.local_summary(result))),
        "questions": questions,
        "risks": [strip_money(str(r)) for r in data.get("risks", [])][:6],
    }


def audit(text: str, city: str | None = None, area: float | None = None,
          config: dict | None = None, db=None, force_mock: bool = False,
          save: bool = False) -> dict:
    result = rules.audit(text, city=city, area=area)
    if _use_model(config, force_mock):
        layers = _model_questions(result, config)
        mode = "model"
    else:
        layers = mock.offline(result)
        mode = "offline"

    result.update({
        "verdict": layers["summary"],
        "questions": layers["questions"],
        "risks": layers["risks"],
        "mode": mode,
        "saved_id": None,
    })
    if db is not None and save:
        result["saved_id"] = db.save(result)
    return result
