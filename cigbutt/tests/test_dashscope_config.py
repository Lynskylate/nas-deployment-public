from pathlib import Path

from cigbutt.config import resolve_dashscope_config


def test_dashscope_config_file_then_env_override(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[dashscope]",
                'api_key = "file-api-key"',
                'base_url = "https://dashscope-file.example/v1"',
                'model = "qwen-file"',
                "timeout_seconds = 33",
            ]
        ),
        encoding="utf-8",
    )

    from_file = resolve_dashscope_config(config_path=str(config_path), env={})
    assert from_file["api_key"] == "file-api-key"
    assert from_file["base_url"] == "https://dashscope-file.example/v1"
    assert from_file["model"] == "qwen-file"
    assert from_file["timeout_seconds"] == 33

    with_env = resolve_dashscope_config(
        config_path=str(config_path),
        env={
            "DASHSCOPE_API_KEY": "env-api-key",
            "DASHSCOPE_TIMEOUT_SECONDS": "12",
        },
    )
    assert with_env["api_key"] == "env-api-key"
    assert with_env["base_url"] == "https://dashscope-file.example/v1"
    assert with_env["model"] == "qwen-file"
    assert with_env["timeout_seconds"] == 12
