#!/usr/bin/env python3
"""
Qwen3.5-35B 关闭思考模式测试 Demo

当前项目在 AlayaFlow 中注册了 Qwen3 Chat（model_id: qwen3-chat），
base_url 指向 qwen35 服务（Qwen3.5-35B）。该模型默认开启思考模式，会先输出
<reasoning>...</reasoning> 再输出正文，导致延迟大。

本脚本用 OpenAI 兼容接口直接请求同一服务，通过请求体中的
chat_template_kwargs.enable_thinking=false 关闭思考模式（vLLM 部署时适用）。

使用前请确保 .env 中配置：
  QWEN_BASE_URL=http://star.sustech.edu.cn/service/model/qwen35/v1
  QWEN_API_KEY=你的密钥（若服务不需要可填 placeholder）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 保证可导入项目模块
_repo_root = Path(__file__).resolve().parents[1]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def load_dotenv(env_file: Path | None = None) -> None:
    path = env_file or _repo_root / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _run_with_requests(
    base_url: str, api_key: str, model_name: str, enable_thinking: bool
) -> dict:
    """用 requests 直接发 POST，chat_template_kwargs 传入请求体。返回完整 choices[0] 便于看 reasoning。"""
    import requests
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "用一句话介绍南科大。"}],
        "max_tokens": 2560,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "placeholder":
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices", [])
    return data if not choices else choices[0]


def _run_with_openai(
    base_url: str, api_key: str, model_name: str, enable_thinking: bool
) -> dict:
    """用 OpenAI 客户端（若支持 extra_body）。返回便于解析的 dict。"""
    from openai import OpenAI
    client = OpenAI(base_url=base_url.rstrip("/") + "/", api_key=api_key)
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": "用一句话介绍南科大。"}],
        max_tokens=256,
        extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
    )
    msg = response.choices[0].message
    return {
        "message": {
            "content": getattr(msg, "content", None) or "",
            "reasoning_content": getattr(msg, "reasoning_content", None),
        }
    }


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Qwen3.5 思考模式开关测试")
    p.add_argument(
        "--thinking",
        action="store_true",
        help="开启思考模式（默认关闭）",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="打印完整响应 JSON（便于确认服务端是否返回 reasoning 等）",
    )
    args = p.parse_args()

    load_dotenv()
    base_url = os.getenv("QWEN_BASE_URL", "http://star.sustech.edu.cn/service/model/qwen35/v1")
    api_key = os.getenv("QWEN_API_KEY") or "placeholder"
    model_name = "qwen3"
    enable_thinking = args.thinking

    print("调用 Qwen 服务")
    print("  base_url:", base_url)
    print("  chat_template_kwargs.enable_thinking:", enable_thinking)
    print()

    try:
        result = _run_with_requests(base_url, api_key, model_name, enable_thinking)
    except ImportError:
        try:
            result = _run_with_openai(base_url, api_key, model_name, enable_thinking)
        except Exception as e:
            print("requests 未安装，且 openai 调用失败:", e)
            print("请安装: pip install requests")
            sys.exit(1)
    except Exception as e:
        print("请求失败:", e)
        raise

    # 兼容两种返回结构：requests 路径返回 choice 对象（含 message），openai 路径返回 { message }
    if "message" in result:
        msg = result["message"]
    else:
        msg = result.get("message", result)
    if isinstance(msg, dict):
        content = (msg.get("content") or "").strip()
        reasoning = msg.get("reasoning_content")
    else:
        content = (getattr(msg, "content", None) or "").strip()
        reasoning = getattr(msg, "reasoning_content", None)

    if reasoning:
        print("思考内容 (reasoning_content):")
        print(reasoning)
        print()
    print("回复 (content):")
    print(content)
    print()

    if args.debug:
        import json
        print("完整响应:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if enable_thinking:
        print("当前为开启思考模式；若上面没有思考内容，可能是服务端未返回 reasoning 或放在 content 内（如 <reasoning>...）。")
    else:
        print("当前为关闭思考模式；若回复中无 <reasoning> 或大段思考，则生效。")


if __name__ == "__main__":
    main()
