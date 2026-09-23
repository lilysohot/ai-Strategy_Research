"""I4 窗口目标库解析（r5g 冻结）：默认 i2_sandbox_corpus，显式 CORPUS_TARGET_DB 才放行生产。

fail-closed 默认不变：未设置 ``CORPUS_TARGET_DB`` 时，读写两侧仍硬绑隔离库
``i2_sandbox_corpus``，含 ``apodex`` 库的生产实例一律拒绝。I4 窗口操作（I4-7
迁移 / I4-4 重建 / I4-5 验收）在子进程环境显式设置 ``CORPUS_TARGET_DB=<目标库名>``
时，目标库解析与生产实例反证按显式授权放行——环境变量是唯一开关，没有其他旁路。
"""

from __future__ import annotations

import os

SANDBOX_DB = "i2_sandbox_corpus"
TARGET_DB_ENV = "CORPUS_TARGET_DB"

__all__ = ["SANDBOX_DB", "TARGET_DB_ENV", "production_instance_authorized", "resolve_target_db"]


def resolve_target_db() -> str:
    """解析目标库：显式 ``CORPUS_TARGET_DB`` 优先，否则隔离库（默认行为不变）。"""
    value = os.environ.get(TARGET_DB_ENV, "").strip()
    return value or SANDBOX_DB


def production_instance_authorized() -> bool:
    """是否显式授权面向生产实例（含 ``apodex`` 库的实例）。

    仅在 ``CORPUS_TARGET_DB`` 非空时为真；``current_database`` 校验仍按调用方
    传入的目标库名执行，本函数只放开 apodex 反证这一道闸。
    """
    return bool(os.environ.get(TARGET_DB_ENV, "").strip())
