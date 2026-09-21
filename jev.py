#!/usr/bin/env python3
"""输入文本和是非问题，通过 Jev 获取“是”的概率（仅使用标准库）。"""

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class QuestionError(ValueError):
    """本地输入校验失败；消息仅包含固定说明。"""


class AnswerError(ValueError):
    """远端回答与请求类型或数值范围不符。"""


def build_question(question, kind="noul", criteria=None):
    if not isinstance(question, str) or not question.strip():
        raise QuestionError("请填写判断问题。")
    if kind not in ("noul", "choice", "score"):
        raise QuestionError("请选择 Noul、Choice 或 Score。")
    result = {"type": kind, "instructions": question}
    if kind == "choice":
        if not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255:
            raise QuestionError("Choice 需要 2–255 个选项。")
        clean = {}
        for name, description in criteria.items():
            if not isinstance(name, str) or not name.strip() or name.strip() in clean:
                raise QuestionError("选项名称不能为空或重复。")
            if description is not None and not isinstance(description, str):
                raise QuestionError("选项说明必须是文本。")
            clean[name.strip()] = description.strip() or None if description is not None else None
        result["criteria"] = clean
    elif kind == "score":
        if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
            raise QuestionError("Score 需要按从低到高的顺序填写 2–10 个等级。")
        if any(not isinstance(level, str) or not level.strip() for level in criteria):
            raise QuestionError("每个等级都需要文字说明。")
        clean = [level.strip() for level in criteria]
        if len(set(clean)) != len(clean):
            raise QuestionError("等级说明不能重复。")
        result["criteria"] = clean
    return result


def valid_number(value, low=0, high=1):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def read_answer(result, question):
    """只返回已校验的字段，不透传任意服务端内容。"""
    try:
        answer = result["answers"]["judgment"]
        kind = question["type"]
        if answer["type"] != kind:
            raise ValueError()
        if kind == "noul":
            if not valid_number(answer["noul"]):
                raise ValueError()
            return {"type": kind, "noul": answer["noul"]}
        keys = list(question["criteria"]) if kind == "choice" else [str(i) for i in range(len(question["criteria"]))]
        probabilities = answer["probabilities"]
        if (not isinstance(probabilities, dict) or set(probabilities) != set(keys)
                or any(not valid_number(p) for p in probabilities.values())
                or not math.isclose(sum(probabilities.values()), 1, abs_tol=0.02)
                or not valid_number(answer["confidence"])):
            raise ValueError()
        output = {"type": kind, "probabilities": {k: probabilities[k] for k in keys}, "confidence": answer["confidence"]}
        if kind == "choice":
            if not isinstance(answer["choice"], str) or answer["choice"] not in keys:
                raise ValueError()
            output["choice"] = answer["choice"]
        else:
            if not valid_number(answer["score"], 0, len(keys) - 1):
                raise ValueError()
            if not isinstance(answer["legend"], dict) or set(answer["legend"]) != set(keys):
                raise ValueError()
            output["score"] = answer["score"]
            # 显示用户实际提交的等级，避免远端描述变化造成误读。
            output["legend"] = dict(zip(keys, question["criteria"]))
        return output
    except (ValueError, KeyError, TypeError):
        raise AnswerError("Jev 返回的判断结果格式无效，请重试。") from None


def evaluate(text, question, api_key, kind="noul", criteria=None):
    typed_question = build_question(question, kind, criteria)
    payload = {
        "model": "jev-latest",
        "state": text,
        "questions": {"judgment": typed_question},
    }
    request = urllib.request.Request(
        "https://api.typesafe.ai/v1/systemone",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # 不跟随重定向，不输出请求头、原始响应或异常详情。
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=60) as response:
        try:
            result = json.load(response)
        except ValueError:
            raise AnswerError("Jev 返回的判断结果格式无效，请重试。") from None
    return read_answer(result, typed_question)


def ask(text, question, api_key):
    return evaluate(text, question, api_key)["noul"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="待判断文本；省略时交互输入")
    parser.add_argument("--question", help="是非问题；省略时交互输入")
    args = parser.parse_args()
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        print("错误：请先设置环境变量 TYPESAFE_API_KEY。", file=sys.stderr)
        return 1
    try:
        text = args.text if args.text is not None else input("请输入文本：")
        question = args.question if args.question is not None else input("请输入是非问题：")
        if not text.strip() or not question.strip():
            print("错误：文本和问题均不能为空。", file=sys.stderr)
            return 1
        probability = ask(text, question, api_key)
    except urllib.error.HTTPError as error:
        hints = {
            401: "API Key 无效或已失效。",
            403: "访问被拒绝，请检查账户权限。",
            422: "请求未通过接口校验。",
            429: "请求过于频繁，请稍后重试。",
            529: "服务繁忙，请稍后重试。",
        }
        print(f"错误：HTTP {error.code}。" + hints.get(error.code, "调用失败，请稍后重试。"), file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError):
        print("错误：网络连接失败或超时，请检查网络后重试。", file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError):
        print("错误：请求或响应格式无效，无法读取判断概率。", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n输入已取消。", file=sys.stderr)
        return 1
    print(f"是的概率：{probability:.2%}（P(是) = {probability:g}）")
    print(f"否的概率：{1 - probability:.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
