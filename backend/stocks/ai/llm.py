"""LLM 客户端：统一走 OpenAI 兼容 /chat/completions 协议。"""
import json

import requests
from django.conf import settings

from .crypto import decrypt_api_key


class LlmError(Exception):
    """LLM 调用失败（网络/上游/配置）——上层如实报错，绝不伪造结果"""


class LlmClient:
    def __init__(self, provider):
        self.provider = provider
        self.base_url = provider.base_url.rstrip('/')
        self.api_key = decrypt_api_key(provider.api_key_encrypted)

    def chat(self, messages, temperature=0.3, max_tokens=2000, timeout=None):
        """返回 (文本, usage dict)。失败抛 LlmError。"""
        timeout = timeout or int(
            getattr(settings, 'STOCKTRACE_LLM_TIMEOUT', 60)
        )
        try:
            resp = requests.post(
                f'{self.base_url}/chat/completions',
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': self.provider.model,
                    'messages': messages,
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                },
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise LlmError(f'LLM 请求失败：{exc}') from exc

        if resp.status_code != 200:
            raise LlmError(f'LLM 上游返回 {resp.status_code}：{resp.text[:300]}')

        try:
            data = resp.json()
            text = data['choices'][0]['message']['content']
        except (ValueError, KeyError, IndexError) as exc:
            raise LlmError(f'LLM 响应格式异常：{resp.text[:300]}') from exc

        usage = data.get('usage') or {}
        return text, {
            'prompt_tokens': usage.get('prompt_tokens'),
            'completion_tokens': usage.get('completion_tokens'),
        }

    def chat_json(self, messages, temperature=0.0, max_tokens=2000):
        """要求严格 JSON 输出并解析；解析失败抛 LlmError，不猜不修。"""
        text, usage = self.chat(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        try:
            return json.loads(_strip_code_fence(text)), usage
        except ValueError as exc:
            raise LlmError(f'LLM 未返回合法 JSON：{text[:300]}') from exc


def _strip_code_fence(text):
    text = text.strip()
    if text.startswith('```'):
        first_newline = text.find('\n')
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.endswith('```'):
            text = text[:-3]
    return text.strip()
