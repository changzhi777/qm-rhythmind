# CLAUDE.md — docs/knowledge/ 知识库文档

> `[根目录](../../CLAUDE.md) > **docs** > **knowledge**`

> **最后更新:** 2026-06-09T10:59:32+08:00

---

## 模块职责

领域知识 Markdown 文档集合，由 `scripts/ingest_knowledge.py` 解析后写入 `knowledge_article` + `knowledge_reference` 数据库表，供 Agent 分析时引用。

---

## 文件列表

| 文件 | 领域 | 说明 |
|------|------|------|
| `osa_sleep_apnea.md` | `osa` | 阻塞性睡眠呼吸暂停（OSA）筛查与 SpO2 分析 |
| `sleep_athletic_performance.md` | `sleep_performance` | 睡眠与运动表现关联 |
| `vo2max_recovery_training.md` | `vo2max_training` | VO2max 恢复训练指南 |

---

## 文档格式

每个 `.md` 文件遵循结构化模板：

```markdown
**领域:** <domain_tag>

## KA-<ID>：<标题>
### 摘要
...
**来源类型:** academic / clinical_guideline / web
**来源:** <source_name>
**URL:** <source_url>
**标签:** [tag1, tag2]
### 关键发现
- finding 1
- finding 2
---
```

---

## 入库方式

```bash
python scripts/ingest_knowledge.py [--db sqlite:///data/knowledge.db]
```

脚本自动扫描 `docs/knowledge/*.md`，按 `KA-<ID>` 分块解析，去重后写入数据库。

---

## 变更记录 (Changelog)

- **2026-05-27** 首次创建，包含 3 篇领域知识文档
