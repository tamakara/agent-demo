"""兼容入口：转发到 ``infra.llm``。"""

from infra.llm.openai_gateway import OpenAIGateway

__all__ = ["OpenAIGateway"]

