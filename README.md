# 03 — 章鱼 AI 量化策略日报 (Editorial E-Ink Edition)

自动生成的分析报告站点: <https://k-macao.github.io/03/>

## 🔄 动态抓取真正上线 — 行情+社区双动态 (每次构建/推送自动更新)

每次 push、手动触发或每天 09:00 定时任务，都会**先自动抓取最新行情+14 大社区最新研判，再构建报告并推送**，
页面与微信收到的永远是当天最新数据，杜绝“8 月 12 日”旧内容残留：

```bash
python3 market_data.py               # ① 动态抓取行情 → market_data.json (Yahoo→Stooq回退)
python3 verify_quotes.py --json verify_report.json --text   # ①′ 全来源交叉校验 (FAIL=2 阻断推送；网页阶段仅公开报告不阻断)
python3 community_data.py            # ② 动态抓取14社区 → community_data.json (HTTP GET+模板回退，每次刷新当天日期)
python3 macro_data.py                # ②′ 动态抓取宏观/财经快讯 → macro_data.json (网页 02 节 + 微信 02 栏正文；只保留 7 天内、发布日期可解析的条目)
python3 build_site.py                # ③ 动态建站 → report.html (注入行情+社区+宏观快讯+日期/时间戳，14源动态注入)
python3 tools/wechat_push.py --embed # ④ 内嵌最新推送负载进 report.html
python3 tools/wechat_push.py --push --scheduled   # ⑤ 推送完整报告到微信
```

- **行情源**：Yahoo Finance chart API → Stooq CSV 多源自动回退（纯标准库，CI 无需安装依赖）。
- **社区源**：14 大社区（富途牛牛/雪球/老虎/东方财富/智通财经/华尔街见闻/香港讨论区/LIHKG/韭圈儿/蚂蚁财富/Reddit/TradingView/VIC/FinTwit）**每次构建均 HTTP GET 尝试抓取**，提取文本片段作为活数据佐证，结合最新行情动态生成研判；单源失败自动降级为基于最新行情的动态模板，保证 14 源永远齐全，**正文日期永远为当天**。
- **覆盖标的**：恒指 / 恒生科技 / 恒生国企 / 标普 500 / 纳斯达克 / 道琼斯 / 现货黄金 / WTI / 布伦特 / 美元离岸与在岸人民币。
- **失败降级**：单品行情/单社区抓取失败自动降级（行情显示 "—"，社区显示动态模板），并在页面标注，**不阻断构建与推送**，保证 09:00 定时任务永不中断。
- **02 栏（全球经济与财经动态）已改为快讯驱动**：`macro_data.py` 每次构建现抓 Google News RSS（中/英分主题）+ 美联储官方新闻稿 RSS + 东财财经快讯检索，按「宏观 / 美联储 / 港股 / 大宗商品 / 大行目标价」五类归组后渲染，**每条快讯自带发布日期**；超窗或无日期的条目在数据层就被丢弃（`stale_dropped` / `undated_dropped`）。**修复背景（2026-09-16 核查）**：这一栏原本是写死在 `tools/wechat_push.py` 里的固定文案（IMF 7 月 WEO、7 月 29 日 FOMC、8 月 12 日 CPI、南向 628.69 亿、各行恒指目标价…），构建时原样重播、页脚却盖当天时间戳，导致「生成时间是当天、正文停在 8 月 12 日」；现在抓不到快讯时 02 栏明确显示「今日未获取」+ 实时行情，**绝不回填历史叙事**（回归防线：`tests/test_wechat_push_macro.py` 断言正文不得再出现任何写死的历史事实）。
- **网页 02 节同步接入宏观快讯**：`report.html` 的 02 节（行情快照）新增 `<!-- MACROLIST -->` 占位区，`build_site.py` 从**同一个** `macro_data.json` 注入五类快讯（每条自带发布日期，注入区尾部留 `<!-- /MACROLIST -->` 哨兵保证重复构建幂等）；缺 `macro_data.json` 时网页同样显示「今日未获取」+ `python3 macro_data.py …` 恢复命令，**绝不回填历史叙事** —— 网页与微信推送共用一套数据与时效口径（回归防线同上：`tests/test_wechat_push_macro.py` 同时断言网页注入区不含任何写死的历史事实）。
- **CI 接入待人工应用一次**：`macro_data.py` 的构建步骤、以及 `verify_quotes.py` 的推送门禁（`#43` 声称但从未生效的部分：Pages 阶段 `|| true` 不阻断 + `verify_report.json` 随站点公开，推送阶段 FAIL 直接阻断）都以 `docs/macro-ci-workflow.patch` 随本仓库交付（Agent 的 GitHub App 缺 `workflows` 权限，含 `.github/workflows/**` 的提交会被远端 reject）。在有权限的账号执行 `git apply docs/macro-ci-workflow.patch` 并合并之前，构建不会产出 `macro_data.json`，02 栏会稳定显示「今日未获取」+ 实时行情（而不是重播旧文案）——这是刻意选择的降级方向。
- **日期联动**：14 大社区「最新读取」日期与正文中的“8 月 X 日”日期均随抓取日自动刷新（`community_data.py` 生成当天日期），推送前日期核对（`--push` 严格 / `--scheduled` 宽松）逻辑保持不变。
- 本地联调可用 `python3 market_data.py --demo && python3 community_data.py --demo` 生成模拟行情+社区。

## 🌍 01 栏：每日全球全景扫描 (Daily Global Panorama Scan)

> 扫一遍今天全球市场，总结推动股价的 5 大力量。重点关注宏观事件、板块轮动、情绪变化。
> 哪些是重点，哪些是噪音。如何利好利空。是否可以做多。

本栏由 `panorama.py` 在**每次构建时现算**，四路当次数据（行情 / 宏观快讯 / 舆情因子 / 社区研判）
合成，**引擎里不存放任何新闻事实、点位与日期**——与 02 / 03B 栏同一套反陈旧口径。

**① 候选力量（取到数据才出现，取不到就不编故事）**

| 力量 | 数据来源 | 归类 |
|---|---|---|
| 港股盘面本身 | 恒指 / 恒科 / 国企当日涨跌 + 港股快讯 | 市场盘面 |
| 全球风险偏好 | 标普 / 纳指 / 道指的隔夜映射 | 市场盘面 |
| 美元利率与离岸流动性 | 联储快讯 + 离岸人民币 + 黄金 | 宏观事件 |
| 宏观事件与全球增速 | 央行 / 经济数据 / 政策类快讯 | 宏观事件 |
| 大宗商品与供应链 | WTI / 布伦特 / 黄金 + 供应链快讯 | 宏观事件 |
| 机构观点 | 大行目标价与配置建议快讯 | 宏观事件 |
| 板块轮动 | 恒科−恒指、纳指−道指的成长/价值价差 | 板块轮动 |
| 情绪变化 | 舆情温度计 + 14 源社区多空家数 | 情绪变化 |

**② 打分与重点 / 噪音判定（显式规则，可复算）**

```
力量分 = 100 × (0.45 × 幅度 + 0.30 × 印证度 + 0.25 × 时效)
  幅度   |涨跌幅| / 该资产的显著性阈值（不同资产波动率不同，阈值分开给）
  印证度 独立证据条数 / 3（多资产或多条快讯互相印证才算高）
  时效   行情当次抓取 = 1.0；快讯当天 1.0，每往前 1 天 −0.15

≥55 重点　35~55 次要　<35 或未过噪音阈值 → 噪音（分数压到 30 以内，且不参与做多结论）
```

噪音阈值举例：恒指 0.35% / 纳指 0.40% / WTI 0.80% / 离岸人民币 0.12%；
成长−价值价差低于 0.30 个百分点即判定「当日无有效轮动」，避免把噪音讲成故事。

**③ 是否可以做多（合成分 + 置信度）**

```
合成分 = Σ(方向 × 力量分 × 权重) / Σ(力量分 × 权重) × 100     # 噪音力量不计入
调整项：突发风险分 ≥60 → −10；负面新闻占比 ≥60% → −5
置信度 = 0.6 × 数据覆盖率 + 0.4 × 有效力量广度

≥25 可以做多　≥10 轻仓试多　−10~10 观望　≤−10 偏防御　≤−25 减仓或对冲
置信度 <0.35 → 直接输出「数据不足 · 不给做多结论」
```

每条结论都挂着推导它的证据（行情读数或当次快讯标题 + 发布日期），并给出恒指前收盘作为
多头有效性参考位。四路数据全缺时本栏渲染为「今日未获取 —— 本栏不编故事」，**绝不回填历史叙事**。

```bash
python3 panorama.py                 # 读仓库内 4 份 json → 文本摘要
python3 panorama.py --json out.json # 导出结构化扫描结果（便于回测/核对）
python3 panorama.py --self-test     # 规则自检（普涨 / 普跌 / 横盘 / 空数据）
python3 -m unittest tests.test_panorama   # 13 项回归
```

## 🗞️ 舆情 / 新闻因子层 — 多量化平台采集 → 日报标的匹配（对外**不显示来源**）

社区热评是"印象"，量化要的是**可回测的因子**。本层从多家量化平台采集**现成的舆情 / 新闻情感因子**，
合成成 5 个可直接入模的因子，并把采集到的每条新闻**匹配到日报正文的行情标的与主题**后展示，
接入同一条日报管线（页面 03B 节 + 微信 03B 节点）：

```bash
python3 tools/probe_sentiment_apis.py --mock     # ① 接口接入实测 + 6 维打分 → api_probe_report.json + docs/sentiment-api-eval.md（内部档案）
python3 sentiment_nlp.py --self-test             # ② 自建中文金融词库自检（否定/程度/风险词规则）
python3 sentiment_match.py --self-test           # ②′ 标的匹配 + 来源脱敏自检（采集关键词是否对得上日报标的）
python3 sentiment_adapters.py --mode mock        # ③ 11 个接口逐个解析校验（零联网）
python3 sentiment_factors.py --mock              # ④ 离线回放：采集 → 合成因子 → 标的匹配 → sentiment_data.json（CI/本地默认用这条）
python3 sentiment_factors.py --live              # ④′ 境内出口 + 凭据的联网实测（优先平台现成因子，缺失时自动降级）
python3 build_site.py                            # ⑤ 建站时把「因子读数 + 标的匹配」注入 report.html 的 <!-- SENTIMENT_LIST --> 标记
```

- **🔒 对外展示策略（本次新增）**：网页与微信推送的 03B 节**不显示数据来源** —— 平台名 / 接口 ID / 域名 / SDK /
  凭据与依赖报错由 `sentiment_match.redact()` 统一遮成「量化平台」，逐源明细表默认不渲染，
  「量化平台现成舆情/新闻因子接入评测（9 阶段实测）」评分矩阵默认隐藏；
  来源明细只保留在内部：`sentiment_data.json`（构建产物，不入库）的 `sources[] / series[].source / news[].source`
  与本节表格、`docs/sentiment-api-eval.md`（内部评测档案）。
  临时恢复内部视图：`SENTIMENT_SHOW_SOURCE=1`（来源明细）、`SENTIMENT_SHOW_API_EVAL=1`（评测矩阵）。
- **🎯 采集 → 匹配 → 显示（本次新增）**：`sentiment_match.py` 用与 `market_data.py` 同一套 key 的标的表
  （恒指 / 恒科 / 国企 / 标普 / 纳指 / 道指 / 黄金 / 原油 / 人民币 + 美联储、内房、高息防御、地缘供应链 4 个主题）
  做关键词匹配（标题命中权重 0.4 / 正文 0.15），复用 `sentiment_nlp.aggregate()` 的同一套因子口径，
  产出 `sentiment_data.json` 的 `matches` 字段：每个标的的命中条数、净情感、负面占比、风险分、舆情温度与代表新闻（不含来源），
  以及整体匹配率与未匹配条数；检索型接口的采集关键词同样取自该表（`search_keywords()`），保证"采回来的"和"要显示的"对得上。

- **因子口径**：`NET_SENTI` 净情感强度 = Σ(情感×权重)/Σ权重 ∈[-1,1]；`NEG_SHARE` 负面舆情占比；
  `NEWS_HEAT_Z` 新闻热度 Z 值（今日条数对近 20 日均值标准化）；`SENT_TEMP` 市场舆情温度计 = 50+35·net+12·tanh(z/2)−18·neg_share ∈[0,100]（≥72 极度亢奋 / ≥60 偏热 / ≥45 中性 / ≥32 偏冷 / ≥20 恐慌）；`EVENT_RISK` 突发事件风险分（立案/处罚/造假/违约…加权，截断 0-100）。
- **打分规则可解释**：命中金融情感词按词权计分 → 程度副词乘权（大幅×1.5 / 小幅×0.7…）→ 否定字（不未无没非失否难）在情感词前 3 字内则极性翻转打 8 折 → 按发布时间 24h 半衰期指数衰减加权；平台已给 `sentiment` 时**优先采用平台口径**（结果里标 `source_provided`），纯标准库、可复现。
- **实测结论（仓库内部档案，详见 `docs/sentiment-api-eval.md`；不在网页/推送中展示）**：

| 平台 | 现成舆情/新闻因子 | 关键接口 | 时效 / 历史 | 口径提醒 |
|---|---|---|---|---|
| 米筐 RQData | ✅ 最贴近"现成因子" | 私有 pip 源装 `rqdatac` + `rqdatac_news` → `rqdatac.news.get_stock_news()` | 日内每 30 分钟；2017 至今 | `news_emotion_indicator`(±1/0) + 正/中/负 weight + `company_relevance` + 公司层情感，拿到即可入模；需商务开舆情数据包 |
| 聚宽 JQData | ⚠️ 名不副实 | `get_factor_values(['VOL5','VOL20','AR','BR','ARBR','ATR14',…])`；舆情仅 `finance.CCTV_NEWS` / 雪球热度 / 百度因子 | 因子 T+1 05:00；热度 03:00；新闻联播 20:30 | 聚宽"情绪因子"= 量价换手类，**不是新闻情感**；试用账号「因子和特色数据：无」；`get_query_count()` 可当配额探针 |
| 掘金量化 | ❌ 不提供 | `gm.api`：`history/current/stk_get_*/fnd_*`（无新闻·无情感） | 行情实时 | 官方 FAQ：指标数据需自行设计实现；SDK 依赖本地掘金终端代理 → CI 完全不可用；舆情必须外挂 |
| 优矿 Uqer | ✅ 免费层最划算 | `DataAPI.NewsSentimentIndexGet→sentimentIndex`、`NewsHeatIndexGet→heatIndex`、`NewsByTickersGet` | 指数日更；新闻 2004-10-28 起 | 现成日频舆情因子，两个数即可入模；站点迭代放缓，字段需实测复核 |
| Tushare Pro | ⚠️ 只给文本 | `POST api.tushare.pro {api_name:'news'/'major_news'/'cctv_news'}` | 准实时；6–8 年 | 需单独开权限；`news` 单次 1500 条；配合自建词库才成因子 |
| 免费兜底 | 热度可用 / 情感弱 | 东财千股千评（关注指数）、金十微博人气、东财 search-api 新闻、数库情绪指数 | 日更 / 小时级 | 东财只有热度无极性；数库端点疑似随官网改版下线，必须降级 |

- **落地建议**：有预算 → 米筐（唯一"给到即入模"）；性价比 → 优矿；零成本 → 东财热度 + Tushare/东财文本 + 自建词库；聚宽只补量价情绪因子；**掘金不承担舆情**。
- **境内出口硬约束**：聚宽 `dataapi.joinquant.com` 等站点对非中国大陆 IP 直接拒绝访问，GitHub 海外 runner 跑不通 → CI 里 `--live` 失败即自动降级 `--mock`（页面与推送显示"降级说明"，绝不阻断 09:00 定时任务）；要拿真实因子请在境内执行器（自建机 / 境内 Actions runner）跑 `--live` 并配好凭据。
- **凭据环境变量**（缺失即跳过该源，不算故障）：`JQ_MOBILE`/`JQ_USERNAME` + `JQ_PASSWORD`（聚宽）、`RQDATA_USER`/`RQDATAC_USER` + `RQDATA_PASSWORD`/`RQDATAC_PASSWORD`、`RQDATA_TOKEN`（米筐）、`UQER_TOKEN`（优矿）、`TUSHARE_TOKEN`（Tushare）、`GM_TOKEN`（掘金，仅行情）；用 `python3 sentiment_sources.py` 查看逐源凭据与依赖状态。
- **CI 接线**：`.github/workflows/m.yml` 的三个 job（deploy / wechat / daily）都需在 `build_site.py` 之前生成 `sentiment_data.json`
  （先 `tools/probe_sentiment_apis.py --mock` 出评测矩阵（内部档案，不对外展示），再 `sentiment_factors.py --live`，取不到数据自动降级 `--mock`）。
  本次新增的 `python3 sentiment_match.py --self-test`（标的匹配 + 来源脱敏自检）需加进 deploy job 的「🧪 舆情层自检」步骤；
  若当前 GitHub 连接未授予 `workflows` 权限、CI 改动无法随 PR 推送，仓库内备好了补丁：`git apply docs/sentiment-ci-workflow.patch`
  后自行提交即可（不改 workflow 也不影响本地/境内执行器跑舆情因子与匹配展示）。
- **单源失败降级**：11 个源任一失败只把自己标成 `ok=false` 并计入 `summary.failed`，其余源继续供数；全源失败时温度计回退 50（中性）并标注 `degraded`，页面与推送照常构建。

## 结构

| 文件 | 说明 |
|---|---|
| `market_data.py` | **动态行情抓取**：多源回退抓取最新行情，生成 `market_data.json`（构建产物，不入库） |
| `sentiment_data.json` / `sentiment_history.json` | 舆情因子当日结果与新闻条数历史（供 `NEWS_HEAT_Z` 基线），均为构建产物，不入库 |
| `macro_data.py` | **宏观/财经快讯抓取**：8 个免密钥公开源（Google News RSS 中英分主题 / 美联储官方 RSS / 东财检索）→ 归一去重 → **时效过滤** → 按 02 栏五个小节归类，生成 `macro_data.json`（构建产物，不入库）；`--days` 收紧窗口、`--mock` 离线回放 `tests/fixtures/MACRO_MIX.json`、`--offline` 沿用上次结果、`--text` 输出 CI Step Summary；单源失败不阻断 |
| `tests/test_macro_data.py` | 快讯层测试（16 项，零联网）：RSS/JSONP 解析、跨源去重、分类路由（IMF+关税 必须落宏观而非大宗）、超窗与无日期拦截、`--mock` 输出契约 |
| `tests/test_wechat_push_macro.py` | 宏观快讯渲染回归（推送 02 栏 + 网页 02 节）：必须渲染当次快讯且每条带日期；快讯缺失时降级为「今日未获取」；网页 `MACROLIST` 注入幂等；正文/注入区禁止再出现 628.69 亿、8 月 12 日、25,440.17 等写死历史内容 |
| `community_data.py` | **动态社区抓取**：14 大社区 HTTP GET + 动态模板回退，生成 `community_data.json`（构建产物，不入库），每次刷新当天日期与研判正文 |
| `sentiment_sources.py` | **接口注册表**：11 个量化平台/公开源舆情·新闻因子的能力口径（端点、字段、时效、历史、额度、成本、局限）+ 因子定义 + 9 个评测阶段与 6 维评分权重；`python3 sentiment_sources.py` 打印清单与凭据/依赖状态 |
| `sentiment_adapters.py` | **接入适配器**：每源一个 `call_*`（live 取数）+ `parse_*`（报文 → 统一结构 `{news, series, meta}`），全部纯标准库；`--mode mock` 用 `tests/fixtures` 录制报文离线校验解析链路 |
| `sentiment_nlp.py` | **自建情感层**：中文金融词库 + 否定/程度修饰 + 时间衰减 → `score_text()`，`aggregate()` 合成 `NET_SENTI / NEG_SHARE / SENT_TEMP / EVENT_RISK`；`--self-test` 自检 |
| `sentiment_match.py` | **匹配 + 脱敏层（新增）**：日报标的/主题关键词表（与 `market_data.py` 同一套 key）、采集关键词 `search_keywords()`、`match_news()/build_matches()` 产出 `matches`、`redact()/status_line()/collection_summary()` 保证对外输出不显示来源；`--self-test` 自检 |
| `sentiment_factors.py` | **因子合成管线**：分层取数（平台现成因子优先 → 免费热度/文本 + 自建词库）→ `sentiment_data.json`（构建产物，不入库）；`--live` / `--mock` / `--offline`，任何源失败都不阻断 |
| `tools/probe_sentiment_apis.py` | **接入实测探针**：依赖→网络→鉴权→取数→字段→时效→覆盖→延迟→额度 9 阶段短路判定 + 100 分制打分 → `api_probe_report.json` 与 `docs/sentiment-api-eval.md` |
| `docs/sentiment-api-eval.md` | **评测矩阵（内部档案）**：结论速览 / 能力矩阵 / 评分明细 / 逐源明细，由探针自动生成；**不在网页与微信推送中展示**（对外不显示来源） |
| `tests/test_sentiment.py` | 舆情层测试（38 项，零联网）：`python3 -m unittest discover -s tests`；含「03B 对外输出不得出现任何来源痕迹」与「采集结果必须匹配到日报标的」两类回归 |
| `panorama.py` | **01 栏「每日全球全景扫描」推理引擎**：把当次的 `market_data.json` + `macro_data.json` + `sentiment_data.json` + `community_data.json` 合成为**推动股价的 5 大力量**（重点 / 次要 / 噪音 · 利好 / 利空 / 中性 · 0~100 力量分）、三大关注面小结（宏观事件 / 板块轮动 / 情绪变化）与**是否可以做多**的合成分结论；纯标准库纯函数、不联网不落盘，构建期由 `build_site.py` 与 `tools/wechat_push.py` 直接调用（**因此无需改 CI workflow**）。`python3 panorama.py` 打印文本摘要、`--json` 导出结构化结果、`--self-test` 规则自检 |
| `tests/test_panorama.py` | 01 栏回归（13 项，零联网）：5 大力量与栏目要素齐全、多/空/横盘三种行情结论必须不同、噪音不计入做多合成分、突发风险分下调做多结论、四路数据缺失时降级为「本栏不编故事」、网页 `PANORAMA` 注入幂等、旧栏目名与写死历史内容不得回归 |
| `build_site.py` | **动态建站**：把 `report.html` 模板中的 `{{占位符}}` 替换为最新行情/抓取日期/时间戳，把 `panorama.py` 的全景扫描注入 01 节 `<!-- PANORAMA -->` 占位区（哨兵 `<!-- /PANORAMA -->` 保证幂等），把 `community_data.json` 的 14 条最新研判注入 `<!-- COMMUNITY_LIST -->` 标记，把 `macro_data.json` 的快讯注入 02 节 `<!-- MACROLIST -->` 占位区（缺数据→「今日未获取」，回填哨兵 `<!-- /MACROLIST -->` 保证幂等），并把「因子读数 + 标的匹配（不含来源）」注入 `<!-- SENTIMENT_LIST -->` 标记 |
| `report.html` | 报告**模板源文件**（**电子杂志 × 电子墨水**风格 · 浅灰底 + 正文纯黑 + 深绿高对比标题 · 小字号竖版长页），内含"手动推送"按钮与 01 节 `<!-- PANORAMA -->`、`<!-- COMMUNITY_LIST:BEGIN/END -->`、02 节 `<!-- MACROLIST -->` 动态注入标记；仓库中始终保持模板版本，构建产物不提交（误提交构建产物时 `git checkout -- report.html` 恢复） |
| `tools/wechat_push.py` | 微信推送工具：读取 `market_data.json` + `community_data.json` 双动态数据，转为微信兼容的单页完整内联样式 HTML，经 PushPlus **一对多**群组推送（群组编码 `oai.1`）到微信 |
| `.github/workflows/m.yml` | CI：动态抓取行情+校验+社区+宏观快讯 → 动态建站（三注入） → 部署 Pages + 一键触发微信单页推送 + **每天北京时间 09:00 定时自动推送** |
| `docs/macro-ci-workflow.patch` | **待人工应用的 workflow 补丁**（GitHub App 无 `workflows` 权限）：三个 job 各加 `macro_data.py` 抓取步骤（失败不阻断、摘要进 Step Summary）+ `verify_quotes.py` 门禁（deploy 非阻断并公开 `verify_report.json`；wechat/daily FAIL 直接阻断推送） |

## 页面风格系统 (Style A · 电子杂志 × 电子墨水)

参考 [Guizang PPT Skill](https://github.com/op7418/guizang-ppt-skill) 的 **Style A「电子杂志 × 电子墨水」**，改造成适合微信阅读的竖版长页面。

- **视觉基调**：电子杂志 × 电子墨水 (Editorial Magazine × E-Ink)，像 *Monocle* 杂志贴上了代码。
- **字体系统**：全站使用黑体栈（SimHei / 微软雅黑 / 苹方 PingFang SC / Noto Sans SC），章节标题加粗纯黑，**全部字号偏小**（正文 12px 紧凑小字号）。
- **调色系统**：
  - 整体**浅灰色背景** `#eef0f2`
  - **正文纯黑** `#141414`
  - **标题深绿** `#007a35`（浅底高对比文字绿：对 `#f8f9fa` 约 5.2:1、对 `#eef0f2` 约 4.8:1，达 WCAG AA 4.5:1；原 `#00e05c` 荧光绿在浅底仅约 1.7:1，看不清，已弃用于浅底文字）
  - **重点字体荧光绿文字 + 黑色背景** `#000` / `#39ff14`（霓虹绿高亮，黑底场景如顶部/底部/黑底徽章）
  - 其余配搭均为深绿与黑色（按钮/Tab 激活态为深绿底 + 白字）。
- **标题与署名**：网页标题为「章鱼 AI 量化策略日报」，**微信推送标题为「章鱼 AI·全景分析（情绪因子分析）」**（推送卡片顶部大标题同步使用该名称），副标题「全网 AI 调研境内境外数据，由多个大模型混合部署」，**标题去除 pushplus 与时间戳**。正文末尾署名：**作者：章鱼 ai · 仅供参考，分析研究**，并附多模型协同说明。
- **01 节每日全球全景扫描**：栏目为「**每日全球全景扫描** (Daily Global Panorama Scan)」——扫一遍今天全球市场，总结**推动股价的 5 大力量**，重点关注**宏观事件 / 板块轮动 / 情绪变化**，逐条标注**哪些是重点、哪些是噪音**与**如何利好利空**，最后给出**是否可以做多**的结论。**网页与微信推送两端同步呈现**（`report.html` 的 `<!-- PANORAMA -->` 注入区与 `tools/wechat_push.py` 的 `panorama_block`），紧随其后仍保留章鱼 AI 量化策略说明块（`.quant-box` / `quant_block`，含「六大打造步骤」）。
- **01 节量化策略说明**：章鱼 AI 量化策略说明块（`.quant-box`）——包含量化交易优势说明及「章鱼 AI 量化策略六大打造步骤」（数据收集、数据清洗、建立因子、选股优化、历史回测、实盘运作）。**网页与微信推送两端同步呈现**（`report.html` 与 `tools/wechat_push.py` 的 `quant_block`）。

## 微信推送 (PushPlus · 一对多群组单页完整版 · 14 源动态)

- **推送标题**：「章鱼 AI·全景分析（情绪因子分析）」。三处保持同步 —— `tools/wechat_push.py` 的 `TITLE` 常量（命令行 `--push` / `--emit` / `--embed`）、`report.html` 内嵌负载 `wechat-parts` 的 `title`、网页按钮 `manualPush()` 的 `pushTitle`；推送卡片顶部大标题亦为同一名称。
- **一对多群组推送**：默认推送到 **`oai.1` 群组**，群内所有关注该群组的微信成员同步接收；需先在 PushPlus 后台「一对多推送」中创建群组编码 `oai.1`，成员扫码关注该群组后即可收推送。
- **页面只推一个微信页**：点击"手动推送"立即发送**单页完整微信卡片**，全篇 7 大章节与 14 大社区论坛研判一次性送达，无需拆条分发与 15s 等待。
- **⏰ 推送前时间核对**：每一次推送前均重新抓取行情+社区数据，并读取当前时间；标题与正文中的"生成时间 / 时间核对"等全部时间戳**实时刷新为最新时间**后再发送（网页按钮与命令行推送均已内置）。
- **📅 推送前频道最新内容核对**：**每一次推送都重新抓取并逐条检查** 14 个频道内容是否为频道最新（`community_data.py` 每次生成当天日期），不因当天已抓取过而复用历史结果；任一频道缺少「最新读取」标记、检查失败或结果非当天，**手动推送**拒绝推送；**定时推送** (`--scheduled`) 则仅警告不阻断，确保每天 09:00 定时任务可运行。
- **🧪 推送前全来源数据准确性校验** (`verify_quotes.py`)：**每一次推送前**对 `market_data.json` 全部 11 个标的做 **Yahoo 官方口径 × Stooq 实时 × Stooq 历史日线重算 × ECB 汇率** 多来源交叉校验——内部自洽 (涨跌额/涨跌幅 ↔ last/prev_close)、行情日期健全性（不超前/不陈旧）、点位与涨跌幅逐源比对；**≥2 个独立来源族彼此一致但与流水线矛盾、或与主源官方口径矛盾即判定 FAIL 并阻断推送** (CI 中 FAIL 时工作流直接终止，绝不把错误数字推给读者)。单源不可达仅告警不阻断，校验报告公开在 `_site/verify_report.json`。背景：2026-09-16 恒指当日 +0.19% 曾被误算成 −2.22% 并推送，本机制保证同类错误在推送前被拦截。命令行可用 `--skip-verify` 跳过（不推荐）、`--verify-strict` 收紧为 WARN 也阻断。
  > ⚠️ 推送门禁内置于 `wechat_push.py --push`（FAIL 即 exit 5，不依赖任何工作流改动即生效）。CI 侧的
  > fail-fast 校验步骤与 `verify_report.json` 公开因 GitHub App 凭证无 `workflows` 权限，改以补丁交付：
  > `git apply docs/macro-ci-workflow.patch` 后生效（三处：wechat/daily 任务抓取行情后的**阻断式**校验、
  > deploy 任务的 `|| true` **非阻断**校验 + `_site/verify_report.json` 随站点公开）。
- **命令行推送**：`python3 tools/wechat_push.py --push`
- **定时自动推送**：`python3 tools/wechat_push.py --push --scheduled`
- **验证转换效果**：`python3 tools/wechat_push.py --dry-run`
- **重新内嵌内容**：报告更新后，运行 `python3 tools/wechat_push.py --embed`（幂等）。

Token 维护在 `report.html` 的 `PUSHPLUS_TOKEN` 常量中，网页按钮与推送工具共用。群组编码 `PUSHPLUS_TOPIC` 默认为 `'oai.1'`（一对多群组推送，网页按钮与命令行工具共用该常量）；如需改回一对一专属推送，将其留空 `''` 即可。

## ⏰ 每天北京时间早上九点自动推送

`.github/workflows/m.yml` 内置 `schedule` 定时任务（UTC `0 1 * * *`，即**北京时间每天 09:00**），自动执行「动态抓取行情+社区 → 动态建站 → `python3 tools/wechat_push.py --push --scheduled`」，无需手动操作即可把最新全景报告推送到微信，同时重新部署 Pages 站点。

> 提示：GitHub Actions 定时任务存在少量延迟属正常现象；若需精确到秒的定时，可结合仓库 Secrets (PUSHPLUS_TOKEN) 与外部 Cron 服务。

## 🐛 本次修复：红圈旧数据问题

- **问题**：截图红圈显示 14 个社区正文仍是“8 月 12 日”旧数据，仅 `{{CD_xx}}` 日期占位符刷新，社区研判正文未动态。
- **根因**：`report.html` 与 `tools/wechat_push.py` 中社区内容为硬编码静态文本，未接入动态管线。
- **修复**：
  1. 新增 `community_data.py`：14 源每次构建 HTTP GET + 动态模板回退，生成 `community_data.json`，正文日期永远为当天（如 8 月 30 日），包含现场抓取片段。
  2. `build_site.py` 支持双动态：加载 `community_data.json`，通过 `<!-- COMMUNITY_LIST:BEGIN/END -->` 标记动态注入 14 个社区卡片，覆盖旧静态内容。
  3. `tools/wechat_push.py` 支持双动态：优先读取 `community_data.json`，否则回退到动态模板（日期已刷新为当天），并统一刷新“最新读取”日期。
  4. `.github/workflows/m.yml` 增加 `community_data.py` 步骤，CI 每次自动抓取 14 社区。
  5. `report.html` 模板增加注入标记，保留 `{{CD_xx}}` 占位符兼容旧逻辑。
- **验证**：`python3 market_data.py --demo && python3 community_data.py --demo && python3 build_site.py` 后，`report.html` 中 14 个社区正文均为“8 月 30 日”当天，`最新读取 2026-08-30`，微信推送同理。
