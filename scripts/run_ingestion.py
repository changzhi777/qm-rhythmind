"""
run_ingestion.py — 一键入口：数据入库 + 启动仪表盘服务

用法：
  python scripts/run_ingestion.py          # 入库 + 启动服务
  python scripts/run_ingestion.py --ingest # 仅入库（不启动服务）
  python scripts/run_ingestion.py --serve  # 仅启动服务（不重新入库）

流程：
  1. 初始化 SQLite 数据库
  2. 创建 GarminDataSourceAdapter
  3. IngestionEngine.ingest()  → 数据写入 HealthFact
  4. IngestionEngine.analyze() → 调用本地模型生成 AI 报告
  5. 启动 FastAPI + 静态文件服务 → 前端仪表盘
"""
from __future__ import annotations

import asyncio
import os
import sys

# ── 环境配置（必须在 rhythmind import 之前）────────────────────────────────
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./garmin_health.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("QMD_URL", "http://localhost:8181")
os.environ.setdefault("JWT_SECRET", "test-secret-for-dashboard")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test")
os.environ.setdefault("LITELLM_URL", "http://localhost:4000")
os.environ.setdefault("DEV_AUTH_BYPASS", "true")
os.environ.setdefault("ENFORCE_MODEL_PLATFORM", "false")

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


async def run_ingestion(garmin_data_dir: str) -> None:
    """执行数据入库 + AI 分析。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from rhythmind.core.memory.models import Base
    import rhythmind.core.memory.manager as mem_manager

    # 初始化数据库
    db_path = os.path.join(PROJECT_ROOT, "garmin_health.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    mem_manager.AsyncSessionLocal = session_factory

    # 创建适配器
    from rhythmind.ingestion import GarminDataSourceAdapter, IngestionEngine

    adapter = GarminDataSourceAdapter(garmin_data_dir)
    errors = adapter.validate()
    if errors:
        print(f"❌ 数据源验证失败:")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)

    print(f"📂 数据目录: {garmin_data_dir}")
    print(f"✅ 数据源验证通过")

    # 入库
    engine_ing = IngestionEngine(adapter, model_spec="omlX://gemma-4-e4b-it-4bit")
    print("\n⏳ 开始数据入库...")
    result = await engine_ing.ingest()

    print(f"\n✅ 入库完成:")
    print(f"   - 用户画像: {result.profile_records} 条")
    print(f"   - 活动统计: {result.activity_records} 条")
    print(f"   - 睡眠数据: {result.sleep_records} 条")
    print(f"   - 身体指标: {result.body_metric_records} 条")
    print(f"   - 训练指标: {result.training_records} 条")
    print(f"   - 健康事件: {result.health_event_records} 条")
    print(f"   - 总计: {result.total} 条")
    if result.errors:
        print(f"\n⚠️ 错误:")
        for e in result.errors:
            print(f"   - {e}")

    # AI 分析
    print("\n🤖 调用本地模型生成 AI 分析报告...")
    print(f"   模型: omlX://gemma-4-e4b-it-4bit")
    try:
        report = await engine_ing.analyze()
        print(f"✅ AI 报告生成完成 ({len(report)} 字)")
        # 输出到文件
        report_path = os.path.join(PROJECT_ROOT, "佳明手表AI分析报告.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# AI 健康分析报告\n\n> 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n> 模型: omlX://gemma-4-e4b-it-4bit\n\n{report}")
        print(f"📄 报告已保存: {report_path}")
    except Exception as e:
        print(f"❌ AI 分析失败: {e}")

    await engine.dispose()


def _create_app():
    """创建 FastAPI 应用实例。"""
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from fastapi.middleware.cors import CORSMiddleware

    # 初始化数据库
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    import rhythmind.core.memory.manager as mem_manager

    db_path = os.path.join(PROJECT_ROOT, "garmin_health.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    mem_manager.AsyncSessionLocal = session_factory

    app = FastAPI(title="RHYTHMIND 健康仪表盘")

    # 注册 dashboard 路由
    from rhythmind.api.routers.dashboard import router as dashboard_router
    app.include_router(dashboard_router)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态文件
    web_dir = os.path.join(PROJECT_ROOT, "web")

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(web_dir, "index.html"))

    app.mount("/static", StaticFiles(directory=web_dir), name="static")
    return app


def serve():
    """启动 FastAPI + 静态文件服务。"""
    import uvicorn

    db_path = os.path.join(PROJECT_ROOT, "garmin_health.db")
    if not os.path.exists(db_path):
        print("❌ 数据库不存在，请先运行: python scripts/run_ingestion.py --ingest")
        sys.exit(1)

    app = _create_app()

    port = 8088
    print("\n🚀 启动仪表盘服务...")
    print(f"   地址: http://localhost:{port}")
    print(f"   API:  http://localhost:{port}/api/dashboard")
    print(f"   报告: http://localhost:{port}/api/reports")
    print()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="RHYTHMIND 数据入库 + 仪表盘")
    parser.add_argument("--ingest", action="store_true", help="仅入库不启动服务")
    parser.add_argument("--serve", action="store_true", help="仅启动服务不入库")
    parser.add_argument("--data-dir", default=None, help="佳明数据包目录路径")
    args = parser.parse_args()

    # 数据目录
    garmin_dir = args.data_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(PROJECT_ROOT))),
        "佳明手表数据包"
    )
    # 尝试多种路径
    if not os.path.isdir(garmin_dir):
        alt = os.path.join(os.path.dirname(PROJECT_ROOT), "佳明手表数据包")
        if os.path.isdir(alt):
            garmin_dir = alt
        else:
            alt2 = os.path.join(PROJECT_ROOT, "..", "..", "佳明手表数据包")
            if os.path.isdir(alt2):
                garmin_dir = os.path.abspath(alt2)

    if args.serve:
        serve()
    elif args.ingest:
        asyncio.run(run_ingestion(garmin_dir))
    else:
        asyncio.run(run_ingestion(garmin_dir))
        serve()


if __name__ == "__main__":
    main()
