from src.llm.openai_client import normalize_openai_base_url


def test_normalize_openai_website_url_to_api_endpoint() -> None:
    assert normalize_openai_base_url("https://openai.com/api/v1") == (
        "https://api.openai.com/v1"
    )


def test_normalize_openai_base_url_preserves_compatible_proxy() -> None:
    assert normalize_openai_base_url("https://openrouter.ai/api/v1/") == (
        "https://openrouter.ai/api/v1"
    )


def test_normalize_openai_base_url_returns_none_when_unset() -> None:
    assert normalize_openai_base_url("  ") is None
