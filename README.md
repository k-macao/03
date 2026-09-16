# 03 — 章鱼 AI 量化策略日报 (Editorial E-Ink Edition)

自动生成的分析报告站点: <https://k-macao.github.io/03/>

## 🔄 动态抓取真正上线 — 行情+社区双动态 (每次构建/推送自动更新)

每次 push、手动触发或每天 09:00 定时任务，都会**先自动抓取最新行情+14 大社区最新研判，再构建报告并推送**，
页面与微信收到的永远是当天最新数据，杜绝“8 月 12 日”旧内容残留：

```bash
python3 market_data.py               # ① 动态抓取行情 + 6个月日线技术面 → market_data.json (Yahoo→Stooq回退)
python3 macro_data.py                # ② 动态抓取宏观 → macro_data.json (FRED/世界银行/东方财富 + 人工维护项，离线可 --mock)
python3 community_data.py            # ③ 动态抓取14社区 → community_data.json (HTTP GET+模板回退，正文引用①②的实算事实)
python3 build_site.py                # ④ 动态建站 → report.html (注入行情+宏观+时效核对表+社区+核心结论)
python3 tools/wechat_push.py --embed # ⑤ 内嵌最新推送负载进 report.html
python3 tools/wechat_push.py --push --scheduled   # ⑥ 推送完整报告到微信（推送前过真时效护栏）
```

- **行情源**：Yahoo Finance chart API → Stooq CSV 多源自动回退（纯标准库，CI 无需安装依赖）。
- **社区源**：14 大社区（富途牛牛/雪球/老虎/东方财富/智通财经/华尔街见闻/香港讨论区/LIHKG/韭圈儿/蚂蚁财富/Reddit/TradingView/VIC/FinTwit）**每次构建均 HTTP GET 尝试抓取**，提取文本片段作为活数据佐证，结合最新行情动态生成研判；单源失败自动降级为基于最新行情的动态模板，保证 14 源永远齐全，**正文日期永远为当天**。
- **覆盖标的**：恒指 / 恒生科技 / 恒生国企 / 标普 500 / 纳斯达克 / 道琼斯 / 现货黄金 / WTI / 布伦特 / 美元离岸与在岸人民币。
- **失败降级**：单品行情/单社区抓取失败自动降级（行情显示 "—"，社区显示动态模板），并在页面标注，**不阻断构建与推送**，保证 09:00 定时任务永不中断。
- **日期联动**：14 大社区「最新读取」日期与正文中的“8 月 X 日”日期均随抓取日自动刷新（`community_data.py` 生成当天日期），推送前日期核对（`--push` 严格 / `--scheduled` 宽松）逻辑保持不变。
- 本地联调可用 `python3 market_data.py --demo && python3 community_data.py --demo` 生成模拟行情+社区。

## 🌍 02 节全球经济与财经动态 — 去固化 + 真时效护栏

**过去的问题**：`02 / 全球经济与财经动态` 整节是写死的文案（美债 4.67%、南向净买入 628.69 亿、中国 CPI 0.5%、
恒指 25,440.17 / RSI 72.58 / 箱体 25,200–25,400 / 止损 25,124 / 街货比 49:51 / 大行目标 31,000 …），
日期占位符会刷新但数字永远不变；推送前的"日期核对"比较的是同一份数据的日期，**恒真**，等于没有护栏；
网页端甚至完全没有这一节。

**现在的做法**：数据、渲染、护栏三层分离，网页与微信推送共用同一份渲染器。

| 层 | 文件 | 职责 |
|---|---|---|
| 取数 | `macro_data.py` | 9 项指标：FRED（联邦基金区间 / CPI / 核心 CPI / 非农 / 10 年期 / 铜）、东方财富数据中心（中国 CPI、港股通成交额）、世界银行（全球实际 GDP 增速）；每项带 `value / display / as_of / source / freq / max_age_days / status / age_days`。取不到 → `status=missing` + `error`，**不回填旧值** |
| 取数 | `market_data.py` | 11 项行情 + **动态技术面**（6 个月日线实算 EMA9/21、MA50、RSI14、近 20 日箱体、5 日/1 月/3 月涨跌），写进 `quotes[key]['tech']`，技术位不再写死 |
| 人工项 | `macro_manual_inputs.json` | 无免费公开接口的 4 项（IMF WEO 预测 / 碳酸锂 / 大行目标价 / 地缘判断），**每项必须带 `as_of` 与 `max_age_days`**；超期自动判 `stale` 并在正文打标，改数据不用改代码 |
| 渲染 | `macro_render.py` | `build_blocks()` → `render_web()` / `render_wechat()` 双端同源；`verdict_items()` 供 07 节核心结论共用；`freshness_report()` + `scan_narrative_dates()` 是护栏 |
| 消费 | `community_data.py` / `build_site.py` / `tools/wechat_push.py` | 14 社区模板、网页 02/07 节、微信 02/07 节全部只引用上述数据，缺项写「未取到」 |

**时效护栏（真核对，取代恒真校验）**

- 频率上限：日频 7 天 / 月频 45 天（按**观测期最后一天**算，避免把正常公布节奏误判为陈旧）/ 年频 400 天 / 人工项各自上限。
- `mode=mock|demo|offline` 的数据层一律判 `stale`，**不得冒充实时抓取**。
- 陈旧项在正文强制打 `⚠️ 数据陈旧 · 截至 X（N 天前，上限 M 天）`；缺失项直接不渲染断言。
- 渲染后再扫一遍正文里的中文绝对日期（`scan_narrative_dates`），超过 45 天的过期叙事（如"8 月 20 日阿里业绩"）会被揪出来。
- 推送：`--push` 严格模式命中即 **退出码 6 拒绝推送**；`--push --scheduled`（09:00 定时）只警告不中断；`--allow-stale` 为知情放行，正文仍保留 ⚠️ 标注。
- 网页 02 节顶部同步渲染**时效核对表**（逐项 `as_of` / 龄期 / 上限 / 状态 / 判定依据），不再声称"正文所有时间戳均为最新"。

**诚实性约定**：港股通单日净买入额自 2024-08 起官方停止公布（接口返回 `null`），本报告只引用成交额，
**永不编造"南向净买入 XXX 亿"**；取不到的数据一律写「未取到」，不用旧值兜底、不冒充当天。

```bash
python3 macro_data.py                 # 联网抓取（FRED / 世界银行 / 东方财富）
python3 macro_data.py --mock          # 离线回放 tests/fixtures/MACRO_*（CI 降级路径，标记 mode=mock 并判陈旧）
python3 -m unittest tests.test_macro  # 56 项宏观层测试（零联网）
```

## 🗞️ 舆情 / 新闻因子层 — 量化平台现成因子接入实测（聚宽 · 米筐 · 掘金 · 优矿）

社区热评是"印象"，量化要的是**可回测的因子**。本层专门实测境内主流量化平台是否提供**现成的舆情 / 新闻情感因子接口**，
并把取到的数据合成成 5 个可直接入模的因子，接入同一条日报管线（页面 03B 节 + 微信 03B 节点）：

```bash
python3 tools/probe_sentiment_apis.py --mock     # ① 接口接入实测 + 6 维打分 → api_probe_report.json + docs/sentiment-api-eval.md
python3 sentiment_nlp.py --self-test             # ② 自建中文金融词库自检（否定/程度/风险词规则）
python3 sentiment_adapters.py --mode mock        # ③ 11 个接口逐个解析校验（零联网）
python3 sentiment_factors.py --mock              # ④ 离线回放合成因子 → sentiment_data.json（CI/本地默认用这条）
python3 sentiment_factors.py --live              # ④′ 境内出口 + 凭据的联网实测（优先平台现成因子，缺失时自动降级）
python3 build_site.py                            # ⑤ 建站时把舆情因子注入 report.html 的 <!-- SENTIMENT_LIST --> 标记
```

- **因子口径**：`NET_SENTI` 净情感强度 = Σ(情感×权重)/Σ权重 ∈[-1,1]；`NEG_SHARE` 负面舆情占比；
  `NEWS_HEAT_Z` 新闻热度 Z 值（今日条数对近 20 日均值标准化）；`SENT_TEMP` 市场舆情温度计 = 50+35·net+12·tanh(z/2)−18·neg_share ∈[0,100]（≥72 极度亢奋 / ≥60 偏热 / ≥45 中性 / ≥32 偏冷 / ≥20 恐慌）；`EVENT_RISK` 突发事件风险分（立案/处罚/造假/违约…加权，截断 0-100）。
- **打分规则可解释**：命中金融情感词按词权计分 → 程度副词乘权（大幅×1.5 / 小幅×0.7…）→ 否定字（不未无没非失否难）在情感词前 3 字内则极性翻转打 8 折 → 按发布时间 24h 半衰期指数衰减加权；平台已给 `sentiment` 时**优先采用平台口径**（结果里标 `source_provided`），纯标准库、可复现。
- **实测结论（详见 `docs/sentiment-api-eval.md`）**：

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
  （先 `tools/probe_sentiment_apis.py --mock` 出评测矩阵，再 `sentiment_factors.py --live`，取不到数据自动降级 `--mock`）。
  若当前 GitHub 连接未授予 `workflows` 权限、CI 改动无法随 PR 推送，仓库内备好了补丁：`git apply docs/sentiment-ci-workflow.patch`
  后自行提交即可（不改 workflow 也不影响本地/境内执行器跑舆情因子）。
- **单源失败降级**：11 个源任一失败只把自己标成 `ok=false` 并计入 `summary.failed`，其余源继续供数；全源失败时温度计回退 50（中性）并标注 `degraded`，页面与推送照常构建。

## 结构

| 文件 | 说明 |
|---|---|
| `market_data.py` | **动态行情抓取**：多源回退抓取最新行情，生成 `market_data.json`（构建产物，不入库） |
| `macro_data.py` | **动态宏观抓取**：FRED / 世界银行 / 东方财富 9 项指标 + 人工维护项 + 事件日历 → `macro_data.json`（构建产物，不入库）；每项带 `as_of` 与频率上限，`--mock` 可离线回放 fixtures |
| `macro_manual_inputs.json` | **人工维护输入**（入库）：IMF WEO / 碳酸锂 / 大行目标价 / 地缘判断，每项必须带 `as_of` + `max_age_days`，超期自动判陈旧 |
| `macro_render.py` | **共享渲染器 + 时效护栏**：`build_blocks` / `render_web` / `render_wechat` / `verdict_items` / `freshness_report` / `scan_narrative_dates`，网页与微信同源同口径 |
| `sentiment_data.json` / `sentiment_history.json` | 舆情因子当日结果与新闻条数历史（供 `NEWS_HEAT_Z` 基线），均为构建产物，不入库 |
| `community_data.py` | **动态社区抓取**：14 大社区 HTTP GET + 动态模板回退，生成 `community_data.json`（构建产物，不入库），每次刷新当天日期与研判正文 |
| `sentiment_sources.py` | **接口注册表**：11 个量化平台/公开源舆情·新闻因子的能力口径（端点、字段、时效、历史、额度、成本、局限）+ 因子定义 + 9 个评测阶段与 6 维评分权重；`python3 sentiment_sources.py` 打印清单与凭据/依赖状态 |
| `sentiment_adapters.py` | **接入适配器**：每源一个 `call_*`（live 取数）+ `parse_*`（报文 → 统一结构 `{news, series, meta}`），全部纯标准库；`--mode mock` 用 `tests/fixtures` 录制报文离线校验解析链路 |
| `sentiment_nlp.py` | **自建情感层**：中文金融词库 + 否定/程度修饰 + 时间衰减 → `score_text()`，`aggregate()` 合成 `NET_SENTI / NEG_SHARE / SENT_TEMP / EVENT_RISK`；`--self-test` 自检 |
| `sentiment_factors.py` | **因子合成管线**：分层取数（平台现成因子优先 → 免费热度/文本 + 自建词库）→ `sentiment_data.json`（构建产物，不入库）；`--live` / `--mock` / `--offline`，任何源失败都不阻断 |
| `tools/probe_sentiment_apis.py` | **接入实测探针**：依赖→网络→鉴权→取数→字段→时效→覆盖→延迟→额度 9 阶段短路判定 + 100 分制打分 → `api_probe_report.json` 与 `docs/sentiment-api-eval.md` |
| `docs/sentiment-api-eval.md` | **评测矩阵**（可提交的结论文档）：结论速览 / 能力矩阵 / 评分明细 / 逐源明细，由探针自动生成 |
| `tests/test_sentiment.py` | 舆情层测试（30 项，零联网）：`python3 -m unittest discover -s tests` |
| `tests/test_macro.py` | 宏观层测试（56 项，零联网）：取数 → 时效计算 → 渲染无写死值 → 护栏拦截 → 网页注入 → 社区降级文案 |
| `build_site.py` | **动态建站**：把 `report.html` 模板中的 `{{占位符}}` 替换为最新行情/抓取日期/时间戳（含 `{{FILTER_*}}` 社区家数），并把 14 条社区研判注入 `<!-- COMMUNITY_LIST -->`、02 节宏观层注入 `<!-- MACRO_BLOCK -->`、时效核对表注入 `<!-- FRESHNESS_BLOCK -->`、07 节核心结论注入 `<!-- VERDICT_LIST -->` |
| `report.html` | 报告**模板源文件**（**电子杂志 × 电子墨水**风格 · 浅灰底 + 正文纯黑 + 深绿高对比标题 · 小字号竖版长页），内含"手动推送"按钮与 `<!-- COMMUNITY_LIST -->` / `<!-- MACRO_BLOCK -->` / `<!-- FRESHNESS_BLOCK -->` / `<!-- VERDICT_LIST -->` 四组动态注入标记；**模板里不保留任何静态数据文案**（03 节静态卡片与内嵌推送快照已清空为占位说明），仓库中始终保持模板版本，构建产物不提交（误提交构建产物时 `git checkout -- report.html` 恢复） |
| `tools/wechat_push.py` | 微信推送工具：读取 `market_data.json` + `macro_data.json` + `community_data.json` + `sentiment_data.json`，转为微信兼容的单页完整内联样式 HTML，经 PushPlus **一对多**群组推送（群组编码 `oai.1`）；推送前过 `assert_content_freshness()` 真护栏（严格模式命中退出码 6），社区数据缺失时复用 `community_data.py` 的同一套模板，不再内嵌第二份写死文案 |
| `.github/workflows/m.yml` | CI：动态抓取行情+宏观+社区+舆情 → 动态建站（四注入） → 部署 Pages + 一键触发微信单页推送 + **每天北京时间 09:00 定时自动推送**；`macro_data.py` 联网失败自动降级 `--mock`（fixtures 回放，正文标注陈旧） |

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
- **01 节量化策略说明**：替换为章鱼 AI 量化策略说明块（`.quant-box`）——包含量化交易优势说明及「章鱼 AI 量化策略六大打造步骤」（数据收集、数据清洗、建立因子、选股优化、历史回测、实盘运作）。**网页与微信推送两端同步呈现**（`report.html` 与 `tools/wechat_push.py` 的 `quant_block`）。

## 微信推送 (PushPlus · 一对多群组单页完整版 · 14 源动态)

- **推送标题**：「章鱼 AI·全景分析（情绪因子分析）」。三处保持同步 —— `tools/wechat_push.py` 的 `TITLE` 常量（命令行 `--push` / `--emit` / `--embed`）、`report.html` 内嵌负载 `wechat-parts` 的 `title`、网页按钮 `manualPush()` 的 `pushTitle`；推送卡片顶部大标题亦为同一名称。
- **一对多群组推送**：默认推送到 **`oai.1` 群组**，群内所有关注该群组的微信成员同步接收；需先在 PushPlus 后台「一对多推送」中创建群组编码 `oai.1`，成员扫码关注该群组后即可收推送。
- **页面只推一个微信页**：点击"手动推送"立即发送**单页完整微信卡片**，全篇 7 大章节与 14 大社区论坛研判一次性送达，无需拆条分发与 15s 等待。
- **⏰ 推送前时间核对**：每一次推送前均重新抓取行情+社区数据，并读取当前时间；标题与正文中的"生成时间 / 时间核对"等全部时间戳**实时刷新为最新时间**后再发送（网页按钮与命令行推送均已内置）。
- **📅 推送前频道最新内容核对**：**每一次推送都重新抓取并逐条检查** 14 个频道内容是否为频道最新（`community_data.py` 每次生成当天日期），不因当天已抓取过而复用历史结果；任一频道缺少「最新读取」标记、检查失败或结果非当天，**手动推送**拒绝推送；**定时推送** (`--scheduled`) 则仅警告不阻断，确保每天 09:00 定时任务可运行。
- **命令行推送**：`python3 tools/wechat_push.py --push`
- **定时自动推送**：`python3 tools/wechat_push.py --push --scheduled`
- **验证转换效果**：`python3 tools/wechat_push.py --dry-run`
- **重新内嵌内容**：报告更新后，运行 `python3 tools/wechat_push.py --embed`（幂等）。

Token 维护在 `report.html` 的 `PUSHPLUS_TOKEN` 常量中，网页按钮与推送工具共用。群组编码 `PUSHPLUS_TOPIC` 默认为 `'oai.1'`（一对多群组推送，网页按钮与命令行工具共用该常量）；如需改回一对一专属推送，将其留空 `''` 即可。

## ⏰ 每天北京时间早上九点自动推送

`.github/workflows/m.yml` 内置 `schedule` 定时任务（UTC `0 1 * * *`，即**北京时间每天 09:00**），自动执行「动态抓取行情+社区 → 动态建站 → `python3 tools/wechat_push.py --push --scheduled`」，无需手动操作即可把最新全景报告推送到微信，同时重新部署 Pages 站点。

> 提示：GitHub Actions 定时任务存在少量延迟属正常现象；若需精确到秒的定时，可结合仓库 Secrets (PUSHPLUS_TOKEN) 与外部 Cron 服务。

## 🐛 修复记录二：02 节全球经济与财经动态整节固化

- **问题**：`02 / 全球经济与财经动态` 与 `07 / 核心结论` 的数字全部写死（美债 4.67%、南向 628.69 亿、CPI 0.5%、
  恒指 25,440.17、RSI 72.58、EMA 25,978/25,471、箱体 25,200–25,400、止损 25,124、街货比 49:51、目标 31,000），
  只有日期在动；网页端根本没有 02 节；推送前的日期校验恒真。
- **根因**：宏观数据没有取数层，正文直接写文案；网页与推送各写一套模板，护栏形同虚设。
- **修复**：
  1. 新增 `macro_data.py`（9 项指标 + 事件日历）与 `macro_manual_inputs.json`（4 项人工维护项，必带 vintage）。
  2. 新增 `macro_render.py`：网页/微信**共用**渲染器 + `freshness_report()` 真护栏 + `scan_narrative_dates()` 过期叙事扫描。
  3. `market_data.py` 增加动态技术面层（EMA / RSI / MA50 / 近 20 日箱体 / 多周期涨跌），技术位不再写死。
  4. `report.html` 新增 `02 / 全球经济与财经动态` 节（`MACRO_BLOCK` + `FRESHNESS_BLOCK` 标记）与 07 节 `VERDICT_LIST` 标记；
     原 `02 / 行情快照` 顺延为 `02B`；清空 03 节静态社区卡片与内嵌推送旧快照（改为占位说明，构建时注入）。
  5. `build_site.py` 增加 `--macro` 参数与三处注入；`tools/wechat_push.py` 改为 `assert_content_freshness()` 真核对
     （严格模式退出码 6 / `--scheduled` 仅警告 / `--allow-stale` 知情放行），社区回退复用 `community_data.py` 模板。
  6. `community_data.py` 14 套引语与研判模板全部改为引用实算事实；行情缺失走**降级模板**（只说明缺什么 + 列出仍取到的宏观事实），
     不再套用富模板产出破句，也不再默认"窄幅震荡"。
  7. `.github/workflows/m.yml` 三个 job 均增加 `macro_data.py` 步骤（联网失败降级 `--mock`），
     `community_data.py` 显式传 `--macro-data`；`.gitignore` 忽略 `macro_data.json`。
     > ⚠️ **workflow 改动需单独应用**：GitHub App 默认无 `workflows` 权限，无法推送 `.github/workflows/` 下的文件。
     > 该改动已导出为补丁 `docs/ci-macro-step.patch`，请由有权限的账号执行：
     > `git apply docs/ci-macro-step.patch && git commit -am "ci: 增加 macro_data.py 步骤" && git push`
     > （或在 Arena 里为 GitHub 连接开启 `workflows` 权限后重推）。未应用补丁时 CI 仍可运行，
     > 但 02 节会走"宏观数据缺失"降级路径，页面显式写「未取到」而不会显示旧数字。
  8. 新增 `tests/test_macro.py`（56 项）：把上述约束固化为回归测试，任何写死值回潮都会红。
- **验证**：`python3 macro_data.py --mock && python3 build_site.py --out /tmp/x.html && python3 tools/wechat_push.py --dry-run`；
  `python3 -m unittest discover -s tests` → 86 项全绿。

## 🐛 修复记录一：红圈旧数据问题

- **问题**：截图红圈显示 14 个社区正文仍是“8 月 12 日”旧数据，仅 `{{CD_xx}}` 日期占位符刷新，社区研判正文未动态。
- **根因**：`report.html` 与 `tools/wechat_push.py` 中社区内容为硬编码静态文本，未接入动态管线。
- **修复**：
  1. 新增 `community_data.py`：14 源每次构建 HTTP GET + 动态模板回退，生成 `community_data.json`，正文日期永远为当天（如 8 月 30 日），包含现场抓取片段。
  2. `build_site.py` 支持双动态：加载 `community_data.json`，通过 `<!-- COMMUNITY_LIST:BEGIN/END -->` 标记动态注入 14 个社区卡片，覆盖旧静态内容。
  3. `tools/wechat_push.py` 支持双动态：优先读取 `community_data.json`，否则回退到动态模板（日期已刷新为当天），并统一刷新“最新读取”日期。
  4. `.github/workflows/m.yml` 增加 `community_data.py` 步骤，CI 每次自动抓取 14 社区。
  5. `report.html` 模板增加注入标记，保留 `{{CD_xx}}` 占位符兼容旧逻辑。
- **验证**：`python3 market_data.py --demo && python3 community_data.py --demo && python3 build_site.py` 后，`report.html` 中 14 个社区正文均为“8 月 30 日”当天，`最新读取 2026-08-30`，微信推送同理。
