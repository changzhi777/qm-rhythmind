# CLAUDE.md — docs/knowledge/ 知识库文档

> `[根目录](../../CLAUDE.md) > **docs** > **knowledge**`

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 模块职责

领域知识 Markdown 文档集合，由 `scripts/ingest_knowledge.py` 解析后写入 `knowledge_article` + `knowledge_reference` 数据库表，供 Agent（MedicalAdvisor/CoachAgent）分析时做 RAG 引用。

---

## 文件列表

| 文件 | 领域标签 | KA-ID 范围 | 条目数 | 行数 | 主要来源类型 |
|------|---------|-----------|--------|------|-------------|
| `osa_sleep_apnea.md` | `osa` | OSA-001 ~ OSA-010 | 10 | ~215 | academic 为主 |
| `sleep_athletic_performance.md` | `sleep_performance` | SLP-001 ~ SLP-010 | 10 | ~190 | academic 为主 |
| `vo2max_recovery_training.md` | `vo2max_training` | VO2-001 ~ VO2-010 | 10 | ~270 | academic + web |

**总计**: 3 领域 × 10 条目 = 30 篇知识文章

---

## 各文档内容概要

### osa_sleep_apnea.md（OSA 筛查）

| KA-ID | 标题 | 来源 | 关键结论 |
|-------|------|------|---------|
| OSA-001 | 可穿戴设备 OSA 筛查验证 | Springer 2024 | 脉搏血氧戒指敏感性 >85%，ODI 与 AHI 高度相关 |
| OSA-002 | 腕式设备夜间 SpO2 监测 | JCSM | 腕式设备可可靠识别 OSA 严重度分级 |
| OSA-003 | OSA 与心血管风险 | clinical_guideline | 未治疗 OSA 增加高血压/房颤/心衰风险 |
| OSA-004 | SpO2 阈值与 OSA 严重度 | academic | SpO2<90% 占比 >30% 高度怀疑中重度 OSA |
| OSA-005 | OSA 对运动表现的影响 | academic | 夜间低氧 → 白天疲劳、VO2Max 下降 |
| OSA-006~010 | 诊断标准/CPAP 治疗/筛查流程 | mixed | 多导睡眠监测（PSG）为金标准 |

### sleep_athletic_performance.md（睡眠与运动表现）

| KA-ID | 标题 | 来源 | 关键结论 |
|-------|------|------|---------|
| SLP-001 | 睡眠剥夺对耐力影响的荟萃分析 | EJSS 2022 | 中等效应量 d=-0.55，运动时间越长影响越大 |
| SLP-002 | 部分睡眠限制对 12min 自配速跑的影响 | Psychophysiology 2020 | 减少 2-3h 睡眠 → 耐力下降 |
| SLP-003 | 睡眠延长对运动表现的改善 | academic | 延长睡眠 1-2h → 冲刺速度/反应时提升 |
| SLP-004 | 深睡与生长激素分泌 | academic | 深睡期间 HGH 脉冲分泌，肌肉修复依赖 |
| SLP-005~010 | REM/运动恢复/昼夜节律/午睡策略 | mixed | — |

### vo2max_recovery_training.md（VO2Max 恢复训练）

| KA-ID | 标题 | 来源 | 关键结论 |
|-------|------|------|---------|
| VO2-001 | Norwegian 4×4 间歇训练方案 | NTNU/Wisløff | 比中等强度 VO2Max 提升高 46%，8-10 周 +5-15% |
| VO2-002 | 4×4 心率反应特征 | academic | 高强度区间 85-95%HRmax，主动恢复 60-70%HRmax |
| VO2-003 | 80/20 极化训练原则 | academic | 80% 低强度 + 20% 高强度的配比最优 |
| VO2-004 | VO2Max 可训练性（遗传 vs 训练） | academic | 训练可提升 5-20%，个体差异大 |
| VO2-005~010 | 停训后恢复/阈值训练/年龄相关下降 | mixed | 停训 2 周 VO2Max 开始下降，恢复需 4-8 周 |

---

## 文档模板（结构化字段说明）

每个 `.md` 文件遵循统一模板，`ingest_knowledge.py` 按 `KA-<ID>` 分割：

```markdown
# <文档标题>

> **领域:** <domain_tag>        → knowledge_article.domain
> **更新日期:** YYYY-MM-DD      → knowledge_article.updated_at
> **条目数:** N

---

## KA-<DOMAIN>-<NNN>：<标题>     → 分割标记，一篇文章的起点

- **来源类型:** academic | clinical_guideline | web
  → knowledge_reference.source_type
- **来源:** <source_name>        → knowledge_reference.source_name
- **URL:** <source_url>          → knowledge_reference.source_url
- **标签:** [tag1, tag2]          → knowledge_reference.tags (JSON array)

### 摘要                        → knowledge_article.summary
<2-4 句核心结论>

### 关键发现                      → knowledge_article.key_findings (JSON array)
- finding 1
- finding 2
---

## KA-<DOMAIN>-<NNN>：<下一篇标题>
...
```

### 来源类型枚举

| 类型 | 说明 | 对应 reference 表 |
|------|------|-------------------|
| `academic` | 同行评审期刊论文 | `source_type = 'academic'` |
| `clinical_guideline` | 临床指南/专家共识 | `source_type = 'clinical_guideline'` |
| `web` | 权威网站/博客文章 | `source_type = 'web'` |

---

## 数据库映射

### knowledge_article 表

| 字段 | 类型 | 来源 | 示例 |
|------|------|------|------|
| `ka_id` | string(PK) | 标题中的 `KA-<ID>` | `KA-OSA-001` |
| `domain` | string | 文件头部 `**领域:**` | `osa` |
| `title` | string | `## KA-XXX：<title>` | `OSA 筛查的可穿戴设备验证` |
| `summary` | text | `### 摘要` 段落 | — |
| `key_findings` | JSONB | `### 关键发现` 列表 | `["发现1", "发现2"]` |
| `source_doc` | string | 源文件名 | `osa_sleep_apnea.md` |
| `created_at` | datetime | 入库时间 | — |
| `updated_at` | datetime | 文件头部日期 | — |

### knowledge_reference 表

| 字段 | 类型 | 来源 | 示例 |
|------|------|------|------|
| `id` | int(PK) | 自增 | — |
| `article_ka_id` | string(FK) | 关联文章 | `KA-OSA-001` |
| `source_type` | string | `- **来源类型:**` | `academic` |
| `source_name` | string | `- **来源:**` | `Springer, 2024` |
| `source_url` | text | `- **URL:**` | `https://link.springer.com/...` |
| `tags` | JSONB | `- **标签:**` | `["osa", "screening"]` |

---

## Agent 引用方式

### MedicalAdvisor 使用流程

```
用户上传 Garmin 数据
    ↓
SpO2 分析 → 发现 hypoxic_nights > 30%
    ↓
RAG 检索: "OSA" "SpO2<90%" → knowledge_article
    ↓
匹配 KA-OSA-004 (SpO2 阈值) + KA-OSA-001 (可穿戴设备验证)
    ↓
输出: "您的 SpO2 数据提示可能存在 OSA，建议做睡眠监测（PSG）确认"
```

### CoachAgent 使用流程

```
分析睡眠数据 → 发现 avg_total_hours < 6h
    ↓
RAG 检索: "sleep deprivation" "endurance" → knowledge_article
    ↓
匹配 KA-SLP-001 (荟萃分析: 效应量 d=-0.55)
    ↓
输出: "您的睡眠不足可能使耐力表现下降 3-7%，建议优先改善睡眠"
```

---

## 入库方式

```bash
# 全量入库（默认 SQLite）
python scripts/ingest_knowledge.py

# 指定数据库
python scripts/ingest_knowledge.py --db postgresql://user:pass@host:5432/db

# 单领域增量
python scripts/ingest_knowledge.py --domain osa
python scripts/ingest_knowledge.py --domain sleep_performance
python scripts/ingest_knowledge.py --domain vo2max_training
```

**入库逻辑**: 扫描 `docs/knowledge/*.md` → 按 `KA-<ID>` 正则分割 → 解析元数据 → 去重（按 `ka_id`）→ UPSERT 到两个表

---

## 变更记录 (Changelog)

- **2026-06-10** 深化：新增 30 条 KA-ID 内容概要表、模板字段→数据库映射、Agent 引用流程图、来源类型枚举
- **2026-05-27** 首次创建，包含 3 篇领域知识文档
