"""候选人详情提取单元测试 — 全部 mock，不访问 Boss 直聘."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from src.c1_scraper.detail_extractor import (
    extract_detail_from_dom,
    parse_candidate_detail,
)


# ── fixture: 完整的 geek item（模拟 /wapi/ geek_list 响应中的单个候选人） ──


def _make_geek_item(**overrides: Any) -> dict[str, Any]:
    """构造一个完整的 geek item JSON."""
    base: dict[str, Any] = {
        "encryptGeekId": "abc123def456",
        "geekCard": {
            "geekName": "张丽",
            "geekGender": 0,
            "geekWorkYear": "6年",
            "geekDegree": "初中及以下",
            "ageDesc": "44岁",
            "expectLocationName": "昆明",
            "salary": "4-5K",
            "expectPositionName": "洗碗工",
            "applyStatusDesc": "在职-月内到岗",
            "geekDesc": {"content": "餐具收纳,卫生清洁"},
        },
        "detailUrl": "/web/frame/c-resume/?encryptGeekId=abc123def456",
        "showWorks": [
            {
                "company": "某餐厅",
                "positionName": "洗碗工",
                "workTime": "1年半",
                "startDate": "2020.06",
                "endDate": "2022.03",
                "responsibility": "负责餐具清洗",
                "current": False,
            },
            {
                "company": "某火锅店",
                "positionName": "服务员",
                "workTime": "2年",
                "startDate": "2022.04",
                "endDate": "",
                "responsibility": "",
                "current": True,
            },
        ],
        "showEdus": [
            {
                "school": "昆明某中学",
                "major": "",
                "degreeName": "初中及以下",
                "startDate": "1989.01",
                "endDate": "1992.01",
            },
        ],
    }
    base.update(overrides)
    return base


class TestParseFullCandidate:
    """测试从完整 JSON 解析候选人详情."""

    def test_basic_fields(self) -> None:
        """验证基本字段正确提取."""
        item = _make_geek_item()
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.encrypt_geek_id == "abc123def456"
        assert detail.geek_name == "张丽"
        assert detail.gender == "女"
        assert detail.age == "44岁"
        assert detail.work_years == "6年"
        assert detail.degree == "初中及以下"
        assert detail.city_name == "昆明"
        assert detail.salary == "4-5K"
        assert detail.expect_position == "洗碗工"
        assert detail.apply_status == "在职-月内到岗"
        assert detail.self_desc == "餐具收纳,卫生清洁"

    def test_detail_url(self) -> None:
        """验证详情页 URL 正确提取."""
        item = _make_geek_item()
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert "encryptGeekId=abc123def456" in detail.detail_url

    def test_work_experiences(self) -> None:
        """验证工作经历正确解析."""
        item = _make_geek_item()
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert len(detail.work_experiences) == 2

        w0 = detail.work_experiences[0]
        assert w0.company == "某餐厅"
        assert w0.position_name == "洗碗工"
        assert w0.work_time == "1年半"
        assert w0.start_date == "2020.06"
        assert w0.end_date == "2022.03"
        assert w0.responsibility == "负责餐具清洗"
        assert w0.is_current is False

        w1 = detail.work_experiences[1]
        assert w1.company == "某火锅店"
        assert w1.is_current is True

    def test_educations(self) -> None:
        """验证教育经历正确解析."""
        item = _make_geek_item()
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert len(detail.educations) == 1

        edu = detail.educations[0]
        assert edu.school == "昆明某中学"
        assert edu.degree_name == "初中及以下"

    def test_raw_json_preserved(self) -> None:
        """验证原始 JSON 保留."""
        item = _make_geek_item()
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.raw_json["encryptGeekId"] == "abc123def456"

    def test_gender_male(self) -> None:
        """验证男性性别解析."""
        item = _make_geek_item()
        item["geekCard"]["geekGender"] = 1
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.gender == "男"

    def test_gender_unknown(self) -> None:
        """验证未知性别处理."""
        item = _make_geek_item()
        item["geekCard"]["geekGender"] = None
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.gender == ""


class TestMissingFields:
    """测试字段缺失时的容错处理."""

    def test_missing_encrypt_geek_id(self) -> None:
        """缺少 encryptGeekId 时返回 None."""
        item = _make_geek_item()
        del item["encryptGeekId"]
        assert parse_candidate_detail(item) is None

    def test_missing_geek_name(self) -> None:
        """缺少 geekName 时返回 None."""
        item = _make_geek_item()
        item["geekCard"]["geekName"] = ""
        # Also remove fallback
        item.pop("geekName", None)
        assert parse_candidate_detail(item) is None

    def test_name_fallback_to_top_level(self) -> None:
        """geekCard 中无 geekName 时从顶层字段回退."""
        item = _make_geek_item()
        del item["geekCard"]["geekName"]
        item["geekName"] = "顶层姓名"
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.geek_name == "顶层姓名"

    def test_no_geek_card(self) -> None:
        """无 geekCard 时仍可从顶层提取姓名."""
        item = {"encryptGeekId": "id1", "geekName": "无卡片"}
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.geek_name == "无卡片"
        assert detail.gender == ""
        assert detail.work_years == ""

    def test_no_work_experiences(self) -> None:
        """无工作经历时返回空元组."""
        item = _make_geek_item()
        del item["showWorks"]
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.work_experiences == ()

    def test_no_educations(self) -> None:
        """无教育经历时返回空元组."""
        item = _make_geek_item()
        del item["showEdus"]
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.educations == ()

    def test_geek_desc_not_dict(self) -> None:
        """geekDesc 不是 dict 时返回空字符串."""
        item = _make_geek_item()
        item["geekCard"]["geekDesc"] = "纯文本"
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert detail.self_desc == ""

    def test_show_works_contains_invalid_items(self) -> None:
        """showWorks 包含非 dict 项时跳过."""
        item = _make_geek_item()
        item["showWorks"] = [{"company": "有效", "positionName": "有效岗位"}, "无效", 123]
        detail = parse_candidate_detail(item)
        assert detail is not None
        assert len(detail.work_experiences) == 1


class TestDomFallback:
    """测试 DOM 兜底提取（全部 mock）."""

    @pytest.mark.asyncio()
    async def test_extract_from_dom_success(self) -> None:
        """DOM 提取成功时返回 CandidateDetail."""
        # 构造 mock frame
        mock_frame = AsyncMock()
        mock_frame.url = "https://www.zhipin.com/web/frame/c-resume/?id=123"

        name_el = AsyncMock()
        name_el.inner_text.return_value = "  王五  "
        info_el = AsyncMock()
        info_el.inner_text.return_value = "28岁 3年经验"
        desc_el = AsyncMock()
        desc_el.inner_text.return_value = "认真负责"

        mock_frame.query_selector = AsyncMock(
            side_effect=lambda sel: {
                ".geek-card-small .name": name_el,
                ".geek-card-small .info": info_el,
                ".geek-desc .text": desc_el,
            }.get(sel)
        )

        # 构造 mock page
        mock_page = MagicMock()
        type(mock_page).frames = PropertyMock(return_value=[mock_frame])

        detail = await extract_detail_from_dom(mock_page)
        assert detail is not None
        assert detail.geek_name == "王五"
        assert detail.self_desc == "认真负责"
        assert detail.raw_json["_source"] == "dom"

    @pytest.mark.asyncio()
    async def test_extract_from_dom_no_iframe(self) -> None:
        """无匹配 iframe 时返回 None."""
        mock_frame = MagicMock()
        mock_frame.url = "https://www.zhipin.com/other"

        mock_page = MagicMock()
        type(mock_page).frames = PropertyMock(return_value=[mock_frame])

        detail = await extract_detail_from_dom(mock_page)
        assert detail is None

    @pytest.mark.asyncio()
    async def test_extract_from_dom_no_name(self) -> None:
        """DOM 中无姓名时返回 None."""
        mock_frame = AsyncMock()
        mock_frame.url = "https://www.zhipin.com/web/frame/c-resume/?id=123"
        mock_frame.query_selector = AsyncMock(return_value=None)

        mock_page = MagicMock()
        type(mock_page).frames = PropertyMock(return_value=[mock_frame])

        detail = await extract_detail_from_dom(mock_page)
        assert detail is None

    @pytest.mark.asyncio()
    async def test_extract_from_dom_exception(self) -> None:
        """DOM 提取异常时返回 None 不崩溃."""
        mock_page = MagicMock()
        type(mock_page).frames = PropertyMock(side_effect=RuntimeError("boom"))

        detail = await extract_detail_from_dom(mock_page)
        assert detail is None
