"""推荐列表解析单元测试 — 测试 parse_recommend_response 纯函数."""

import json
from pathlib import Path
from typing import Any

import pytest

from src.c1_scraper.models import RecommendCandidate
from src.c1_scraper.recommend_scraper import parse_recommend_response

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "wapi_recommend_response.json"


@pytest.fixture()
def fixture_data() -> dict[str, Any]:
    """加载 fixture JSON."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_parse_full_candidate_list(fixture_data: dict[str, Any]) -> None:
    """验证能正确解析 fixture JSON 中的候选人列表."""
    candidates = parse_recommend_response(fixture_data)
    # fixture 中有 3 个候选人，但第 3 个缺少 detailUrl/geekCard（最小数据，仍有 id+name）
    assert len(candidates) == 3
    assert all(isinstance(c, RecommendCandidate) for c in candidates)


def test_encrypt_geek_id_extracted(fixture_data: dict[str, Any]) -> None:
    """验证 encryptGeekId 正确提取."""
    candidates = parse_recommend_response(fixture_data)
    ids = [c.encrypt_geek_id for c in candidates]
    assert "abc123def456" in ids
    assert "xyz789ghi012" in ids
    assert "min000basic01" in ids


def test_detail_url_extracted(fixture_data: dict[str, Any]) -> None:
    """验证详情页 URL 正确提取."""
    candidates = parse_recommend_response(fixture_data)
    by_id = {c.encrypt_geek_id: c for c in candidates}

    full = by_id["abc123def456"]
    assert "encryptGeekId=abc123def456" in full.detail_url
    assert full.detail_url.startswith("/web/frame/c-resume/")

    minimal = by_id["min000basic01"]
    assert minimal.detail_url == ""


def test_geek_card_fields_extracted(fixture_data: dict[str, Any]) -> None:
    """验证 geekCard 中的字段正确提取."""
    candidates = parse_recommend_response(fixture_data)
    by_id = {c.encrypt_geek_id: c for c in candidates}

    full = by_id["abc123def456"]
    assert full.job_name == "面点师"
    assert full.city_name == "昆明"
    assert full.work_years == "3年"
    assert full.age == "28"
    assert full.education == "中专"
    assert full.gender == "1"


def test_missing_card_fields_no_crash(fixture_data: dict[str, Any]) -> None:
    """验证 geekCard 字段缺失时不崩溃，返回空字符串."""
    candidates = parse_recommend_response(fixture_data)
    by_id = {c.encrypt_geek_id: c for c in candidates}

    partial = by_id["xyz789ghi012"]
    assert partial.job_name == "收银员"
    assert partial.city_name == "大理"
    # 缺失字段返回空字符串
    assert partial.work_years == ""
    assert partial.age == ""
    assert partial.education == ""

    minimal = by_id["min000basic01"]
    assert minimal.job_name == ""
    assert minimal.city_name == ""


def test_missing_required_fields_skipped() -> None:
    """验证缺少 encryptGeekId 或 geekName 时跳过该候选人."""
    data: dict[str, Any] = {
        "code": 0,
        "message": "Success",
        "zpData": {
            "geekList": [
                {"geekName": "无ID的人"},
                {"encryptGeekId": "has_id_no_name"},
                {"encryptGeekId": "valid_id", "geekName": "有效"},
            ]
        },
    }
    candidates = parse_recommend_response(data)
    assert len(candidates) == 1
    assert candidates[0].encrypt_geek_id == "valid_id"


def test_empty_response() -> None:
    """验证空响应不崩溃."""
    assert parse_recommend_response({}) == []
    assert parse_recommend_response({"code": 0}) == []
    assert parse_recommend_response({"zpData": "not_a_dict"}) == []
    assert parse_recommend_response({"zpData": {}}) == []


def test_raw_json_preserved(fixture_data: dict[str, Any]) -> None:
    """验证原始 JSON 保留在 raw_json 字段."""
    candidates = parse_recommend_response(fixture_data)
    first = candidates[0]
    assert first.raw_json["encryptGeekId"] == "abc123def456"
    assert "geekCard" in first.raw_json
