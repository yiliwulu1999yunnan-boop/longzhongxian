"""Tests for c2_scorer.profile_loader."""

from pathlib import Path

import pytest
import yaml

from c2_scorer.profile_loader import (
    JobProfile,
    ProfileLoadError,
    load_all_profiles,
    load_profile,
)

# 真实配置目录
_REAL_PROFILES_DIR = Path(__file__).resolve().parents[2] / "config" / "job_profiles"

# 所有真实岗位 ID（跳过 _schema.yaml）
_ALL_POSITION_IDS = sorted(
    f.stem
    for f in _REAL_PROFILES_DIR.glob("*.yaml")
    if not f.name.startswith("_")
)


# ───────── 加载真实 YAML 文件 ─────────


@pytest.mark.parametrize("position_id", _ALL_POSITION_IDS)
def test_load_real_profile(position_id: str) -> None:
    """每个 YAML 都能成功加载为 JobProfile."""
    profile = load_profile(position_id, _REAL_PROFILES_DIR)
    assert isinstance(profile, JobProfile)
    assert profile.position_id == position_id
    assert profile.position_name
    assert profile.position_category in ("基层岗位", "管理储备岗位")


@pytest.mark.parametrize("position_id", _ALL_POSITION_IDS)
def test_config_version_is_stable(position_id: str) -> None:
    """config_version 两次加载结果一致."""
    p1 = load_profile(position_id, _REAL_PROFILES_DIR)
    p2 = load_profile(position_id, _REAL_PROFILES_DIR)
    assert p1.config_version == p2.config_version
    assert position_id in p1.config_version


def test_load_all_profiles() -> None:
    """load_all_profiles 返回所有岗位，数量与文件数一致."""
    profiles = load_all_profiles(_REAL_PROFILES_DIR)
    assert len(profiles) == len(_ALL_POSITION_IDS)
    for pid, profile in profiles.items():
        assert pid == profile.position_id


# ───────── 字段校验 ─────────


@pytest.mark.parametrize("position_id", _ALL_POSITION_IDS)
def test_hard_rules_structure(position_id: str) -> None:
    """硬规则字段完整性."""
    profile = load_profile(position_id, _REAL_PROFILES_DIR)
    hr = profile.hard_rules
    assert hr.age_range.min < hr.age_range.max
    assert hr.salary_range.probation_min <= hr.salary_range.probation_max
    assert hr.salary_range.regular_min <= hr.salary_range.regular_max


@pytest.mark.parametrize("position_id", _ALL_POSITION_IDS)
def test_llm_dimensions_weights_positive(position_id: str) -> None:
    """LLM 评估维度权重均为正数，总和为 100."""
    profile = load_profile(position_id, _REAL_PROFILES_DIR)
    total = 0
    for dim in profile.llm_evaluation.dimensions:
        assert dim.weight > 0, f"{dim.name} weight should be positive"
        total += dim.weight
    assert total == 100, f"{position_id} 维度权重总和应为 100，实际 {total}"


@pytest.mark.parametrize("position_id", _ALL_POSITION_IDS)
def test_greeting_template_within_limit(position_id: str) -> None:
    """打招呼模板 ≤150 字."""
    profile = load_profile(position_id, _REAL_PROFILES_DIR)
    assert len(profile.greeting_template) <= 150


@pytest.mark.parametrize("position_id", _ALL_POSITION_IDS)
def test_prompt_template_has_placeholders(position_id: str) -> None:
    """prompt_template 包含必要的占位符."""
    profile = load_profile(position_id, _REAL_PROFILES_DIR)
    tmpl = profile.llm_evaluation.prompt_template
    assert "{position_name}" in tmpl
    assert "{hard_rules_summary}" in tmpl
    assert "{dimensions_detail}" in tmpl


# ───────── 错误处理 ─────────


def test_load_nonexistent_position() -> None:
    """不存在的岗位 ID 抛出 ProfileLoadError."""
    with pytest.raises(ProfileLoadError, match="不存在"):
        load_profile("nonexistent_position_xyz", _REAL_PROFILES_DIR)


def test_load_invalid_yaml(tmp_path: Path) -> None:
    """YAML 格式错误时抛出 ProfileLoadError."""
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("key: [unclosed\n  - broken:", encoding="utf-8")
    with pytest.raises(ProfileLoadError, match="YAML 解析失败"):
        load_profile("bad", tmp_path)


def test_load_yaml_not_dict(tmp_path: Path) -> None:
    """YAML 顶层非字典时抛出 ProfileLoadError."""
    bad_file = tmp_path / "list_top.yaml"
    bad_file.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ProfileLoadError, match="顶层应为字典"):
        load_profile("list_top", tmp_path)


def test_load_yaml_missing_required_fields(tmp_path: Path) -> None:
    """缺少必填字段时抛出 ProfileLoadError."""
    incomplete = tmp_path / "incomplete.yaml"
    yaml.dump({"position_id": "incomplete"}, open(incomplete, "w"))
    with pytest.raises(ProfileLoadError, match="配置校验失败"):
        load_profile("incomplete", tmp_path)


def test_load_all_profiles_nonexistent_dir(tmp_path: Path) -> None:
    """配置目录不存在时抛出 ProfileLoadError."""
    with pytest.raises(ProfileLoadError, match="目录不存在"):
        load_all_profiles(tmp_path / "no_such_dir")
