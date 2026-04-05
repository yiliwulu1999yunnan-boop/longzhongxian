"""C1 候选人数据模型."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecommendCandidate:
    """推荐列表中的候选人数据."""

    encrypt_geek_id: str
    geek_name: str
    detail_url: str = ""
    job_name: str = ""
    city_name: str = ""
    work_years: str = ""
    age: str = ""
    education: str = ""
    gender: str = ""
    raw_json: dict[str, Any] = field(default_factory=dict)
