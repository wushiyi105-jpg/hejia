"""核价 · 本地规则层:报价行解析、复算、单位归一、单价对标、漏项与重复检测。

每个结论都能回指报价行:行号、原文、数量、单价、小计。模型不参与任何金额计算。
"""

from __future__ import annotations

import json
import os
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

UNITS = ["平方米", "平米", "㎡", "m2", "延米", "米", "项", "套", "个", "组", "张", "樘", "台"]

UNIT_ALIAS = {"平方米": "㎡", "平米": "㎡", "m2": "㎡", "㎡": "㎡",
              "米": "延米", "延米": "延米", "m": "延米"}

LINE_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<unit>" + "|".join(UNITS) + r")\s+(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<price>\d+(?:\.\d+)?)(?:\s+(?P<sub>\d+(?:\.\d+)?))?\s*$"
)
LOOSE_RE = re.compile(r"^(?P<name>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+(?P<price>\d+(?:\.\d+)?)"
                      r"(?:\s+(?P<sub>\d+(?:\.\d+)?))?\s*$")

CITY_FACTOR = {"北京": 1.25, "上海": 1.22, "深圳": 1.2, "广州": 1.05, "杭州": 1.05,
               "南京": 0.95, "成都": 0.85, "武汉": 0.82, "西安": 0.78, "重庆": 0.75}

PROCESS_WORDS = [
    ("拆改", ("拆", "铲", "清运", "砸")),
    ("防水", ("防水", "闭水", "涂膜")),
    ("水电", ("电", "线", "开关", "插座", "配电", "水路", "管", "开槽", "弱电", "强电")),
    ("瓦工", ("砖", "瓦", "找平", "踢脚", "立管", "过门石", "美缝")),
    ("木工", ("木", "吊顶", "柜", "门套", "窗帘盒", "造型")),
    ("油漆", ("漆", "墙纸", "基层", "腻子", "涂刷")),
    ("安装", ("安装", "灯具", "洁具", "五金", "打孔", "热水器", "橱柜")),
]


def load_seed(name: str) -> list[dict]:
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def normalize_unit(unit: str) -> str:
    return UNIT_ALIAS.get(unit, unit)


def parse_lines(text: str) -> list[dict]:
    """把报价单按行解析。识别失败的行走 issues,不静默丢弃。"""
    lines = []
    for no, raw in enumerate((text or "").splitlines(), 1):
        raw = raw.strip().replace("|", "  ").replace("\t", "  ")
        raw = re.sub(r"\s{2,}", "  ", raw)
        if not raw or raw.startswith("#"):
            continue
        m = LINE_RE.match(raw) or LOOSE_RE.match(raw)
        if not m:
            lines.append({"line_no": no, "raw": raw, "ok": False, "reason": "这行没解析出来"})
            continue
        unit = m.groupdict().get("unit") or ""
        unit = normalize_unit(unit)
        qty = float(m.group("qty"))
        price = float(m.group("price"))
        sub = m.group("sub")
        sub = float(sub) if sub is not None else None
        expected = round(qty * price, 2)
        if sub is None:
            diff = 0.0
            flag = "无小计,按数量×单价推算"
        else:
            diff = round(sub - expected, 2)
            flag = "" if abs(diff) <= 0.5 else f"小计与数量×单价差 {diff:+.2f}"
        name = m.group("name").strip()
        lines.append({
            "line_no": no, "raw": raw, "ok": True,
            "name": name, "unit": unit, "qty": qty, "price": price,
            "subtotal": sub if sub is not None else expected,
            "expected": expected, "diff": diff, "flag": flag,
            "process": classify(name),
        })
    return lines


def classify(name: str) -> str:
    if "管理费" in name or "设计费" in name or "搬运" in name:
        return "其他"
    for process, words in PROCESS_WORDS:
        if any(w in name for w in words):
            return process
    return "其他"


def benchmark(item: dict, city: str | None = None, prices: list[dict] | None = None) -> dict | None:
    prices = prices if prices is not None else load_seed("prices.json")
    best = None
    for p in prices:
        if p["name"] in item["name"] or item["name"] in p["name"]:
            if best is None or len(p["name"]) > len(best["name"]):
                best = p
    if not best:
        return None
    factor = CITY_FACTOR.get(city or "", 1.0)
    low, high = best["low"] * factor, best["high"] * factor
    price = item["price"]
    if item["unit"] and normalize_unit(best["unit"]) != item["unit"]:
        return {"name": best["name"], "low": round(low), "high": round(high),
                "verdict": "单位不同,无法直接对标"}
    if price > high * 1.2:
        verdict = f"高于区间上限 {price / high:.1f} 倍"
    elif price < low * 0.8:
        verdict = "低于区间下限,问清材料品牌与工艺"
    else:
        verdict = "在区间内"
    return {"name": best["name"], "low": round(low), "high": round(high), "verdict": verdict}


def find_duplicates(lines: list[dict]) -> list[dict]:
    out = []
    ok = [x for x in lines if x["ok"]]
    for i, a in enumerate(ok):
        for b in ok[i + 1:]:
            if a["process"] != b["process"]:
                continue
            na, nb = a["name"], b["name"]
            if na in nb or nb in na:
                out.append({"a": a, "b": b,
                            "detail": f"第 {a['line_no']} 行「{na}」与第 {b['line_no']} 行「{nb}」疑似重复计费"})
    return out


def find_missing(lines: list[dict], standard: list[dict] | None = None) -> list[dict]:
    standard = standard if standard is not None else load_seed("standard.json")
    ok = [x for x in lines if x["ok"]]
    present = {x["process"] for x in ok}
    names = " ".join(x["name"] for x in ok)
    missing = []
    for s in standard:
        if s["process"] not in present:
            continue
        key = s["item"].split("(")[0]
        words = [w for w in re.split(r"[与/(、)]", key) if len(w) >= 2]
        if not any(w in names for w in words) and key[:4] not in names:
            missing.append(s)
    return missing


def hit_vague(text: str, vague: list[dict] | None = None) -> list[dict]:
    vague = vague if vague is not None else load_seed("vague.json")
    return [v for v in vague if v["phrase"] in text]


def summarize(lines: list[dict]) -> dict:
    by_process: dict[str, float] = {}
    total = 0.0
    for x in lines:
        if not x["ok"]:
            continue
        by_process[x["process"]] = by_process.get(x["process"], 0.0) + x["subtotal"]
        total += x["subtotal"]
    rows = [{"process": k, "amount": round(v, 2),
             "share": round(v / total * 100, 1) if total else 0.0}
            for k, v in sorted(by_process.items(), key=lambda kv: -kv[1])]
    return {"total": round(total, 2), "by_process": rows}


def audit(text: str, city: str | None = None, area: float | None = None) -> dict:
    lines = parse_lines(text)
    ok = [x for x in lines if x["ok"]]
    summary = summarize(lines)

    issues = []
    for x in ok:
        if x["flag"]:
            issues.append({"kind": "复算", "line_no": x["line_no"], "raw": x["raw"],
                           "detail": x["flag"], "amount": abs(x["diff"]) if x["diff"] else 0})
        bm = benchmark(x, city)
        if bm and bm["verdict"] not in ("在区间内", "单位不同,无法直接对标"):
            issues.append({"kind": "单价", "line_no": x["line_no"], "raw": x["raw"],
                           "detail": f"{bm['name']} 参考 {bm['low']}–{bm['high']} 元/{x['unit']},{bm['verdict']}"})
        if x["unit"] in ("项", "套") and x["process"] != "其他":
            issues.append({"kind": "模糊计价", "line_no": x["line_no"], "raw": x["raw"],
                           "detail": f"「按{'项' if x['unit'] == '项' else '套'}报价」看不出工作量,要求改为按量计价"})

    for d in find_duplicates(lines):
        issues.append({"kind": "重复", "line_no": d["a"]["line_no"], "raw": d["a"]["raw"],
                       "detail": d["detail"]})

    bad_lines = [x for x in lines if not x["ok"]]
    for x in bad_lines:
        issues.append({"kind": "解析失败", "line_no": x["line_no"], "raw": x["raw"],
                       "detail": x["reason"]})

    missing = find_missing(lines)
    for m in missing:
        issues.append({"kind": "漏项", "line_no": 0, "raw": "",
                       "detail": f"「{m['process']}」里没看到「{m['item']}」"})

    if area and summary["total"]:
        per_sqm = round(summary["total"] / area, 0)
        summary["per_sqm"] = per_sqm
    else:
        summary["per_sqm"] = None

    return {
        "lines": lines,
        "summary": summary,
        "issues": issues,
        "vague": hit_vague(text),
        "area": area,
        "city": city or "",
        "missing": missing,
    }


def local_questions(result: dict) -> list[dict]:
    """离线模式的问题清单:含糊话术 + 漏项 + 复算差额,每条挂原文。"""
    out = []
    for v in result["vague"][:5]:
        out.append({"quote": v["phrase"], "question": v["question"]})
    for m in result["missing"][:4]:
        out.append({"quote": "报价单未列", "question": f"「{m['item']}」是否包含?不含的话单项多少钱?"})
    for i in result["issues"]:
        if i["kind"] == "复算":
            out.append({"quote": i["raw"], "question": f"这一行小计对不上:{i['detail']},按哪个金额结算?"})
            break
    return out


def local_summary(result: dict) -> str:
    s = result["summary"]
    if not s["total"]:
        return "没解析出有效的报价行,先确认每行是「项目 单位 数量 单价 小计」的格式。"
    head = f"报价合计 {s['total']:.0f} 元"
    if s.get("per_sqm"):
        head += f",折合 {s['per_sqm']:.0f} 元/㎡"
    counts: dict[str, int] = {}
    for i in result["issues"]:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    if counts:
        head += ";疑点 " + "、".join(f"{k} {v} 处" for k, v in counts.items()) + "。"
    return head
