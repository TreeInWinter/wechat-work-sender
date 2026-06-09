# 知识库维护治理设计

**日期**：2026-06-07
**分支**：`feature/knowledge-base-explore`
**状态**：待评审
**范围**：在现有「采集（`kb_writer.py`）+ 两级检索（`kb_search.py`）+ KB 增强生成（`ai_reply.py`）」基础上，引入一套**知识库治理机制**，让知识库做到三件事：内容保持**正确**、对 AI **检索高效**、对人**方便阅读**。

---

## 0. 背景：这个知识库的本质

它不是给人浏览的 wiki，而是 **RAG 检索语料**——唯一读者是 Claude，唯一目的是让「采集 → 检索 → 生成」闭环越用越准。读者是模型不是人，这一条决定了「好」的标准：

> 好 = **命中率 ↑ × 单条信噪比 ↑ × 矛盾率 ↓ × 过期率 ↓**

当前 append-only 采集 + FTS5 trigram 单路检索，在规模涨到 500~2000 条时会暴露三个结构性问题：**近似重复堆积、答案过期无人纠、trigram 无语义**。本设计逐一解决。

---

## 1. 调研结论：业内三条脉络

三个目标对应业内三个成熟体系，叠加即为整体方案：

| 目标 | 对应体系 | 精髓 |
|------|---------|------|
| 内容**正确** | KCS（知识中心服务，客服知识库治理金标准） | "复用即评审"——知识在被用的过程中持续校正 |
| AI **检索高效** | RAG 检索工程 | 混合检索 + 重排；元数据过滤是第一道关 |
| 人**方便阅读** | 内容生命周期治理 | "足够好就发布"、一条只讲一件事、有主人 |

关键认知（反直觉项）：

1. **"足够好"胜过"完美"**：等写完美文档，知识已过期。先存能用的，复用中打磨。
2. **规模不是越大越好**：近似重复让同一段政策被检索多次，既涨成本又污染上下文。**去重 > 增量**。
3. **检索最大杠杆是重排（reranking），不是更好的 embedding**：生产级 RAG 标准架构是「粗召回 → 交叉编码器重排」。本项目里 **Claude 精读那一步天然就是重排器**。
4. **腐烂速度按内容类型差几个数量级**：价格/行情按天，SOP/政策按月，通用话术按季度。统一过期时间是错的。
5. **owner-less = stale**：没有主人的内容必然腐烂，用户察觉后停止信任，采纳率崩盘。

---

## 2. 可量化的「好」标准（计分卡）

不用"感觉全不全"判断，用以下指标，每项都能从现有数据算出：

**正确性维度**
- 时效命中率：被检索条目中 `last_verified` 在半衰期内的比例
- 矛盾率：同一 scenario 下存在 ≥2 条措辞冲突答案的比例（目标 → 0）
- 编辑率：检索出的答案被用户**发送前改动**的程度（免费的"答案过期"信号）

**AI 检索维度（借 RAGAS 框架）**
- Context Precision：检索回来真正相关的占比（信噪比）
- Context Recall：该检索到的是否都检索到
- 零结果率：挖"查不到"的提问，反推缺哪类知识

**人类可读维度**
- 单条原子性：一条只回答一个问题（"标题能否一句话概括"可检验）
- 复用率：被多次命中的条目占比（KCS 第一指标，没人复用的知识等于不存在）

---

## 3. 数据模型升级（frontmatter）

当前仅 `title/date/tags/source`。新增治理字段，后续所有算法都依赖它们：

```yaml
---
title: 退款流程 - 24小时反馈
scenario: ["怎么退款", "能退钱吗", "退款要多久", "申请退款"]  # 改成"问法变体"数组,检索诱饵
tags: [退款, SOP]            # 受控词表,不自由生成
status: validated            # draft | validated | published | deprecated
confidence: 0.7              # 0~1,随复用/反馈动态更新
owner: baijinshan
source: 企业微信
created: 2026-06-07
last_verified: 2026-06-07    # 每次被复用而未被改动 → 刷新
half_life: 90d               # 按内容类型:价格7d / SOP 90d / 通用 180d
reuse_count: 0
supersedes: []               # 取代了哪些旧条目(去重合并留痕)
---
```

**两个重点字段：**
- `scenario` 从"场景描述"改为**"用户可能怎么问"数组**——trigram 无语义，全靠此字段做语义桥，是单点改 prompt、对检索收益最大的一招。
- `status` + `confidence` 构成生命周期与质量的双轴。

**向后兼容**：旧文件缺字段时，解析侧给默认值（`status=validated`、`half_life=180d`、`confidence=0.5`、`last_verified=date`），不阻断现有检索。

---

## 4. 文章生命周期状态机（借 KCS）

```
  采集
   │
   ▼
[draft] ──人确认──▶ [validated] ──复用≥N次 & 人confirm──▶ [published]
   │                    │                                     │
   │                    └────────── 内容/政策变化 ────────────┤
   │                                                          ▼
   └───────────────────────────────────────────────▶ [deprecated]
                                              (检索时过滤,但不删,留审计)
```

**检索时只召回 `status ∈ {validated, published}`**。这是"元数据过滤先于检索"——既提精度又防止过期答案出场。`deprecated` 不物理删除，保留审计与可恢复性。

---

## 5. 核心算法

### 算法 A：采集去重 / 合并（堵住近似重复源头）

解决 append-only 最大的洞。存入前先查重：

```
on_capture(new_entry):
    候选 = search(new_entry.scenario + new_entry.title, top_k=5)
    for c in 候选:
        sim = max(BM25_归一化(c), embedding_余弦(new, c))   # 无 embedding 时只用前者
        if sim > 0.85:
            → 弹窗:"已有相似条目《c.title》,更新 / 合并 / 新建?"
            合并 = 保留 canonical,新措辞并入,bump last_verified,
                   confidence 上调,supersedes 记录来源
            return
    → 新建 draft
```

### 算法 B：时效 / 健康评分（决定谁复审、谁淘汰）

后台 daemon 周期性给每条算分，低分进"待复审"队列：

```
age        = now - last_verified
freshness  = exp(-age / half_life)                               # 指数衰减,按类型
feedback   = (helpful - unhelpful + 1) / (helpful + unhelpful + 2)  # 拉普拉斯平滑
popularity = log(1 + reuse_count) / log(1 + max_reuse)

health = 0.4*freshness + 0.35*feedback + 0.25*popularity
       - 0.3*(存在同场景矛盾) - 0.2*(owner 为空)

if health < 0.3 and reuse_count == 0:  建议归档(deprecated)
if freshness < 0.5:                    进入"待复审"队列,通知 owner
```

### 算法 C：复用即评审 + 编辑信号（本项目独有的金矿）

普通 KB 没有、但 IM 场景天然有的信号：**检索出的答案 vs 用户真正发出去的答案之间的 diff**。

```
on_send(retrieved_entry, final_text):
    edit = 归一化编辑距离(retrieved_entry.reply, final_text)
    if edit < 0.1:        # 几乎原样发出 = 仍然正确
        reuse_count += 1
        last_verified = now        # "复用即评审"——隐式重新验证
        confidence ↑
    elif edit > 0.4:      # 大改 = 已过时
        flag_for_review(entry)
        建议:用 final_text 生成"改进版"草稿
    # 0.1~0.4:小修,confidence 微降
```

发出去就是最强的"对不对"反馈，零成本、不打扰用户。

---

## 6. 检索架构升级（对 AI 高效）

当前 FTS5 trigram 单路、无语义。生产级标准是混合检索 + 重排：

```
[召回] FTS5 (词面/BM25)  ┐
                          ├─ RRF 倒数排名融合 → Top-15 ─→ [重排] Claude 精读精选 3~5
       embedding (语义)   ┘                                  (现有第二级 = 重排器)
       ↑ 先按 status/tags 元数据过滤,缩小候选池
```

- 加一路 embedding 召回（本地小模型或公司内部 API），RRF 与 FTS 融合，补"退钱↔退款"语义缺口。
- **重排已由 Claude 完成**，所以 embedding 是后置项——研究指出对强模型 BM25+embedding 边际收益缩小。**先做好元数据与去重，再上语义检索。**

---

## 7. 后台维护（一个 daemon，三件事）

把维护变成自动巡检，不靠人记得：

1. **去重扫描**：周期性两两比相似度，>0.9 提示合并
2. **腐烂扫描**：跑算法 B，低 health 进待复审队列
3. **缺口挖掘**：记录"检索零结果"提问，反推该补哪类知识

---

## 8. 落地优先级（本分支 roadmap）

按投入产出比排序：

| 优先级 | 做什么 | 改哪 | 收益 |
|-------|-------|------|------|
| **P0** | frontmatter 加治理字段 + status 过滤检索 | `kb_writer.py` `kb_search.py` | 防过期答案出场,所有算法地基 |
| **P0** | 采集去重(算法 A) | `gui_panel.py` 存入流程 + `kb_search.py` | 堵住近似重复,治本 |
| **P1** | `scenario`→问法变体 + 受控 tags | `ai_reply.py` 提炼 prompt | 单点改,检索精度最大提升 |
| **P1** | 复用即评审 + 编辑信号(算法 C) | 发送流程埋点 | 免费的正确性反馈闭环 |
| **P2** | 健康评分 + 待复审队列(算法 B + daemon) | 新增 `kb_maintain.py` | 自动防腐烂 |
| **P3** | embedding 混合检索 | `kb_search.py` | 补语义缺口(后置) |

---

## 9. 文件变更清单（预估）

| 文件 | 变更 | 说明 |
|------|------|------|
| `kb_writer.py` | 修改 | 写入新 frontmatter 字段；采集前调用查重 |
| `kb_search.py` | 修改 | 解析新字段并向后兼容；检索按 status 过滤；（P3）embedding + RRF |
| `ai_reply.py` | 修改 | `extract_kb_entry()` 生成问法变体 + 受控 tags |
| `gui_panel.py` | 修改 | 去重合并弹窗；发送埋点；待复审入口 |
| `kb_maintain.py` | **新增** | 健康评分、去重扫描、缺口挖掘 daemon |
| `config.py` | 微改 | 受控 tag 词表、半衰期默认值等配置项 |

---

## 10. 验证方式

1. 采集已有相似条目 → 弹"更新/合并/新建"，不产生近似重复文件
2. 检索结果不含 `status: deprecated` 的条目
3. 原样发送检索答案 → 该条 `reuse_count +1`、`last_verified` 刷新
4. 发送前大改答案 → 该条进"待复审"队列
5. 旧版无新字段的 `.md` 仍能被正常检索（向后兼容）
6. 健康评分 daemon 能把过期/零复用条目挑进待复审队列

---

## 参考来源

- [From RAG to Context — 2025 year-end review | RAGFlow](https://ragflow.io/blog/rag-review-2025-from-rag-to-context)
- [Designing RAG Architectures That Scale: Chunking, Deduplication, Accuracy | Sabarish Kumar](https://sabarishkumarg.medium.com/designing-rag-architectures-that-scale-chunking-deduplication-and-accuracy-improvements-1adb76dbd8ec)
- [Optimizing Knowledge Bases for Effective RAG Pipelines | Unstructured](https://unstructured.io/insights/knowledge-base-optimization-for-enterprise-rag-pipelines)
- [Optimizing RAG with Hybrid Search & Reranking | Superlinked VectorHub](https://superlinked.com/vectorhub/articles/optimizing-rag-with-hybrid-search-reranking)
- [Hybrid Search and Re-Ranking in Production RAG | Towards Data Science](https://towardsdatascience.com/hybrid-search-and-re-ranking-in-production-rag/)
- [LLM Knowledge Base Staleness: Scoring, Causes, and Fixes | Atlan](https://atlan.com/know/llm-knowledge-base-staleness/)
- [Content Freshness: Automating Updates and Deletions | Cobbai](https://cobbai.com/blog/knowledge-freshness-automation)
- [The KCS Practices | Consortium for Service Innovation](https://library.serviceinnovation.org/KCS/KCS_v6/KCS_v6_Practices_Guide/030)
- [13 KCS Best Practices | InvGate](https://blog.invgate.com/kcs-best-practices)
- [Building a Maintenance Knowledge Base That Actually Gets Used | Dovient](https://dovient.com/resources/blog/maintenance-knowledge-base-that-gets-used)
- [RAGAS Metrics Documentation](https://docs.ragas.io/en/v0.1.21/concepts/metrics/)
