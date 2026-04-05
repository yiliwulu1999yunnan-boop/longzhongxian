"""岗位画像配置加载器 — 将 YAML 配置解析为类型安全的 Pydantic model."""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

_DEFAULT_PROFILES_DIR = Path(__file__).resolve().parents[2] / "config" / "job_profiles"


# ───────── Pydantic Models ─────────


class AgeRange(BaseModel):
    min: int
    max: int
    flexible_max: Optional[int] = None


class SalaryRange(BaseModel):
    probation_min: int
    probation_max: int
    regular_min: int
    regular_max: int


class HardRules(BaseModel):
    age_range: AgeRange
    education_min: str
    salary_range: SalaryRange
    experience_required: bool
    experience_min_years: Optional[float] = None
    accept_early_morning: bool
    accept_store_transfer: Optional[bool] = None


class IndustryKeywords(BaseModel):
    whitelist: list[str]
    blacklist: list[str]


class EvaluationDimension(BaseModel):
    name: str
    weight: int
    description: str
    required_for: Optional[list[str]] = None


class LlmEvaluation(BaseModel):
    dimensions: list[EvaluationDimension]
    passing_score: int
    prompt_template: str


class JobProfile(BaseModel):
    """岗位画像完整配置."""

    position_id: str
    position_name: str
    position_category: str = Field(pattern=r"^(基层岗位|管理储备岗位)$")
    hard_rules: HardRules
    industry_keywords: IndustryKeywords
    red_flags: list[str]
    llm_evaluation: LlmEvaluation
    greeting_template: str

    @field_validator("greeting_template")
    @classmethod
    def _greeting_max_length(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) > 150:
            raise ValueError(
                f"greeting_template 超过 150 字限制（当前 {len(stripped)} 字）"
            )
        return stripped

    @property
    def config_version(self) -> str:
        """配置版本标识：position_id + 维度权重指纹，供快照记录."""
        weights = "-".join(
            str(d.weight) for d in self.llm_evaluation.dimensions
        )
        return f"{self.position_id}:{weights}:ps{self.llm_evaluation.passing_score}"


# ───────── Loader ─────────


class ProfileLoadError(Exception):
    """岗位画像配置加载失败."""


def load_profile(
    position_id: str,
    profiles_dir: Path | str = _DEFAULT_PROFILES_DIR,
) -> JobProfile:
    """加载指定岗位的 YAML 配置并返回 JobProfile 对象.

    Args:
        position_id: 岗位标识（与 YAML 文件名一致，不含 .yaml 后缀）.
        profiles_dir: 岗位画像 YAML 所在目录.

    Raises:
        ProfileLoadError: 文件不存在或内容解析失败.
    """
    path = Path(profiles_dir) / f"{position_id}.yaml"
    if not path.exists():
        raise ProfileLoadError(f"岗位配置文件不存在: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileLoadError(f"YAML 解析失败 ({path}): {exc}") from exc

    if not isinstance(raw, dict):
        raise ProfileLoadError(f"YAML 顶层应为字典，实际为 {type(raw).__name__}")

    try:
        return JobProfile(**raw)
    except Exception as exc:
        raise ProfileLoadError(
            f"配置校验失败 ({position_id}): {exc}"
        ) from exc


def load_all_profiles(
    profiles_dir: Path | str = _DEFAULT_PROFILES_DIR,
) -> dict[str, JobProfile]:
    """加载目录下所有岗位画像配置（跳过 _schema.yaml）."""
    profiles_dir = Path(profiles_dir)
    if not profiles_dir.is_dir():
        raise ProfileLoadError(f"岗位配置目录不存在: {profiles_dir}")

    result: dict[str, JobProfile] = {}
    for yaml_file in sorted(profiles_dir.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        position_id = yaml_file.stem
        result[position_id] = load_profile(position_id, profiles_dir)
    return result
