import base64
import json
import os
import tempfile
import unittest

import checkin_ci


MACHINE_DOC = {
    "machineToken": "token-value",
    "machineCode": "code-value",
    "machineType": "type-value",
}


class EnvJsonTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(checkin_ci.parse_json_blob('{"a": 1}', "X"), {"a": 1})

    def test_base64_json_with_bom(self):
        raw = base64.b64encode(
            b"\xef\xbb\xbf" + json.dumps(MACHINE_DOC).encode("utf-8")
        ).decode()
        self.assertEqual(checkin_ci.parse_json_blob(raw + "\n", "X"), MACHINE_DOC)

    def test_invalid_blob_raises(self):
        with self.assertRaises(ValueError):
            checkin_ci.parse_json_blob("not-json-at-all!!", "X")
        with self.assertRaises(ValueError):
            checkin_ci.parse_json_blob("", "X")

    def test_machine_headers_mapping(self):
        raw = base64.b64encode(json.dumps(MACHINE_DOC).encode()).decode()
        headers = checkin_ci.machine_headers_from_json(raw)
        self.assertEqual(headers, {
            "Cosy-MachineToken": "token-value",
            "Cosy-MachineCode": "code-value",
            "Cosy-MachineType": "type-value",
        })

    def test_machine_headers_require_all_fields(self):
        with self.assertRaises(ValueError):
            checkin_ci.machine_headers_from_json('{"machineToken": "only-one"}')
        with self.assertRaises(ValueError):
            checkin_ci.machine_headers_from_json("[]")


class TraeStorageTests(unittest.TestCase):
    def test_materialize_writes_storage_json(self):
        payload = {"iCubeAuthInfo://icube.cloudide": '{"token": "synthetic"}'}
        raw = base64.b64encode(json.dumps(payload).encode()).decode()
        appdata = checkin_ci.materialize_trae_storage(raw)
        self.addCleanup(lambda: __import__("shutil").rmtree(appdata, ignore_errors=True))

        target = os.path.join(
            appdata, "Trae CN", "User", "globalStorage", "storage.json"
        )
        self.assertTrue(os.path.isfile(target))
        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), payload)

    def test_materialize_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            checkin_ci.materialize_trae_storage("")
        with self.assertRaises(ValueError):
            checkin_ci.materialize_trae_storage(base64.b64encode(b"nope").decode())


class WorkBuddyAuthTests(unittest.TestCase):
    def test_materialize_writes_auth_file(self):
        payload = {"auth": {"accessToken": "synthetic"}, "account": {}}
        raw = base64.b64encode(json.dumps(payload).encode()).decode()
        path = checkin_ci.materialize_workbuddy_auth(raw)
        self.addCleanup(lambda: __import__("shutil").rmtree(
            os.path.dirname(path), ignore_errors=True))
        self.assertTrue(os.path.isfile(path))
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), payload)

    def test_materialize_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            checkin_ci.materialize_workbuddy_auth("")
        with self.assertRaises(ValueError):
            checkin_ci.materialize_workbuddy_auth(base64.b64encode(b"nope").decode())

    def test_missing_secret_skips_instead_of_failing(self):
        os.environ.pop("WORKBUDDY_AUTH_B64", None)
        self.assertIsNone(checkin_ci.run_workbuddy())


class SummaryTests(unittest.TestCase):
    def test_writes_markdown_when_env_set(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "summary.md")
            os.environ["GITHUB_STEP_SUMMARY"] = path
            self.addCleanup(os.environ.pop, "GITHUB_STEP_SUMMARY", None)
            checkin_ci.write_summary([
                ("Qoder / Qoder CN", True, []),
                ("Trae CN", False, []),
            ])
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        self.assertIn("| Qoder / Qoder CN | ✅ 成功 |", content)
        self.assertIn("| Trae CN | ❌ 失败 |", content)

    def test_noop_without_env(self):
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        checkin_ci.write_summary([("X", True, [])])  # 不应抛异常

    def test_skip_renders_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "summary.md")
            os.environ["GITHUB_STEP_SUMMARY"] = path
            self.addCleanup(os.environ.pop, "GITHUB_STEP_SUMMARY", None)
            checkin_ci.write_summary([("WorkBuddy", None, [])])
            with open(path, "r", encoding="utf-8") as f:
                self.assertIn("| WorkBuddy | ⏭ 跳过 |", f.read())


class FeishuTests(unittest.TestCase):
    def test_payload_without_secret(self):
        payload = checkin_ci.feishu_payload("标题", "内容")
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(
            payload["card"]["header"]["title"]["content"], "标题")
        self.assertNotIn("sign", payload)
        self.assertNotIn("timestamp", payload)

    def test_payload_signature_matches_independent_hmac(self):
        import hashlib
        import hmac
        payload = checkin_ci.feishu_payload(
            "标题", "内容", secret="test-secret", timestamp=1700000000)
        expected = base64.b64encode(
            hmac.new(b"1700000000\ntest-secret", b"", hashlib.sha256).digest()
        ).decode()
        self.assertEqual(payload["timestamp"], "1700000000")
        self.assertEqual(payload["sign"], expected)

    def test_failure_template_is_red(self):
        payload = checkin_ci.feishu_payload("标题", "内容", template="red")
        self.assertEqual(payload["card"]["header"]["template"], "red")

    def test_push_without_webhook_is_noop(self):
        os.environ.pop("FEISHU_WEBHOOK", None)
        self.assertFalse(checkin_ci.push_feishu("标题", "内容"))


if __name__ == "__main__":
    unittest.main()
