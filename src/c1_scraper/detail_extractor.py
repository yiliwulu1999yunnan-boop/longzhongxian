"""候选人详情提取 — 优先从 /wapi/ JSON 解析，DOM 兜底."""

from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class WorkExperience:
    """工作经历."""

    company: str = ""
    position_name: str = ""
    work_time: str = ""
    start_date: str = ""
    end_date: str = ""
    responsibility: str = ""
    is_current: bool = False


@dataclass(frozen=True)
class Education:
    """教育经历."""

    school: str = ""
    major: str = ""
    degree_name: str = ""
    start_date: str = ""
    end_date: str = ""


@dataclass(frozen=True)
class CandidateDetail:
    """候选人完整详情."""

    encrypt_geek_id: str
    geek_name: str
    gender: str = ""
    age: str = ""
    work_years: str = ""
    degree: str = ""
    city_name: str = ""
    salary: str = ""
    expect_position: str = ""
    apply_status: str = ""
    self_desc: str = ""
    detail_url: str = ""
    work_experiences: tuple[WorkExperience, ...] = ()
    educations: tuple[Education, ...] = ()
    raw_json: dict[str, Any] = field(default_factory=dict)


def parse_candidate_detail(item: dict[str, Any]) -> CandidateDetail | None:
    """从推荐列表 geek item JSON 解析候选人完整详情.

    geek item 包含 geekCard、showWorks、showEdus 等完整信息，
    无需额外请求详情接口。
    """
    encrypt_geek_id = item.get("encryptGeekId")
    if not encrypt_geek_id:
        logger.warning("detail_missing_geek_id")
        return None

    card = item.get("geekCard") or {}
    geek_name = card.get("geekName") or item.get("geekName", "")
    if not geek_name:
        logger.warning("detail_missing_geek_name", geek_id=encrypt_geek_id)
        return None

    # 性别：0=女, 1=男
    raw_gender = card.get("geekGender")
    gender = _parse_gender(raw_gender)

    # 自我描述
    geek_desc = card.get("geekDesc") or {}
    self_desc = geek_desc.get("content", "") if isinstance(geek_desc, dict) else ""

    # 工作经历
    work_experiences = _parse_work_experiences(item.get("showWorks"))

    # 教育经历
    educations = _parse_educations(item.get("showEdus"))

    return CandidateDetail(
        encrypt_geek_id=encrypt_geek_id,
        geek_name=geek_name,
        gender=gender,
        age=card.get("ageDesc", ""),
        work_years=card.get("geekWorkYear", ""),
        degree=card.get("geekDegree", ""),
        city_name=card.get("expectLocationName", ""),
        salary=card.get("salary", ""),
        expect_position=card.get("expectPositionName", ""),
        apply_status=card.get("applyStatusDesc", ""),
        self_desc=self_desc,
        detail_url=item.get("detailUrl", ""),
        work_experiences=tuple(work_experiences),
        educations=tuple(educations),
        raw_json=item,
    )


def _parse_gender(raw: Any) -> str:
    """解析性别字段."""
    if raw == 0:
        return "女"
    if raw == 1:
        return "男"
    return ""


def _parse_work_experiences(works: Any) -> list[WorkExperience]:
    """解析工作经历列表."""
    if not isinstance(works, list):
        return []
    result: list[WorkExperience] = []
    for w in works:
        if not isinstance(w, dict):
            continue
        result.append(
            WorkExperience(
                company=w.get("company", ""),
                position_name=w.get("positionName", ""),
                work_time=w.get("workTime", ""),
                start_date=w.get("startDate", ""),
                end_date=w.get("endDate", ""),
                responsibility=w.get("responsibility", ""),
                is_current=bool(w.get("current", False)),
            )
        )
    return result


def _parse_educations(edus: Any) -> list[Education]:
    """解析教育经历列表."""
    if not isinstance(edus, list):
        return []
    result: list[Education] = []
    for e in edus:
        if not isinstance(e, dict):
            continue
        result.append(
            Education(
                school=e.get("school", ""),
                major=e.get("major", ""),
                degree_name=e.get("degreeName", ""),
                start_date=e.get("startDate", ""),
                end_date=e.get("endDate", ""),
            )
        )
    return result


async def extract_detail_from_dom(page: Page) -> CandidateDetail | None:
    """DOM 兜底：从详情面板 iframe 提取候选人信息.

    当 /wapi/ 接口拦截失败时使用。
    详情面板在 iframe /web/frame/c-resume/ 内。
    """
    try:
        # 等待详情面板 iframe 加载
        frame = None
        for f in page.frames:
            if "c-resume" in (f.url or ""):
                frame = f
                break

        if frame is None:
            logger.warning("detail_dom_no_iframe")
            return None

        await frame.wait_for_selector(".geek-card-small", timeout=5000)

        # 提取基本信息
        name_el = await frame.query_selector(".geek-card-small .name")
        geek_name = (await name_el.inner_text()).strip() if name_el else ""

        info_el = await frame.query_selector(".geek-card-small .info")
        info_text = (await info_el.inner_text()).strip() if info_el else ""

        # 提取自我描述
        desc_el = await frame.query_selector(".geek-desc .text")
        self_desc = (await desc_el.inner_text()).strip() if desc_el else ""

        if not geek_name:
            logger.warning("detail_dom_no_name")
            return None

        return CandidateDetail(
            encrypt_geek_id="",  # DOM 方式无法直接获取
            geek_name=geek_name,
            self_desc=self_desc,
            raw_json={"_source": "dom", "_info": info_text},
        )
    except Exception:
        logger.warning("detail_dom_extract_failed", exc_info=True)
        return None
