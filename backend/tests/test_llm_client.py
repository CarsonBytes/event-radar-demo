from unittest.mock import patch

import pytest

from app.llm_client import (
    _active_key_index,
    _advance_chatanywhere_key,
    _current_chatanywhere_key,
    invoke_with_rotation,
)


@pytest.fixture(autouse=True)
def reset_key_rotation():
    # Module-level state -- without resetting it, whichever test runs first
    # and rotates past index 0 would leave every later test starting from
    # the fallback key instead of the primary one.
    _active_key_index[0] = 0
    yield
    _active_key_index[0] = 0


class TestKeyRotationState:
    def test_starts_on_primary_key(self):
        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", "key-b"):
            assert _current_chatanywhere_key() == "key-a"

    def test_advance_moves_to_fallback_key(self):
        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", "key-b"):
            assert _advance_chatanywhere_key() is True
            assert _current_chatanywhere_key() == "key-b"

    def test_advance_returns_false_when_no_fallback_configured(self):
        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", ""):
            assert _advance_chatanywhere_key() is False
            assert _current_chatanywhere_key() == "key-a"

    def test_advance_returns_false_once_already_on_last_key(self):
        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", "key-b"):
            assert _advance_chatanywhere_key() is True
            assert _advance_chatanywhere_key() is False
            assert _current_chatanywhere_key() == "key-b"


class TestInvokeWithRotation:
    def test_returns_result_on_first_success_without_rotating(self):
        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", "key-b"):
            result = invoke_with_rotation(lambda: "ok")
            assert result == "ok"
            assert _current_chatanywhere_key() == "key-a"

    def test_retries_once_on_quota_exhaustion_and_succeeds_on_fallback_key(self):
        calls = []

        def flaky():
            calls.append(_current_chatanywhere_key())
            if len(calls) == 1:
                raise RuntimeError("Error code: 429 - free account is limited to 200 requests per day")
            return "ok from fallback"

        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", "key-b"):
            result = invoke_with_rotation(flaky)

        assert result == "ok from fallback"
        assert calls == ["key-a", "key-b"]

    def test_reraises_when_no_fallback_key_available(self):
        def always_quota_exhausted():
            raise RuntimeError("429 rate limit")

        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", ""):
            with pytest.raises(RuntimeError, match="429"):
                invoke_with_rotation(always_quota_exhausted)

    def test_does_not_retry_on_a_non_quota_error(self):
        calls = []

        def always_fails():
            calls.append(1)
            raise ConnectionError("timed out")

        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", "key-b"):
            with pytest.raises(ConnectionError):
                invoke_with_rotation(always_fails)

        assert len(calls) == 1  # no rotation/retry for a non-quota failure

    def test_does_not_rotate_when_last_provider_used_was_deepseek(self):
        # A DeepSeek call failing with something that happens to look like a
        # rate-limit error shouldn't burn a chatanywhere key rotation --
        # they're unrelated accounts/quotas.
        calls = []

        def always_fails():
            calls.append(1)
            raise RuntimeError("429 rate limit")

        with patch("app.llm_client.OPENAI_API_KEY", "key-a"), \
             patch("app.llm_client.OPENAI_API_KEY_FALLBACK", "key-b"), \
             patch("app.llm_client.last_provider_used", return_value="deepseek"):
            with pytest.raises(RuntimeError):
                invoke_with_rotation(always_fails)

        assert len(calls) == 1
