"""模型调用封装：全项目只在这个文件里创建客户端、读取密钥。

其他模块一律通过本文件提供的函数调用模型。把网络错误、超时、限流、返回内容不合要求
统一成 LLMError，由页面给出“智能功能暂不可用”的提示，不让页面崩溃。
"""
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = os.getenv("LLM_MODEL", "deepseek-flash")


class LLMError(Exception):
    """模型不可用或返回内容不合要求。界面层捕获后给出友好提示。"""


def is_configured():
    """是否已配置密钥（页面据此提示而不尝试调用）。"""
    return bool(os.getenv("DEEPSEEK_API_KEY"))


def get_client():
    """创建模型客户端；未配置密钥时抛 LLMError。"""
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise LLMError("未配置 DEEPSEEK_API_KEY，智能功能暂不可用")
    return OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=60, max_retries=2)


def chat_text(system, user):
    """普通文本对话，返回模型回复字符串。"""
    try:
        resp = get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content
    except LLMError:
        raise
    except Exception as e:
        raise LLMError("模型调用失败：" + type(e).__name__) from e


def chat_json(system, user, required_keys):
    """要求模型返回 JSON 对象，并检查必需的键是否齐全。"""
    try:
        resp = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system + "\n只输出一个 JSON 对象。"},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
    except LLMError:
        raise
    except Exception as e:
        raise LLMError("模型调用失败：" + type(e).__name__) from e
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise LLMError("模型返回缺少字段：" + "、".join(missing))
    return data
