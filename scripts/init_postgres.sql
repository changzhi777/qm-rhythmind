-- init_postgres.sql
-- PostgreSQL 初始化脚本（docker-entrypoint-initdb.d 自动执行）

-- 启用常用扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID 生成
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- 模糊搜索（未来全文检索用）
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- 密码加密

-- 设置时区（统一 UTC）
SET timezone = 'UTC';

-- 确认
SELECT current_database(), current_user, version();
