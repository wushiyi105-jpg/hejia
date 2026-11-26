"""集成测试:真起 HTTP 服务、真接一个假模型服务、真跑 CLI 子进程。

test_hejia.py 里的用例只调纯函数;这里走完整链路,
断言的是「请求进来 → 核查结果出去」这条路上的字段、数字与守卫。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hejia import agent, llm, rules, web
from hejia import db as dbmod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
QUOTE_TOTAL = 10005


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestHTTPServer(unittest.TestCase):
    """起 ThreadingHTTPServer 在随机端口,POST 一次,断言 JSON 里的数字。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db = dbmod.Database(os.path.join(self.tmp.name, "hejia.db"))
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), web._handler(db, {"api_key": None}, True))
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def _get(self, path: str) -> str:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=10) as r:
            return r.read().decode("utf-8")

    def _post(self, payload: dict, path: str = "/api/audit"):
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_page_and_status(self):
        self.assertIn("核价", self._get("/"))
        status = json.loads(self._get("/api/status"))
        self.assertTrue(status["mock"])
        self.assertIsNone(status["model"])

    def test_post_audit_numbers(self):
        code, report = self._post({"text": QUOTE, "city": "成都", "area": "89"})
        self.assertEqual(code, 200)
        self.assertEqual(report["mode"], "offline")
        # 服务端算出来的合计必须和本地纯函数一致,不允许两条路径给出两个数
        self.assertEqual(report["summary"]["total"], QUOTE_TOTAL)
        self.assertEqual(report["summary"]["total"], rules.audit(QUOTE)["summary"]["total"])
        self.assertEqual(report["summary"]["per_sqm"], round(QUOTE_TOTAL / 89, 0))
        self.assertEqual(len([x for x in report["lines"] if x["ok"]]), 8)
        self.assertTrue(report["saved_id"])
        self.assertGreaterEqual(len(report["issues"]), 1)

    def test_area_empty_is_none(self):
        code, report = self._post({"text": QUOTE, "city": "", "area": ""})
        self.assertEqual(code, 200)
        self.assertIsNone(report["summary"]["per_sqm"])

    def test_post_unknown_path_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post({"text": QUOTE}, path="/api/nope")
        self.assertEqual(ctx.exception.code, 404)


class FakeLLM(BaseHTTPRequestHandler):
    """假的 OpenAI 兼容服务:按请求内容返回固定 JSON。

    hejia 的契约是 {"summary", "questions":[{"quote","question"}], "risks":[]};
    这里刻意照这个 schema 返回,不借用别的仓库的字段名。
    """

    payload = {}
    calls = 0

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        assert body["messages"]  # 请求必须带 messages,否则这个假服务不该给出正常回答
        type(self).calls += 1
        content = json.dumps(self.payload, ensure_ascii=False)
        data = json.dumps({"choices": [{"message": {"content": content},
                                        "finish_reason": "stop"}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TestModelLayer(unittest.TestCase):
    """假模型返回各种坏东西,验证守卫真的把它们丢掉。"""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.cfg = {"api_key": "test-key", "base_url": "http://127.0.0.1:%d" % cls.port,
                   "model": "fake-model"}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        FakeLLM.calls = 0

    def test_drops_fabricated_quote_and_strips_money(self):
        FakeLLM.payload = {
            "summary": "这份报价合计 10005 元,先核单价再谈总价。",
            "questions": [
                {"quote": "墙砖铺贴 ㎡ 25 65 1625", "question": "这一行含不含倒角与勾缝?"},
                {"quote": "不锈钢台面 ㎡ 3 800", "question": "台面是否单独报价?"},
                {"quote": "乳胶漆 ㎡ 80 25 2000", "question": "乳胶漆 2000 元是几遍?什么品牌?"},
            ],
            "risks": ["管理费 4800 元可能重复计取", "进场后按实际发生容易变增项"],
        }
        r = agent.audit(QUOTE, city="成都", area=89, config=self.cfg, force_mock=False)
        self.assertEqual(r["mode"], "model")

        quotes = [q["quote"] for q in r["questions"]]
        # 报价单里没有的那条必须被丢弃,不能只断言「正确的那条还在」
        self.assertNotIn("不锈钢台面 ㎡ 3 800", quotes)
        self.assertIn("墙砖铺贴 ㎡ 25 65 1625", quotes)
        self.assertEqual(len(quotes), 2)

        # 模型写在问题里的金额一律剥掉,金额只信本地复算
        for q in r["questions"]:
            self.assertNotIn("2000", q["question"])
        self.assertIn("该金额", r["questions"][-1]["question"])

        self.assertNotIn("10005", r["summary"])
        self.assertNotIn("4800", " ".join(r["risks"]))
        self.assertEqual(len(r["risks"]), 2)

    def test_all_quotes_dropped_leaves_empty_list(self):
        FakeLLM.payload = {
            "summary": "报价单整体偏高,建议重新比价。",
            "questions": [
                {"quote": "全屋整装 项 1 98000", "question": "整装包不包主材?"},
                {"quote": "赠送家电三件套", "question": "赠送的家电是哪些型号?"},
            ],
            "risks": [],
        }
        r = agent.audit(QUOTE, config=self.cfg, force_mock=False)
        # 两条引用都不在原文里 → 全部丢弃,而不是原样透传
        self.assertEqual(r["questions"], [])
        self.assertEqual(r["risks"], [])
        self.assertTrue(r["verdict"])
        self.assertEqual(FakeLLM.calls, 1)

    def test_llm_unreachable_raises(self):
        cfg = dict(self.cfg, base_url="http://127.0.0.1:%d" % free_port())
        with self.assertRaises(llm.LLMError):
            llm.chat([{"role": "user", "content": "hi"}], config=cfg, retries=0, timeout=3)


class TestCLI(unittest.TestCase):
    """subprocess 跑 CLI,断言退出码与 stdout / stderr 关键行。"""

    def _run(self, *args):
        return subprocess.run([sys.executable, "-m", "hejia", *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8")

    def test_audit_file_end_to_end(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(QUOTE)
            path = f.name
        try:
            p = self._run("--mock", "audit", "--file", path, "--city", "成都", "--area", "89")
        finally:
            os.unlink(path)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("装修报价核查", p.stdout)
        self.assertIn("合计 10005 元", p.stdout)
        self.assertIn("112 元/㎡", p.stdout)

    def test_json_output_is_machine_readable(self):
        p = self._run("--mock", "--json", "audit", "--text", QUOTE)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data["summary"]["total"], QUOTE_TOTAL)
        self.assertEqual(data["mode"], "offline")
        self.assertEqual(len(data["lines"]), 8)

    def test_empty_text_exit_2(self):
        p = self._run("--mock", "audit", "--text", "  ")
        self.assertEqual(p.returncode, 2)
        self.assertIn("没有报价文本", p.stderr)

    def test_missing_file_exit_2(self):
        p = self._run("--mock", "audit", "--file", os.path.join(ROOT, "_no_such_quote.txt"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("读不到文件", p.stderr)

    def test_non_utf8_file_exit_2(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as f:
            f.write("拆除墙体 ㎡ 12 45 540".encode("gbk"))
            path = f.name
        try:
            p = self._run("--mock", "audit", "--file", path)
        finally:
            os.unlink(path)
        self.assertEqual(p.returncode, 2)
        self.assertIn("不是 UTF-8 编码", p.stderr)


if __name__ == "__main__":
    unittest.main()
