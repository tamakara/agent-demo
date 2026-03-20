"""OpenAI 兼容网关地址规范化工具。

设计目的：
1. 统一处理用户配置中的 ``base_url``，避免各调用点重复清洗逻辑。
2. 兼容用户误填完整 endpoint（例如带 ``/chat/completions``）的情况。
3. 在配置为空时提供受控默认值，防止 SDK 因空地址直接报错。
"""

from __future__ import annotations


OPENAI_DEFAULT_BASE_URL = "http://model-gateway.test.api.dotai.internal/v1"
OPENAI_SUFFIX_CHAT_COMPLETIONS = "/chat/completions"


def normalize_openai_base_url(base_url: str | None) -> str:
    """规范化 OpenAI 兼容基础地址。

    处理规则：
    - ``None`` 或空白字符串：回落到 ``OPENAI_DEFAULT_BASE_URL``。
    - 去掉末尾多余斜杠。
    - 若地址以 ``/chat/completions`` 结尾，自动裁剪回基础 URL。
    - 规范化后为空时，仍回落到默认值。
    """
    actual_base_url = (base_url or OPENAI_DEFAULT_BASE_URL).strip()
    if not actual_base_url:
        actual_base_url = OPENAI_DEFAULT_BASE_URL

    actual_base_url = actual_base_url.rstrip("/")
    if actual_base_url.endswith(OPENAI_SUFFIX_CHAT_COMPLETIONS):
        actual_base_url = actual_base_url[: -len(OPENAI_SUFFIX_CHAT_COMPLETIONS)]
    actual_base_url = actual_base_url.rstrip("/")
    if not actual_base_url:
        return OPENAI_DEFAULT_BASE_URL
    return actual_base_url
