"""SQLAlchemy ORM 模型 — Phase 1 全部数据表."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Candidate(Base):
    """候选人原始信息表."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    encrypt_geek_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, comment="Boss 直聘候选人唯一标识"
    )
    raw_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="/wapi/ 接口原始 JSON"
    )
    detail_url: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="详情页 URL 路径"
    )
    boss_account_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="来源 Boss 账号 ID"
    )
    job_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="关联岗位 jobId"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ScoringSnapshot(Base):
    """AI 判断快照表."""

    __tablename__ = "scoring_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id"), nullable=False
    )
    hard_rule_results: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="硬规则逐项判断结果"
    )
    llm_raw_output: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="LLM 原始输出"
    )
    job_profile_version: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="岗位画像配置版本"
    )
    final_verdict: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="推荐沟通/可以看看/不建议"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class StoreAccount(Base):
    """门店账号配置表."""

    __tablename__ = "store_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wechat_userid: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, comment="企业微信 userid"
    )
    store_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="门店 ID"
    )
    store_name: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="门店名称"
    )
    boss_account_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="Boss 直聘账号 ID"
    )
    storage_state_path: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="storageState 文件路径"
    )
    job_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="岗位类型"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active", comment="active/disabled"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OperationLog(Base):
    """操作日志表."""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    op_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="screening/greeting/summary"
    )
    boss_account_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="Boss 账号 ID"
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("candidates.id"), nullable=True
    )
    result: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="success/failed/quota_exceeded"
    )
    quota_consumed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="本次消耗配额数"
    )
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="操作详情"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class BossJob(Base):
    """Boss 直聘岗位表（V1 可选预留）.

    用于记录每个 Boss 账号发布的岗位信息，
    C1 抓取推荐列表时按 jobId 区分不同岗位的候选人。
    V1 阶段如果每个账号只关注一个岗位可暂不使用，但表结构先建好。
    """

    __tablename__ = "boss_jobs"
    __table_args__ = (
        UniqueConstraint("boss_account_id", "job_id", name="uq_boss_account_job"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    boss_account_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="Boss 直聘账号 ID"
    )
    job_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="Boss 直聘岗位 ID"
    )
    job_name: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="岗位名称"
    )
    job_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="岗位类型"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active", comment="active/disabled"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
