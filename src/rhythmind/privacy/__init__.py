# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — privacy package (GDPR / PIPL data subject rights)
# ─────────────────────────────────────────────────────────────────────────────
"""
privacy — 用户数据导出与删除（数据主体权利）

公开 API:
  - PrivacyService : 业务逻辑，无 FastAPI 耦合，便于单测
  - export_user_data(user_id) -> dict
  - delete_user_data(user_id, *, confirm_token) -> DeletionReport
"""
from rhythmind.privacy.service import (  # noqa: F401
    DeletionReport,
    PrivacyService,
    UserDataExport,
)
