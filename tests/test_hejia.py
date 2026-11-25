"""离线路径单测:报价解析、复算、对标、重复、漏项、金额守卫。"""

from __future__ import annotations

import unittest

from hejia import agent, mock, rules

QUOTE = "\n".join([
    "拆除墙体 ㎡ 12 45 540",
    "卫生间防水 ㎡ 8 55 440",
    "墙砖铺贴 ㎡ 25 65 1625",
    "地砖铺贴 ㎡ 30 60 1800",
    "墙面基层处理 ㎡ 80 20 1800",
    "乳胶漆 ㎡ 80 25 2000",
    "石膏板吊顶 ㎡ 10 120 1200",
    "开关插座安装 个 30 20 600",
])


class TestParse(unittest.TestCase):
    def test_parse_line(self):
        lines = rules.parse_lines("拆除墙体 ㎡ 12 45 540")
        self.assertEqual(len(lines), 1)
        item = lines[0]
        self.assertTrue(item["ok"])
        self.assertEqual(item["qty"], 12)
        self.assertEqual(item["subtotal"], 540)
        self.assertEqual(item["process"], "拆改")

    def test_recompute_mismatch(self):
        item = rules.parse_lines("墙面基层处理 ㎡ 80 20 1800")[0]
        self.assertEqual(item["expected"], 1600)
        self.assertIn("差 +200.00", item["flag"])

    def test_missing_subtotal_is_filled(self):
        item = rules.parse_lines("灯具安装 个 10 35")[0]
        self.assertEqual(item["subtotal"], 350)
        self.assertIn("推算", item["flag"])

    def test_unit_alias(self):
        self.assertEqual(rules.normalize_unit("平方米"), "㎡")
        self.assertEqual(rules.normalize_unit("米"), "延米")
        item = rules.parse_lines("水路改造 米 15 60 900")[0]
        self.assertEqual(item["unit"], "延米")

    def test_unparsed_line_kept(self):
        lines = rules.parse_lines("以上报价最终以实际为准")
        self.assertFalse(lines[0]["ok"])
        self.assertIn("没解析出来", lines[0]["reason"])

    def test_classify(self):
        self.assertEqual(rules.classify("闭水试验"), "防水")
        self.assertEqual(rules.classify("开关插座安装"), "水电")
        self.assertEqual(rules.classify("工程管理费"), "其他")


class TestChecks(unittest.TestCase):
    def test_benchmark_overpriced(self):
        item = rules.parse_lines("乳胶漆 ㎡ 80 200 16000")[0]
        bm = rules.benchmark(item, city="成都")
        self.assertIn("高于", bm["verdict"])

    def test_benchmark_city_factor_changes_range(self):
        item = rules.parse_lines("墙砖铺贴 ㎡ 10 100 1000")[0]
        cd = rules.benchmark(item, city="成都")
        bj = rules.benchmark(item, city="北京")
        self.assertLess(cd["high"], bj["high"])

    def test_duplicate_detection(self):
        text = "墙砖铺贴 ㎡ 25 65 1625\n墙砖铺贴(含辅料) ㎡ 25 30 750"
        lines = rules.parse_lines(text)
        dups = rules.find_duplicates(lines)
        self.assertEqual(len(dups), 1)

    def test_missing_standard_item(self):
        lines = rules.parse_lines("卫生间防水 ㎡ 8 55 440")
        missing = rules.find_missing(lines)
        names = [m["item"] for m in missing]
        self.assertIn("闭水试验(48 小时)", names)

    def test_summary_shares(self):
        result = rules.audit(QUOTE)
        total = result["summary"]["total"]
        self.assertAlmostEqual(total, 10005, places=2)
        shares = sum(r["share"] for r in result["summary"]["by_process"])
        self.assertGreater(shares, 99.0)

    def test_per_sqm(self):
        result = rules.audit(QUOTE, area=89.0)
        self.assertEqual(result["summary"]["per_sqm"], round(10005 / 89, 0))

    def test_vague_hits(self):
        result = rules.audit(QUOTE + "\n以上项目按实际发生结算")
        phrases = [v["phrase"] for v in result["vague"]]
        self.assertIn("按实际发生", phrases)


class TestAgent(unittest.TestCase):
    def test_offline_pipeline(self):
        r = agent.audit(QUOTE, city="成都", area=89, force_mock=True)
        self.assertEqual(r["mode"], "offline")
        self.assertIsNone(r["saved_id"])
        self.assertTrue(r["summary"])
        self.assertTrue(r["questions"])

    def test_strip_money(self):
        text = "这一项 1800 元明显偏高,按 1600 元结算"
        self.assertNotIn("1800", agent.strip_money(text))
        self.assertNotIn("1600", agent.strip_money(text))

    def test_offline_questions_have_no_amounts(self):
        r = agent.audit(QUOTE + "\n以上按实际发生", force_mock=True)
        for q in r["questions"]:
            self.assertNotIn("元", q["question"])

    def test_mock_matches_rules(self):
        result = rules.audit(QUOTE)
        out = mock.offline(result)
        self.assertEqual(out["summary"], rules.local_summary(result))
        self.assertEqual(out["questions"], rules.local_questions(result))


if __name__ == "__main__":
    unittest.main()
