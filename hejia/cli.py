"""命令行入口:python -m hejia <命令>。"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, agent, llm, rules
from . import db as dbmod
from .llm import LLMError

BANNER = (
    "⚠️  当前为离线模式(未配置 LLM_API_KEY):复算、对标、漏项由本地规则给出。\n"
    "   填入 LLM_API_KEY 后,问题清单与风险提示由模型撰写(金额仍以本地复算为准)。\n"
)


def render(result: dict) -> str:
    s = result["summary"]
    mode = "模型" if result["mode"] == "model" else "离线模式"
    lines = [f"🧮 装修报价核查  [{mode}]", "", "📌 " + result["verdict"], ""]

    ok = [x for x in result["lines"] if x["ok"]]
    lines.append("📋 逐行复算")
    for x in ok:
        mark = "✅" if not x["flag"] else "⚠️"
        lines.append(f"  {mark} {x['line_no']:>2} {x['name']}  {x['qty']:g}{x['unit']} × {x['price']:g} "
                     f"= {x['subtotal']:g}    [{x['process']}]")
        if x["flag"]:
            lines.append(f"        ↳ {x['flag']}(应为 {x['expected']:g})")
    bad = [x for x in result["lines"] if not x["ok"]]
    if bad:
        lines.append("  ❓ 未解析:")
        for x in bad:
            lines.append(f"     第{x['line_no']}行 {x['raw']}")
    lines.append("")

    lines.append(f"💰 合计 {s['total']:.0f} 元" + (f"  ·  {s['per_sqm']:.0f} 元/㎡" if s.get("per_sqm") else ""))
    for r in s["by_process"]:
        lines.append(f"  · {r['process']}:{r['amount']:.0f} 元({r['share']}%)")
    lines.append("")

    if result["issues"]:
        lines.append(f"⚠️  疑点({len(result['issues'])})")
        for i in result["issues"]:
            loc = f"第{i['line_no']}行" if i["line_no"] else "报价单"
            lines.append(f"  · [{i['kind']}] {loc}:{i['detail']}")
        lines.append("")

    if result["questions"]:
        lines.append("❓ 要问施工方的问题")
        for q in result["questions"]:
            lines.append(f"  · 「{q['quote']}」→ {q['question']}")
        lines.append("")

    if result["risks"]:
        lines.append("🚩 结算风险")
        for r in result["risks"]:
            lines.append(f"  · {r}")
    if result.get("note"):
        lines.append("")
        lines.append(f"注:{result['note']}")
    return "\n".join(lines)


def cmd_audit(args):
    text = ""
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"❌ 读不到文件:{args.file}({e.strerror or e})", file=sys.stderr)
            sys.exit(2)
        except UnicodeError:
            print(f"❌ 文件不是 UTF-8 编码,请另存为 UTF-8 后重试:{args.file}", file=sys.stderr)
            sys.exit(2)
    elif args.text:
        text = args.text
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    if not text.strip():
        print("❌ 没有报价文本:用 --text、--file,或管道输入。", file=sys.stderr)
        sys.exit(2)
    db = dbmod.Database(args.db) if args.db else dbmod.Database()
    r = agent.audit(text, city=args.city, area=args.area, config=llm.config_from_args(args),
                    db=db, force_mock=args.mock, save=args.save)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(render(r))
        if r.get("saved_id"):
            print(f"\n已入库(#{r['saved_id']}),`python -m hejia history` 可对比多份报价。")


def cmd_prices(args):
    prices = rules.load_seed("prices.json")
    if args.grep:
        prices = [p for p in prices if args.grep in p["name"] or args.grep in p["process"]]
    if args.json:
        print(json.dumps(prices, ensure_ascii=False, indent=2))
        return
    print(f"💰 工序单价区间(基准城市,其他城市按系数换算)  共 {len(prices)} 条")
    for p in prices:
        print(f"  [{p['process']}] {p['name']}:{p['low']}–{p['high']} 元/{p['unit']}")


def cmd_checklist(args):
    standard = rules.load_seed("standard.json")
    print(f"✅ 标准工序检查清单({len(standard)} 项)")
    for process in ("拆改", "水电", "防水", "瓦工", "木工", "油漆", "安装", "其他"):
        items = [s for s in standard if s["process"] == process]
        if not items:
            continue
        print(f"\n【{process}】")
        for s in items:
            print(f"  □ {s['item']}")


def cmd_history(args):
    rows = dbmod.Database(args.db).latest(args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("还没有记录。`python -m hejia audit --file 报价.txt --save` 存一份。")
        return
    print("🧮 存过的报价")
    for r in rows:
        print(f"  #{r['id']}  {r.get('city') or '—'}  {r.get('area') or '—'}㎡  "
              f"合计 {r['total']:.0f} 元  行 {r['lines']}  疑点 {r['issues']}  {r['created_at']}")


def cmd_web(args):
    from . import web
    web.serve(host=args.host, port=args.port, db_path=args.db, force_mock=args.mock)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hejia", description="核价 · 装修报价核查:复算每一行,揪出重复与漏项。")
    p.add_argument("--version", action="version", version=f"hejia {__version__}")
    p.add_argument("--mock", action="store_true", help="强制离线模式")
    p.add_argument("--json", action="store_true", help="输出原始 JSON")
    p.add_argument("--model", help="覆盖 LLM_MODEL")
    p.add_argument("--base-url", help="覆盖 LLM_BASE_URL")
    p.add_argument("--api-key", help="覆盖 LLM_API_KEY")
    p.add_argument("--db", help="SQLite 路径")
    sub = p.add_subparsers(dest="command", required=True)

    ap = sub.add_parser("audit", help="核查一份报价单")
    ap.add_argument("--text", help="报价文本,每行「项目 单位 数量 单价 小计」")
    ap.add_argument("--file", help="从文件读")
    ap.add_argument("--city", help="城市,用于单价系数换算")
    ap.add_argument("--area", type=float, help="建筑面积,用于折算元/㎡")
    ap.add_argument("--save", action="store_true", help="存入库")
    ap.set_defaults(func=cmd_audit)

    pp = sub.add_parser("prices", help="查看工序单价区间")
    pp.add_argument("--grep", help="按工序或项目名过滤")
    pp.set_defaults(func=cmd_prices)

    cp = sub.add_parser("checklist", help="标准工序检查清单")
    cp.set_defaults(func=cmd_checklist)

    hp = sub.add_parser("history", help="存过的报价")
    hp.add_argument("--limit", type=int, default=10)
    hp.set_defaults(func=cmd_history)

    wp = sub.add_parser("web", help="启动 Web 界面")
    wp.add_argument("--host", default="127.0.0.1")
    wp.add_argument("--port", type=int, default=8000)
    wp.add_argument("--mock", action="store_true", default=argparse.SUPPRESS)
    wp.set_defaults(func=cmd_web)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.mock and args.command == "audit" and not llm.config_from_args(args).get("api_key"):
        print(BANNER, file=sys.stderr)
    try:
        args.func(args)
    except LLMError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
