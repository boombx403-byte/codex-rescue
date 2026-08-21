"""Alpha8 share_redact tests: issue-grade token/path scrubbing."""

from __future__ import annotations

import unittest

from codex_rescue.share_redact import redact_for_share


class ShareRedactTests(unittest.TestCase):
    def test_openai_project_key(self) -> None:
        text = "error with key sk-proj-ABCDEF1234567890abcdef1234"
        res = redact_for_share(text)
        self.assertNotIn("sk-proj-", res.text)
        self.assertIn("[REDACTED_OPENAI_KEY]", res.text)
        self.assertGreaterEqual(res.hits.get("REDACTED_OPENAI_KEY", 0), 1)

    def test_aws_and_google_keys(self) -> None:
        text = "AKIAIOSFODNN7EXAMPLE and AIzaSyA1234567890abcdefghijklmnopqrstuvwx"
        res = redact_for_share(text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", res.text)
        self.assertNotIn("AIza", res.text.replace("[REDACTED_GOOGLE_KEY]", ""))

    def test_github_token_upstream(self) -> None:
        text = "using ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        res = redact_for_share(text)
        self.assertNotIn("ghp_", res.text)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", res.text)

    def test_keyed_json_secret(self) -> None:
        text = '{"api_key": "a1b2c3d4e5f6g7h8", "name": "test"}'
        res = redact_for_share(text)
        self.assertNotIn("a1b2c3d4e5f6g7h8", res.text)
        self.assertIn("[REDACTED_KEYED_SECRET]", res.text)
        # Non-secret keys untouched.
        self.assertIn('"name": "test"', res.text)

    def test_windows_user_path(self) -> None:
        res = redact_for_share(r"log from C:\Users\alice\.codex\sessions\x.jsonl")
        self.assertNotIn("alice", res.text)
        self.assertIn("~", res.text)

    def test_email_scrubbed(self) -> None:
        res = redact_for_share("contact me at john.doe@example.com please")
        self.assertNotIn("john.doe@example.com", res.text)
        self.assertIn("[REDACTED_EMAIL]", res.text)

    def test_clean_text_untouched(self) -> None:
        clean = "HEALTHY session, no findings, cwd ~/work/project"
        res = redact_for_share(clean)
        self.assertEqual(res.text, clean)
        self.assertEqual(res.total_hits, 0)


if __name__ == "__main__":
    unittest.main()
