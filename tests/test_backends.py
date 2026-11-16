import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from infographics.backends.base import image_data_url, image_paths
from infographics.backends.factory import load_model_config, make_backend
from infographics.backends.openai_compatible import OpenAICompatibleBackend, to_openai_messages


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "ref.png"
    path.write_bytes(b"\x89PNG fake")
    return path


def test_text_messages_pass_through():
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "topic"}]
    assert to_openai_messages(messages) == messages


def test_images_become_data_urls(image):
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image", "path": str(image)}]}]
    parts = to_openai_messages(messages)[0]["content"]
    assert parts[0] == {"type": "text", "text": "hi"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert image_paths(messages) == [str(image)]


def test_data_url_type_follows_extension(tmp_path):
    jpeg = tmp_path / "a.jpeg"
    jpeg.write_bytes(b"x")
    assert image_data_url(jpeg).startswith("data:image/jpeg;base64,")


def test_unknown_part_type_is_rejected():
    with pytest.raises(ValueError, match="unknown"):
        to_openai_messages([{"role": "user", "content": [{"type": "audio"}]}])


def test_missing_api_key_is_reported(monkeypatch):
    monkeypatch.delenv("NO_SUCH_KEY", raising=False)
    with pytest.raises(ValueError, match="NO_SUCH_KEY"):
        OpenAICompatibleBackend("m", api_key_env="NO_SUCH_KEY")


def test_qwen_config_loads_and_pins_its_checkpoint():
    config = load_model_config("configs/models/qwen3_5_9b.yaml")
    assert len(config["checkpoint"]) == 40
    assert config["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert isinstance(make_backend(config), OpenAICompatibleBackend)


def test_config_must_pin_checkpoint(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text("name: x\nbackend: openai_compatible\nmodel: x\nquantization: null\n")
    with pytest.raises(ValueError, match="checkpoint"):
        load_model_config(path)


class FakeVLLM(BaseHTTPRequestHandler):
    requests: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeVLLM.requests.append((self.path, body))
        reply = {
            "id": "1", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "length",
                         "message": {"role": "assistant", "content": "<html>cut"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        }
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_server():
    FakeVLLM.requests = []
    server = HTTPServer(("127.0.0.1", 0), FakeVLLM)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def test_request_matches_what_vllm_expects(fake_server, image):
    backend = OpenAICompatibleBackend(
        "Qwen/Qwen3.5-9B", base_url=fake_server, max_tokens=500,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    messages = [{"role": "user", "content": [{"type": "image", "path": str(image)}]}]
    generation = backend.generate(messages, temperature=0.2, seed=3)

    path, body = FakeVLLM.requests[0]
    assert path == "/v1/chat/completions"
    assert body["model"] == "Qwen/Qwen3.5-9B"
    assert (body["temperature"], body["seed"], body["max_tokens"]) == (0.2, 3, 500)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}  # sent at the top level
    assert body["messages"][0]["content"][0]["type"] == "image_url"

    assert generation.text == "<html>cut"
    assert generation.usage() == {"input_tokens": 120, "output_tokens": 30}
    assert generation.finish_reason == "length"
    assert generation.latency_s >= 0


def test_provider_quirks_change_the_request(fake_server):
    # GPT-5.5: max_completion_tokens, default temperature. Gemini: no seed.
    backend = OpenAICompatibleBackend(
        "m", base_url=fake_server, max_tokens=500,
        max_tokens_param="max_completion_tokens", send_seed=False,
    )
    backend.generate([{"role": "user", "content": "hi"}], temperature=None, seed=3)
    body = FakeVLLM.requests[0][1]
    assert body["max_completion_tokens"] == 500
    assert not {"max_tokens", "temperature", "seed"} & body.keys()
    assert backend.sends_seed is False


@pytest.mark.parametrize(
    "path, backend_class, temperature",
    [
        ("configs/models/gpt5_5.yaml", "OpenAICompatibleBackend", None),
        ("configs/models/gemini3_1_pro.yaml", "OpenAICompatibleBackend", 0.2),
        ("configs/models/claude_opus5_5.yaml", "AnthropicBackend", None),
    ],
)
def test_frontier_configs_load(monkeypatch, path, backend_class, temperature):
    from infographics.backends.factory import temperature_for

    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "test")
    config = load_model_config(path)
    assert type(make_backend(config)).__name__ == backend_class
    assert temperature_for(config, 0.2) == temperature


def test_claude_messages_split_out_the_system_prompt(image):
    from infographics.backends.anthropic_backend import to_anthropic

    system, messages = to_anthropic([
        {"role": "system", "content": "rules"},
        {"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image", "path": str(image)}]},
    ])
    assert system == "rules"
    assert [m["role"] for m in messages] == ["user"]
    image_block = messages[0]["content"][1]
    assert image_block["source"]["media_type"] == "image/png"
    assert image_block["source"]["type"] == "base64"
