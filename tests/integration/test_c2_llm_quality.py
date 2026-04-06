"""C2 LLM 质量评估 — 用真实 DeepSeek API 验证评分准确率.

运行方式：
    pytest tests/integration/test_c2_llm_quality.py -v -s --run-llm

需要环境变量：
    DEEPSEEK_API_KEY: DeepSeek API 密钥
    DEEPSEEK_BASE_URL: (可选) API 地址，默认 https://api.deepseek.com

准确率目标：≥80%（12 个需 LLM 评估的样本中至少 10 个正确）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.c2_scorer.hard_rules import CandidateInfo, evaluate_hard_rules
from src.c2_scorer.llm_scorer import LlmScorer
from src.c2_scorer.profile_loader import load_profile
from src.c2_scorer.score_merger import merge_scores
from src.common.logger import get_logger

logger = get_logger(__name__)

_PROFILES_DIR = Path(__file__).resolve().parents[2] / "config" / "job_profiles"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# 需要 --run-llm 参数才会执行
pytestmark = pytest.mark.skipif(
    "not config.getoption('--run-llm', default=False)",
)


def _load_samples() -> list[dict]:
    return json.loads((_FIXTURES_DIR / "sample_candidates.json").read_text("utf-8"))


def _get_llm_samples() -> list[dict]:
    """筛选出硬规则通过、需要 LLM 评估的样本."""
    samples = _load_samples()
    result = []
    for s in samples:
        profile = load_profile(s["position_id"], _PROFILES_DIR)
        info = CandidateInfo(**s["candidate_info"])
        hard_v = evaluate_hard_rules(info, profile)
        if hard_v.passed:
            result.append(s)
    return result


async def _evaluate_single(
    scorer: LlmScorer,
    sample: dict,
) -> dict:
    """对单个样本执行 LLM 评估并返回结果."""
    profile = load_profile(sample["position_id"], _PROFILES_DIR)
    info = CandidateInfo(**sample["candidate_info"])
    hard_verdict = evaluate_hard_rules(info, profile)

    llm_result = await scorer.evaluate(profile, sample["candidate_text"])

    merged = merge_scores(
        hard_verdict, llm_result, profile.llm_evaluation.passing_score
    )

    return {
        "id": sample["id"],
        "position_id": sample["position_id"],
        "expected": sample["label"],
        "actual": merged.final_verdict,
        "llm_score": llm_result.weighted_total,
        "llm_error": llm_result.error,
        "passing_score": profile.llm_evaluation.passing_score,
        "recommend_threshold": profile.llm_evaluation.passing_score * 1.33,
        "correct": merged.final_verdict == sample["label"],
    }


@pytest.mark.asyncio
async def test_llm_accuracy() -> None:
    """真实 API 评估准确率，目标 ≥80%."""
    scorer = LlmScorer()
    samples = _get_llm_samples()

    assert len(samples) > 0, "没有需要 LLM 评估的样本"

    # 串行调用避免触发 rate limit
    results = []
    for sample in samples:
        r = await _evaluate_single(scorer, sample)
        results.append(r)
        status = "✓" if r["correct"] else "✗"
        logger.info(
            "llm_eval_result",
            sample_id=r["id"],
            expected=r["expected"],
            actual=r["actual"],
            llm_score=r["llm_score"],
            correct=r["correct"],
        )
        print(
            f"  {status} {r['id']} ({r['position_id']}): "
            f"期望={r['expected']}, 实际={r['actual']}, "
            f"LLM分={r['llm_score']:.1f} "
            f"(及格={r['passing_score']}, 推荐={r['recommend_threshold']:.0f})"
        )

    correct_count = sum(1 for r in results if r["correct"])
    total = len(results)
    accuracy = correct_count / total

    # 打印汇总
    print(f"\n{'='*60}")
    print(f"准确率: {correct_count}/{total} = {accuracy:.0%}")
    print("目标: ≥80%")
    print(f"{'='*60}")

    # 打印错误详情
    wrong = [r for r in results if not r["correct"]]
    if wrong:
        print("\n错误样本:")
        for r in wrong:
            print(
                f"  {r['id']}: 期望={r['expected']}, 实际={r['actual']}, "
                f"LLM分={r['llm_score']:.1f}"
            )

    assert accuracy >= 0.8, (
        f"LLM 准确率 {accuracy:.0%} ({correct_count}/{total}) 未达 80% 目标"
    )
