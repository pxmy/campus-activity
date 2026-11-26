"""智能功能评测脚本（单元 9）：读取 data/eval/ 独立数据，输出指标与错误样例。

不纳入 pytest 自动运行（需调用模型并产生费用）。单独执行：python tests/eval_smarts.py
评测期间不得根据评测数据修改提示词或参数；如需修改，记为新版本并完整重评。
"""
import json
from pathlib import Path

from services.db import get_conn
from services.feedback import classify_one, TOPICS
from services.llm import is_configured
from services.ml import evaluate
from services.qa import answer, build_index
from services.media import extract_todos
import pandas as pd

EVAL_DIR = Path("data/eval")
OUT = Path("outputs/eval_result.json")


def eval_classification():
    """反馈主题分类：准确率、各主题查准率与查全率。"""
    p = EVAL_DIR / "feedback_eval.json"
    if not p.exists() or not is_configured():
        return {"skipped": "缺少评测数据或未配置密钥"}
    data = json.loads(p.read_text(encoding="utf-8"))
    correct, total = 0, 0
    errors = []
    for item in data:
        try:
            got = classify_one(item["content"])
            pred = set(got["topics"])
            gold = set(item["topics"])
            correct += int(pred == gold)
            if pred != gold:
                errors.append({"content": item["content"], "pred": sorted(pred),
                               "gold": sorted(gold)})
        except Exception as e:
            errors.append({"content": item["content"], "error": str(e)})
        total += 1
    return {"accuracy": correct / total if total else None, "total": total,
            "errors": errors[:20]}


def eval_qa():
    """知识问答：回答正确率、来源正确率、拒答正确率。"""
    p = EVAL_DIR / "qa_eval.json"
    if not p.exists() or not is_configured():
        return {"skipped": "缺少评测数据或未配置密钥"}
    data = json.loads(p.read_text(encoding="utf-8"))
    idx, chunks = build_index("data/docs")
    correct, refused, total = 0, 0, 0
    errors = []
    for item in data:
        res = answer(item["question"], idx, chunks)
        covered = item["covered"]
        if not covered:
            refused += int(res["answered"] is False)
        else:
            correct += int(res["answered"] is True and
                           item["answer_keyword"] in res["text"])
        if not (res["answered"] == covered):
            errors.append({"q": item["question"], "covered": covered,
                           "answered": res["answered"]})
        total += 1
    return {"answer_accuracy": correct / total if total else None,
            "refuse_rate": refused / max(1, sum(1 for x in data if not x["covered"])),
            "total": total, "errors": errors[:20]}


def eval_signin():
    """签到表提取：字段级准确率。"""
    p = EVAL_DIR / "signin_eval.json"
    if not p.exists() or not is_configured():
        return {"skipped": "缺少评测数据或未配置密钥"}
    data = json.loads(p.read_text(encoding="utf-8"))
    ok, total = 0, 0
    errors = []
    for item in data:
        try:
            got = extract_signin(item["image"])
            for field, gold in item["fields"].items():
                total += 1
                pred = got.get(field)
                ok += int(str(pred) == str(gold))
                if str(pred) != str(gold):
                    errors.append({"image": item["image"], "field": field,
                                   "pred": pred, "gold": gold})
        except Exception as e:
            errors.append({"image": item["image"], "error": str(e)})
    return {"field_accuracy": ok / total if total else None,
            "total_fields": total, "errors": errors[:20]}


def eval_forecast():
    """到场预测：MAE，与单元5结果对比。"""
    p = EVAL_DIR / "history_new.csv"
    if not p.exists():
        return {"skipped": "缺少评测数据"}
    df = pd.read_csv(p)
    res = evaluate(df)
    return {"baseline_mae": res["baseline_mae"],
            "regression_mae": res["regression_mae"]}


def main():
    print("提示词版本、模型名称、是否开启思考模式、评测日期须在评测记录中注明，以便复现。")
    result = {
        "feedback_classification": eval_classification(),
        "qa": eval_qa(),
        "signin_extraction": eval_signin(),
        "forecast": eval_forecast(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n结果已写入：" + str(OUT))
    print("请据此填写 docs/模型评测记录.md，并归纳典型错误、分析原因。")


if __name__ == "__main__":
    main()
