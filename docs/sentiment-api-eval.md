# 量化平台「现成舆情 / 新闻因子」API 接入评测

> 生成时间：2026-09-17 02:10:58 UTC　·　运行模式：**离线回放 mock（文档基线）**　·　数据源：11 个　·　由 `tools/probe_sentiment_apis.py` 自动生成，请勿手工编辑

> **对外展示策略（内部档案）**：本文件不在网页与微信推送中展示 —— 03B 节**不渲染**该评测矩阵，且**不显示数据来源平台**（平台名 / 接口 ID / 域名 / 凭据与依赖提示由 `sentiment_match.redact()` 统一遮成「量化平台」，逐源明细表默认不出）。对外只展示采集合成后的因子读数与「舆情因子 × 日报标的」匹配结果。临时恢复内部视图：`SENTIMENT_SHOW_API_EVAL=1`（评测矩阵）、`SENTIMENT_SHOW_SOURCE=1`（来源明细）。

## 一、结论速览

| 排名 | 平台 / 接口 | 现成因子 | 时效 | 评分 | 接入判定 |
|---:|---|---|---|---:|---|
| 1 | **东方财富（免费公开）** · 千股千评：用户关注指数 / 机构参与度 / 综合得分 | attention_heat | 交易日日更 | 78 | 部分可用（需自建清洗或 NLP） |
| 2 | **数库 Chinascope（免费公开）** · A 股新闻情绪指数（市场级，日更） | news_sentiment | 交易日日更（akshare 同源实现口径） | 73 | 可直接接入 |
| 3 | **米筐 RiceQuant** · RQData HTTP/WebSocket 接口（舆情同源，机构合同开通） | news_sentiment | 同 RQ_SDK | 68 | 可接入（需开权限/付费） |
| 4 | **金十数据（免费公开）** · 微博舆情报告（个股讨论人气排行指数） | attention_heat | 小时级（2/6/12/24 小时窗口） | 68 | 部分可用（需自建清洗或 NLP） |
| 5 | **米筐 RiceQuant** · RQData 新闻舆情数据 news.get_stock_news（真·现成舆情因子） | news_sentiment | 日内每 30 分钟更新（正式数据） | 67 | 待实测 |
| 6 | **优矿 Uqer（通联数据）** · DataAPI 新闻情感/热度指数（现成舆情因子最完整） | news_sentiment + attention_heat | 情感/热度指数按日更新；新闻明细实时更新 | 67 | 可接入（需开权限/付费） |
| 7 | **东方财富（免费公开）** · search-api 个股新闻检索（关键词 → 标题 + 摘要） | news_text | 准实时 | 66 | 部分可用（需自建清洗或 NLP） |
| 8 | **Tushare Pro** · news / major_news / cctv_news 新闻文本接口 | news_text | 准实时（分钟级入库） | 58 | 部分可用（需自建清洗或 NLP） |
| 9 | **聚宽 JoinQuant** · jqdatasdk 本地 SDK（因子库 + finance 舆情表） | price_volume_sentiment + news_text | 因子 T+1 日更；新闻联播每日 20:30 前 | 50 | 待实测 |
| 10 | **聚宽 JoinQuant** · JQData 旧版 HTTP 数据接口 | price_volume_sentiment + attention_heat | 因子 T+1 日 05:00 前；雪球热度日 03:00 前；新闻联播日 20:30 前 | 39 | 部分可用（需自建清洗或 NLP） |
| 11 | **掘金量化 Myquant** · 掘金 gm.api 数据接口（无舆情因子，需终端代理） | none | 行情实时（tick/分钟）；财务按报告期 | 30 | 平台不提供该能力 |

**推荐接入顺序（本日报场景）**

1. `EM_COMMENT`（东方财富（免费公开））— 与米筐"舆情大数据（东财股吧，2007-10 至今，天度/小时情绪指数 + 热度因子）"同源，可作机构版权益的热度替代。
2. `CHINASCOPE`（数库 Chinascope（免费公开））— 数库基于每日数十万篇财经新闻做情感识别（SmarTag：7 大新闻标签 + 2 大新闻情绪维度），并与 J.P. Morgan 亚太量化团队共建情绪指数
3. `RQ_HTTP`（米筐 RiceQuant）— 若已签 RQData，优先走 HTTP：CI 免装 rqdatac，且与本项目"纯标准库"约束一致。
4. `JIN10_WEIBO`（金十数据（免费公开））— 小时级热度是"舆情异动预警"的极佳补充，但只有热度没有极性。
5. `UQER_HTTP`（优矿 Uqer（通联数据））— sentimentIndex = 当日关联新闻情感均值、heatIndex = 新闻热度，两个数即可直接入模

**三条硬约束（实测踩坑，直接影响架构选择）**

1. **境内出口**：聚宽/米筐等站点按 IP 拒绝境外访问，GitHub 海外 runner 直连必失败 → 舆情抓取放境内执行器，海外 runner 只做建站与推送；
2. **聚宽权限**：试用账号「因子和特色数据 = 无」，情绪因子 / 雪球热度 / 新闻联播属特色数据，需标准版以上（2 亿条/天）；且官方已标注旧版 HTTP 接口「不再维护，随时可能下线」；
3. **掘金无舆情**：`gm.api` 只有行情/财务/成分/日历/估值，且 SDK 依赖本地掘金终端代理（CI 不可用）—— 舆情必须外挂，掘金只当行情与执行通道。

## 二、能力矩阵

| 源 | 平台 | 接入方式 | 关键字段 / 方法 | 更新频率 | 历史 | 额度 | 成本与权限 |
|---|---|---|---|---|---|---|---|
| `EM_COMMENT` | 东方财富（免费公开） | http_free | 全市场: SECURITY_CODE, SECURITY_NAME_ABBR, TRADE_DATE, MARKET_FOCUS(关注指数), ORG_PARTICIPATE(机构参与度), TOTAL_SCORE(综合得分)<br>个股历史: TRADE_DATE, MARKET_FOCUS / ORG_PARTICIPATE / TOTAL_SCORE | 交易日日更 | 全市场单日快照；个股序列约 30 条/页 | pageSize ≤ 500；无限额文档，需自带重试与限速 | 免费公开 |
| `CHINASCOPE` | 数库 Chinascope（免费公开） | http_free | 返回字段: tradeDate（日期）, maIndex1（市场情绪指数）, marketClose（沪深300） | 交易日日更（akshare 同源实现口径） | 接口返回近一年 | 无鉴权、无文档化限额；作兜底建议 ≤ 1 次/日 + 本地缓存 | 免费公开 |
| `RQ_HTTP` | 米筐 RiceQuant | http | — | 同 RQ_SDK | 2017 至今 | 按合同 | 机构订阅制 |
| `JIN10_WEIBO` | 金十数据（免费公开） | http_free | 返回字段: 股票代码/简称, 微博人气排行指数, 区间涨幅 | 小时级（2/6/12/24 小时窗口） | 滚动窗口，不留长历史 | 需带 x-app-id / x-version 等浏览器头（akshare 同源），无正式配额 | 免费公开 |
| `RQ_SDK` | 米筐 RiceQuant | python_sdk | news.get_stock_news: news_id, title, original_time, url, source, news_emotion_indicator, news_neutral_weight, news_positive_weight, news_negative_weight, company_relevance, company_emotion_indicator, company_neutral_weig | 日内每 30 分钟更新（正式数据） | 2017 至今 | 按订阅数据包授权；股票数 × 区间长度需分批（文档未给硬性条数上限，实测补） | 机构订阅制，需商务开通舆情数据包；个人/高校版通常不含舆情 |
| `UQER_HTTP` | 优矿 Uqer（通联数据） | http | NewsSentimentIndexGet: secID, tradeDate, sentimentIndex<br>NewsHeatIndexGet: secID, tradeDate, heatIndex<br>NewsByTickersGet: newsID, title, source, publishTime, insertTime, secID | 情感/热度指数按日更新；新闻明细实时更新 | 指数自 2004-10-28 起（2014-01-01 起来源完整、统计有效） | 按 token 限速；单次批量 secID 建议 ≤ 300 只（需实测） | 标准版免费（约 200 基础因子）；特色/大数据因子需专业版，第三方源另计费 |
| `EM_NEWS` | 东方财富（免费公开） | http_free | 返回字段: date, title, content, mediaName, code | 准实时 | 最近约 100 条滚动 | pageSize 建议 ≤ 20；无鉴权但可能要求浏览器 UA / Cookie（akshare 实现带固定 cookie） | 免费公开 |
| `TUSHARE_NEWS` | Tushare Pro | http | news: datetime, title, content, src<br>major_news: pub_time, title, content, src_site<br>src 可选值: sina, wallstreetcn, 10jqka, eastmoney, yuncaijing, fenghuang, jinrongjie, cls, yicai | 准实时（分钟级入库） | news 6 年以上；major_news 8 年以上 | news 单次最大 1500 条；major_news 单次 400 行，可循环补历史 | 需单独开权限（与积分无关）；互动易/上证 e 互动 120 积分可试用、10000 积分正式 |
| `JQ_SDK` | 聚宽 JoinQuant | python_sdk | get_factor_values: securities, factors, start_date, end_date, count<br>舆情表: finance.CCTV_NEWS（新闻联播文字稿）, 雪球热度数据, 百度指数因子（付费特色数据） | 因子 T+1 日更；新闻联播每日 20:30 前 | 2005 至今（因子）/ 2009-06 至今（新闻联播） | auth 后 get_query_count() 直接返回剩余条数 —— 配额探针可零成本实现 | 同上：因子与舆情属特色数据，需付费版本 |
| `JQ_HTTP` | 聚宽 JoinQuant | http | 因子库·情绪类: VOL5, VOL10, VOL20, VOL60, VOL120, AR, BR, ARBR, VEMA5, DAVOL5, DAVOL10, ATR6, ATR14<br>舆情·雪球热度: 热度值（2015 至今，每日 03:00 前更新）<br>舆情·新闻联播: finance.CCTV_NEWS 文本表（2009-06 至今，每日 20:30 前更新） | 因子 T+1 日 05:00 前；雪球热度日 03:00 前；新闻联播日 20:30 前 | 因子 2005 至今；雪球热度 2015 至今；新闻联播 2009-06 至今 | 试用 100 万条/天、并发 3；正式版约 2 亿条/天（get_query_count 可查余量） | 试用免费（1 年，仅基础数据）；因子与特色数据（含舆情）需标准版/专业版按年付费 |
| `GM_SDK` | 掘金量化 Myquant | local_terminal | — | 行情实时（tick/分钟）；财务按报告期 | 近 10 年日线/分钟/tick（行情类） | 单次查询最多 33000 行；免费版订阅上限 50 个标的（超出报 1202）；L2 仅券商内网且需 500 万门槛 | 基础版免费；专业版按年；券商版由券商收费；机构版定制 |

## 三、评分明细（100 分制）

| 源 | 现成因子度(30) | 时效性(15) | 覆盖与口径(10) | 接入成本(15) | 稳定性与延迟(10) | 成本与权限门槛(20) | 合计 | 依据 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `EM_COMMENT` | 18 | 10 | 9 | 15 | 6 | 20 | **78** | 文档基线（未实测） |
| `CHINASCOPE` | 22 | 10 | 3 | 15 | 3 | 20 | **73** | 文档基线（未实测） |
| `RQ_HTTP` | 28 | 14 | 7 | 11 | 8 | 0 | **68** | 文档基线（未实测）；权限未开通 |
| `JIN10_WEIBO` | 16 | 14 | 4 | 10 | 4 | 20 | **68** | 文档基线（未实测） |
| `RQ_SDK` | 28 | 14 | 7 | 6 | 8 | 4 | **67** | 文档基线（未实测） |
| `UQER_HTTP` | 27 | 10 | 8 | 12 | 6 | 4 | **67** | 文档基线（未实测）；权限未开通 |
| `EM_NEWS` | 8 | 14 | 6 | 13 | 5 | 20 | **66** | 文档基线（未实测） |
| `TUSHARE_NEWS` | 8 | 14 | 6 | 14 | 8 | 8 | **58** | 文档基线（未实测）；权限未开通 |
| `JQ_SDK` | 15 | 6 | 6 | 9 | 8 | 6 | **50** | 文档基线（未实测） |
| `JQ_HTTP` | 15 | 6 | 6 | 8 | 4 | 0 | **39** | 文档基线（未实测）；权限未开通 |
| `GM_SDK` | 0 | 6 | 2 | 2 | 6 | 14 | **30** | 文档基线（未实测） |

维度定义：
- **现成因子度**（30 分）：是否直接给出可入模的舆情/新闻因子值（而非仅给原始文本）
- **时效性**（15 分）：日内多次 / 半小时级 > T+1 日更 > 周更
- **覆盖与口径**（10 分）：A股/港股覆盖广度、个股级 vs 市场级、历史长度
- **接入成本**（15 分）：纯 HTTP + 免安装最低；需私有 pip 源 / 本地终端最高
- **稳定性与延迟**（10 分）：接口可用率、返回结构稳定性、p95 延迟
- **成本与权限门槛**（20 分）：免费额度是否够日报量级；是否需商务开通

## 四、逐源实测明细

### `EM_COMMENT` · 东方财富（免费公开） — 部分可用（需自建清洗或 NLP）（78 分）

- 接口：千股千评：用户关注指数 / 机构参与度 / 综合得分
- 端点 / 调用：`https://datacenter-web.eastmoney.com/api/data/v1/get` · 方法：reportName=RPT_DMSK_TS_STOCKNEW（全市场分页）, reportName=RPT_STOCK_MARKETFOCUS（个股用户关注指数）, reportName=RPT_DMSK_TS_STOCKEVALUATE（机构参与度）, reportName=RPT_STOCK_HISTORYMARK（历史评分）
- 本次结果：只有热度/关注度、无极性，需配自建词库（sentiment_nlp）补足情感维度；本次取数 9 行
- 取样统计：新闻 0 条 / 序列 9 行 / 平台原生情感 0 条 / 最新日期 2026-09-15 / p50 0.0ms · p95 0.0ms
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ✅ | 依赖齐备: 无第三方依赖（纯标准库） |
| 网络可达性 | ✅ | mock 模式跳过网络检测（未产生任何请求） |
| 鉴权与权限 | ✅ | 免鉴权（公开接口） |
| 取数能力 | ✅ | news=0 series=9 行 |
| 字段完整度 | ✅ | 关键字段 ['value'] 缺失 无；非空率 100% |
| 时效新鲜度 | ✅ | 最新记录 2026-09-15（距今 2 天，阈值 ≤3 天） · mock 模式按录制日期判定，实际时效需 --live 复核 |
| 标的覆盖率 | ✅ | 抽样 3 个标的/关键词 → 命中 3（覆盖率 100%） |
| 响应延迟 | ✅ | p50 0ms / p95 0ms（mock 记录为 0，不代表线上延迟） |
| 额度与限频 | ✅ | pageSize ≤ 500；无限额文档，需自带重试与限速 |

- ⚠️ 权限提示：属热度/关注度因子，不含情感极性，需与新闻文本层结合才成"舆情因子"
- 说明：与米筐"舆情大数据（东财股吧，2007-10 至今，天度/小时情绪指数 + 热度因子）"同源，可作机构版权益的热度替代。
- 文档：<https://data.eastmoney.com/stockcomment/>

### `CHINASCOPE` · 数库 Chinascope（免费公开） — 可直接接入（73 分）

- 接口：A 股新闻情绪指数（市场级，日更）
- 端点 / 调用：`https://www.chinascope.com/inews/senti/index` · 方法：GET ?period=YEAR
- 本次结果：平台直接给出日频情绪指数（市场级现成因子，无需自建 NLP）；本次取数 6 行
- 取样统计：新闻 0 条 / 序列 6 行 / 平台原生情感 0 条 / 最新日期 2026-09-15 / p50 0.0ms · p95 0.0ms
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ✅ | 依赖齐备: 无第三方依赖（纯标准库） |
| 网络可达性 | ✅ | mock 模式跳过网络检测（未产生任何请求） |
| 鉴权与权限 | ✅ | 免鉴权（公开接口） |
| 取数能力 | ✅ | news=0 series=6 行 |
| 字段完整度 | ✅ | 关键字段 ['value'] 缺失 无；非空率 100% |
| 时效新鲜度 | ✅ | 最新记录 2026-09-15（距今 2 天，阈值 ≤3 天） · mock 模式按录制日期判定，实际时效需 --live 复核 |
| 标的覆盖率 | ✅ | 抽样 3 个标的/关键词 → 命中 6（覆盖率 100%） |
| 响应延迟 | ✅ | p50 0ms / p95 0ms（mock 记录为 0，不代表线上延迟） |
| 额度与限频 | ✅ | 无鉴权、无文档化限额；作兜底建议 ≤ 1 次/日 + 本地缓存 |

- ⚠️ 权限提示：实测风险：原域名 www.chinascope.com 已 302 跳至 .com.cn 首页，inews/senti/index 疑随官网改版下线；上线前必须先探一次 404/302 再决定是否保留本层
- 说明：数库基于每日数十万篇财经新闻做情感识别（SmarTag：7 大新闻标签 + 2 大新闻情绪维度），并与 J.P. Morgan 亚太量化团队共建情绪指数；市场级温度计可直接用，个股仍需自建。
- 文档：<https://www.chinascope.com.cn/reasearch.html> · <https://akshare.akfamily.xyz/data/index/index.html>

### `RQ_HTTP` · 米筐 RiceQuant — 可接入（需开权限/付费）（68 分）

- 接口：RQData HTTP/WebSocket 接口（舆情同源，机构合同开通）
- 端点 / 调用：`https://api.ricequant.com/apis` · 方法：token, news.get_stock_news, get_price
- 本次结果：平台直接给出情感/情绪字段（1 条可原生入模）；本次取数 1 行
- 取样统计：新闻 1 条 / 序列 0 行 / 平台原生情感 1 条 / 最新日期 2026-09-15 / p50 0.0ms · p95 0.0ms
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ✅ | 依赖齐备: 无第三方依赖（纯标准库） |
| 网络可达性 | ✅ | mock 模式跳过网络检测（未产生任何请求） |
| 鉴权与权限 | ❌ | 缺凭据环境变量: RQDATA_TOKEN、RQDATA_USER/RQDATAC_USER、RQDATA_PASSWORD/RQDATAC_PASSWORD（在 CI Secrets/本地 .env 配置，勿写入仓库） |
| 取数能力 | ✅ | news=1 series=0 行 |
| 字段完整度 | ✅ | 关键字段 ['title', 'sentiment', 'published_at'] 缺失 无；非空率 100% |
| 时效新鲜度 | ✅ | 最新记录 2026-09-15（距今 2 天，阈值 ≤3 天） · mock 模式按录制日期判定，实际时效需 --live 复核 |
| 标的覆盖率 | ✅ | 抽样 3 个标的/关键词 → 命中 1（覆盖率 33%） |
| 响应延迟 | ✅ | p50 0ms / p95 0ms（mock 记录为 0，不代表线上延迟） |
| 额度与限频 | ✅ | 按合同 |

- ⚠️ 权限提示：公开渠道未给出通用 HTTP 端点，本条目为占位，签约后再据实填写，勿据此写死代码
- 说明：若已签 RQData，优先走 HTTP：CI 免装 rqdatac，且与本项目"纯标准库"约束一致。
- 文档：<https://www.ricequant.com/doc/rqdata/python/generic-api>

### `JIN10_WEIBO` · 金十数据（免费公开） — 部分可用（需自建清洗或 NLP）（68 分）

- 接口：微博舆情报告（个股讨论人气排行指数）
- 端点 / 调用：`https://datacenter-api.jin10.com/weibo/list` · 方法：GET ?timescale=CNHOUR2|CNHOUR6|CNHOUR12|CNHOUR24|CNDAY7|CNDAY30
- 本次结果：只有热度/关注度、无极性，需配自建词库（sentiment_nlp）补足情感维度；本次取数 4 行
- 取样统计：新闻 0 条 / 序列 4 行 / 平台原生情感 0 条 / 最新日期 2026-09-15 / p50 0.0ms · p95 0.0ms
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ✅ | 依赖齐备: 无第三方依赖（纯标准库） |
| 网络可达性 | ✅ | mock 模式跳过网络检测（未产生任何请求） |
| 鉴权与权限 | ✅ | 免鉴权（公开接口） |
| 取数能力 | ✅ | news=0 series=4 行 |
| 字段完整度 | ✅ | 关键字段 ['value'] 缺失 无；非空率 100% |
| 时效新鲜度 | ✅ | 最新记录 2026-09-15（距今 2 天，阈值 ≤3 天） · mock 模式按录制日期判定，实际时效需 --live 复核 |
| 标的覆盖率 | ✅ | 抽样 3 个标的/关键词 → 命中 4（覆盖率 100%） |
| 响应延迟 | ✅ | p50 0ms / p95 0ms（mock 记录为 0，不代表线上延迟） |
| 额度与限频 | ✅ | 需带 x-app-id / x-version 等浏览器头（akshare 同源），无正式配额 |

- ⚠️ 权限提示：私有请求头 + 无 SLA，随时可能加签名；只做预警辅助，不入主因子
- 说明：小时级热度是"舆情异动预警"的极佳补充，但只有热度没有极性。
- 文档：<https://datacenter.jin10.com/market>

### `RQ_SDK` · 米筐 RiceQuant — 待实测（67 分）

- 接口：RQData 新闻舆情数据 news.get_stock_news（真·现成舆情因子）
- 端点 / 调用：`SDK 调用` · 方法：rqdatac.init, rqdatac.news.get_stock_news, rqdatac.get_announcement, rqdatac.get_factor, rqdatac.get_all_factor_names
- 本次结果：运行环境缺依赖，未实测；在有 SDK 的机器上重跑 --live
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ❌ | 缺包: rqdatac, rqdatac_news；需私有源：pip install -i https://py.ricequant.com/simple/ rqdatac rqdatac_news |
| 网络可达性 | ⚪ | API 端点 TCP+TLS 是否可达（区分"平台故障"与"本地出口受限/境外 IP 被拒"） |
| 鉴权与权限 | ⚪ | 凭据是否存在、登录是否成功、数据权限是否开通 |
| 取数能力 | ⚪ | 真实取样一次，是否返回非空结果集 |
| 字段完整度 | ⚪ | 舆情/新闻关键字段是否存在且非空率达标 |
| 时效新鲜度 | ⚪ | 最新记录距今天数是否 ≤ 阈值（日内源要求 0-1 天） |
| 标的覆盖率 | ⚪ | 抽样标的中能取到舆情/新闻的比例 |
| 响应延迟 | ⚪ | 连续取样的 p50 / p95 延迟 |
| 额度与限频 | ⚪ | 单次上限、日额度、并发限制是否满足日报节奏 |

- ⚠️ 权限提示：两个必踩坑：① rqdatac 需从米筐私有 pip 源安装（PyPI 无包）；② 舆情模块必须单独 pip install rqdatac_news，否则 rqdatac.news 不存在
- 说明：字段口径最适合直接建因子：情绪极性(-1/0/1) + 正/中/负三档权重 + 公司相关度，可做"新闻级情感 × 相关度 × 时间衰减"的标准舆情因子；缺点是要付费 + 私有源安装。
- 文档：<https://www.ricequant.com/doc/rqdata/python/alternative-data>

### `UQER_HTTP` · 优矿 Uqer（通联数据） — 可接入（需开权限/付费）（67 分）

- 接口：DataAPI 新闻情感/热度指数（现成舆情因子最完整）
- 端点 / 调用：`https://api.uqer.cn/data` · 方法：NewsSentimentIndexGet, NewsHeatIndexGet, NewsByTickersGet, NoticeByTickersGet, MktStockFactorsOneDayGet
- 本次结果：平台直接给出日频情绪指数（市场级现成因子，无需自建 NLP）；本次取数 12 行
- 取样统计：新闻 2 条 / 序列 10 行 / 平台原生情感 0 条 / 最新日期 2026-09-15 / p50 0.0ms · p95 0.0ms
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ✅ | 依赖齐备: 无第三方依赖（纯标准库） |
| 网络可达性 | ✅ | mock 模式跳过网络检测（未产生任何请求） |
| 鉴权与权限 | ❌ | 缺凭据环境变量: UQER_TOKEN（在 CI Secrets/本地 .env 配置，勿写入仓库） |
| 取数能力 | ✅ | news=2 series=10 行 |
| 字段完整度 | ✅ | 关键字段 ['value'] 缺失 无；非空率 83% |
| 时效新鲜度 | ✅ | 最新记录 2026-09-15（距今 2 天，阈值 ≤3 天） · mock 模式按录制日期判定，实际时效需 --live 复核 |
| 标的覆盖率 | ✅ | 抽样 3 个标的/关键词 → 命中 3（覆盖率 100%） |
| 响应延迟 | ✅ | p50 0ms / p95 0ms（mock 记录为 0，不代表线上延迟） |
| 额度与限频 | ✅ | 按 token 限速；单次批量 secID 建议 ≤ 300 只（需实测） |

- ⚠️ 权限提示：优矿近年迭代放缓（文档变更日志停在早期），DataAPI 可用性与字段名需在有权环境实测复核后再上线
- 说明：sentimentIndex = 当日关联新闻情感均值、heatIndex = 新闻热度，两个数即可直接入模；若有可用 token，性价比高于米筐（存在免费层）。
- 文档：<https://uqer.datayes.com/help/introduction/> · <https://uqer.datayes.com/data/>

### `EM_NEWS` · 东方财富（免费公开） — 部分可用（需自建清洗或 NLP）（66 分）

- 接口：search-api 个股新闻检索（关键词 → 标题 + 摘要）
- 端点 / 调用：`https://search-api-web.eastmoney.com/search/jsonp` · 方法：GET ?param={"uid":"","keyword":"600000","type":["cmsArticleWebOld"],"param":{"cmsArticleWebOld":{"pageIndex":1,"pageSize":20}}}
- 本次结果：给到的是原始新闻文本，需自建词库（sentiment_nlp）打分；本次取数 5 行
- 取样统计：新闻 5 条 / 序列 0 行 / 平台原生情感 0 条 / 最新日期 2026-09-15 / p50 0.0ms · p95 0.0ms
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ✅ | 依赖齐备: 无第三方依赖（纯标准库） |
| 网络可达性 | ✅ | mock 模式跳过网络检测（未产生任何请求） |
| 鉴权与权限 | ✅ | 免鉴权（公开接口） |
| 取数能力 | ✅ | news=5 series=0 行 |
| 字段完整度 | ✅ | 关键字段 ['title', 'published_at'] 缺失 无；非空率 100% |
| 时效新鲜度 | ✅ | 最新记录 2026-09-15（距今 2 天，阈值 ≤3 天） · mock 模式按录制日期判定，实际时效需 --live 复核 |
| 标的覆盖率 | ✅ | 抽样 3 个标的/关键词 → 命中 3（覆盖率 100%） |
| 响应延迟 | ✅ | p50 0ms / p95 0ms（mock 记录为 0，不代表线上延迟） |
| 额度与限频 | ✅ | pageSize 建议 ≤ 20；无鉴权但可能要求浏览器 UA / Cookie（akshare 实现带固定 cookie） |

- ⚠️ 权限提示：JSONP 外壳需剥离；标题噪音高，情感需人工规则复核后才能入实盘
- 说明：本项目自建情感层（sentiment_nlp.py）的默认文本源之一。
- 文档：<https://so.eastmoney.com/news/s?keyword=600000>

### `TUSHARE_NEWS` · Tushare Pro — 部分可用（需自建清洗或 NLP）（58 分）

- 接口：news / major_news / cctv_news 新闻文本接口
- 端点 / 调用：`http://api.tushare.pro` · 方法：news, major_news, cctv_news, anns_d, irm_qa_sh, irm_qa_sz
- 本次结果：给到的是原始新闻文本，需自建词库（sentiment_nlp）打分；本次取数 4 行
- 取样统计：新闻 4 条 / 序列 0 行 / 平台原生情感 0 条 / 最新日期 2026-09-15 / p50 0.0ms · p95 0.0ms
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ✅ | 依赖齐备: 无第三方依赖（纯标准库） |
| 网络可达性 | ✅ | mock 模式跳过网络检测（未产生任何请求） |
| 鉴权与权限 | ❌ | 缺凭据环境变量: TUSHARE_TOKEN（在 CI Secrets/本地 .env 配置，勿写入仓库） |
| 取数能力 | ✅ | news=4 series=0 行 |
| 字段完整度 | ✅ | 关键字段 ['title', 'published_at'] 缺失 无；非空率 100% |
| 时效新鲜度 | ✅ | 最新记录 2026-09-15（距今 2 天，阈值 ≤3 天） · mock 模式按录制日期判定，实际时效需 --live 复核 |
| 标的覆盖率 | ✅ | 抽样 3 个标的/关键词 → 命中 4（覆盖率 100%） |
| 响应延迟 | ✅ | p50 0ms / p95 0ms（mock 记录为 0，不代表线上延迟） |
| 额度与限频 | ✅ | news 单次最大 1500 条；major_news 单次 400 行，可循环补历史 |

- ⚠️ 权限提示：给的是原始文本而非因子，需自建情感打分；胜在便宜、纯 HTTP、易进 CI
- 说明：POST {api_name, token, params, fields} → JSON，是"自建舆情因子"层最省事的文本源。
- 文档：<https://tushare.pro/document/2?doc_id=143> · <https://tushare.pro/document/2?doc_id=195>

### `JQ_SDK` · 聚宽 JoinQuant — 待实测（50 分）

- 接口：jqdatasdk 本地 SDK（因子库 + finance 舆情表）
- 端点 / 调用：`SDK 调用` · 方法：auth, get_query_count, get_all_factors, get_factor_values, get_index_stocks, finance.run_query
- 本次结果：运行环境缺依赖，未实测；在有 SDK 的机器上重跑 --live
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ❌ | 缺包: jqdatasdk |
| 网络可达性 | ⚪ | API 端点 TCP+TLS 是否可达（区分"平台故障"与"本地出口受限/境外 IP 被拒"） |
| 鉴权与权限 | ⚪ | 凭据是否存在、登录是否成功、数据权限是否开通 |
| 取数能力 | ⚪ | 真实取样一次，是否返回非空结果集 |
| 字段完整度 | ⚪ | 舆情/新闻关键字段是否存在且非空率达标 |
| 时效新鲜度 | ⚪ | 最新记录距今天数是否 ≤ 阈值（日内源要求 0-1 天） |
| 标的覆盖率 | ⚪ | 抽样标的中能取到舆情/新闻的比例 |
| 响应延迟 | ⚪ | 连续取样的 p50 / p95 延迟 |
| 额度与限频 | ⚪ | 单次上限、日额度、并发限制是否满足日报节奏 |

- ⚠️ 权限提示：SDK 与官网账号体系一致；聚宽研究环境内 import jqdata 免鉴权（但只能在云上跑）
- 说明：返回 DataFrame，便于与既有 pandas 管线拼接；CI 需 pip install jqdatasdk（PyPI 可装）。
- 文档：<https://www.joinquant.com/help/api/help?name=api>

### `JQ_HTTP` · 聚宽 JoinQuant — 部分可用（需自建清洗或 NLP）（39 分）

- 接口：JQData 旧版 HTTP 数据接口
- 端点 / 调用：`https://dataapi.joinquant.com/apis` · 方法：get_token, get_current_token, get_all_factors, get_factor_values, get_alpha101, get_alpha191, get_query_count, get_price
- 本次结果：聚宽"情绪因子"为量价口径（换手/AR-BR/ATR），新闻侧仅文本，需自建打分；本次取数 17 行
- 取样统计：新闻 2 条 / 序列 15 行 / 平台原生情感 0 条 / 最新日期 2026-09-15 / p50 0.0ms · p95 0.0ms
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ✅ | 依赖齐备: 无第三方依赖（纯标准库） |
| 网络可达性 | ✅ | mock 模式跳过网络检测（未产生任何请求） |
| 鉴权与权限 | ❌ | 缺凭据环境变量: JQ_MOBILE/JQ_USERNAME、JQ_PASSWORD（在 CI Secrets/本地 .env 配置，勿写入仓库） |
| 取数能力 | ✅ | news=2 series=15 行 |
| 字段完整度 | ✅ | 关键字段 ['value'] 缺失 无；非空率 88% |
| 时效新鲜度 | ✅ | 最新记录 2026-09-15（距今 2 天，阈值 ≤3 天） · mock 模式按录制日期判定，实际时效需 --live 复核 |
| 标的覆盖率 | ✅ | 抽样 3 个标的/关键词 → 命中 17（覆盖率 100%） |
| 响应延迟 | ✅ | p50 0ms / p95 0ms（mock 记录为 0，不代表线上延迟） |
| 额度与限频 | ✅ | get_token 当日有效；试用 100 万条/天，因子与特色数据需付费版 |

- ⚠️ 权限提示：两个硬坑：① 试用账号"因子和特色数据：无"，情绪因子与雪球热度必须付费；② 官方文档页顶部标注「旧版 http 接口已不再维护，随时可能下线，不再建议使用」
- 说明：聚宽"情绪因子"是量价/换手量能类（VOL、AR/BR、ATR、DAVOL），并非新闻 NLP 情感；真正的新闻情感因子平台不给，只给雪球热度与新闻文本。因 HTTP 版已标记不再维护，本项目仅保留作对照，生产接入请用 JQ_SDK。
- 文档：<https://dataapi.joinquant.com/docs> · <https://www.joinquant.com/help/api/help?name=JQData> · <https://www.joinquant.com/view/factorlib/list>

### `GM_SDK` · 掘金量化 Myquant — 平台不提供该能力（30 分）

- 接口：掘金 gm.api 数据接口（无舆情因子，需终端代理）
- 端点 / 调用：`http://127.0.0.1:31000` · 方法：set_token, history, history_n, current, get_symbol_infos, stk_get_fundamentals_income_pt, stk_get_daily_valuation_pt, stk_get_index_constituents, get_trading_dates_by_year
- 本次结果：依据官方文档判定（不依赖本机 SDK）：结论明确：掘金适合作行情 + 交易执行通道；舆情/新闻因子必须外挂（自建 NLP，或从米筐/优矿取数后回灌掘金的组合管理）。
- 阶段明细：

| 阶段 | 结果 | 说明 |
|---|:--:|---|
| 依赖可用性 | ❌ | 缺包: gm |
| 网络可达性 | ⚪ | API 端点 TCP+TLS 是否可达（区分"平台故障"与"本地出口受限/境外 IP 被拒"） |
| 鉴权与权限 | ⚪ | 凭据是否存在、登录是否成功、数据权限是否开通 |
| 取数能力 | ⚪ | 真实取样一次，是否返回非空结果集 |
| 字段完整度 | ⚪ | 舆情/新闻关键字段是否存在且非空率达标 |
| 时效新鲜度 | ⚪ | 最新记录距今天数是否 ≤ 阈值（日内源要求 0-1 天） |
| 标的覆盖率 | ⚪ | 抽样标的中能取到舆情/新闻的比例 |
| 响应延迟 | ⚪ | 连续取样的 p50 / p95 延迟 |
| 额度与限频 | ⚪ | 单次上限、日额度、并发限制是否满足日报节奏 |

- ⚠️ 权限提示：SDK 通过掘金终端代理取数，终端必须常驻 → 无 GUI 的 CI/服务器环境完全不可用
- 说明：结论明确：掘金适合作行情 + 交易执行通道；舆情/新闻因子必须外挂（自建 NLP，或从米筐/优矿取数后回灌掘金的组合管理）。
- 文档：<https://www.myquant.cn/docs2/quickStart/%E6%95%B0%E6%8D%AE.html> · <https://www.myquant.cn/docs2/faq/%E4%BA%A7%E5%93%81%E9%97%AE%E9%A2%98.html>

## 五、落地接入方案（本仓库已实现）

```
sentiment_sources.py    注册表：源、字段、鉴权 env、额度、口径（唯一事实源）
sentiment_adapters.py   适配器：live/mock 同一套解析；live 走 urllib，SDK 走反射导入
sentiment_nlp.py        自建情感层：词库 + 否定/程度 + 风险词 + 时间衰减 → 舆情因子
sentiment_factors.py    分层取数 + 因子合成 → sentiment_data.json（供建站与推送）
tools/probe_sentiment_apis.py  本工具：9 阶段实测 + 打分 + 报告
```

**分层降级（保证 09:00 定时任务永不断供）**

| 层 | 数据源 | 产出 | 失败时 |
|---|---|---|---|
| T0 | 米筐 `news.get_stock_news` / 优矿 `sentimentIndex` | 个股级现成情感因子 | 下探 T1 |
| T1 | 东财千股千评 / 金十微博人气 | 关注度、热度 Z 值 | 下探 T2 |
| T2 | 东财 search-api / Tushare news / 聚宽新闻联播 | 新闻文本 → 自建词库打分 | 下探 T3 |
| T3 | 数库市场情绪指数 / 聚宽情绪因子（VOL、AR/BR）对照 | 市场级温度计 | 沿用上次结果并标注降级 |

**因子口径**（`sentiment_sources.FACTOR_LIBRARY`，与日报正文一致）

| 因子 | 名称 | 单位 | 定义 | 首选源 |
|---|---|---|---|---|
| `SENT_TEMP` | 市场舆情温度计 | 0-100 | 净情感 + 热度异动 + 负面占比 加权映射到 0-100；>65 偏亢奋、<35 偏恐慌 | UQER_HTTP / RQ_SDK / CHINASCOPE |
| `NET_SENTI` | 净情感强度 | -1 ~ +1 | Σ(情感权重 × 公司相关度 × 时间衰减) / Σ权重，正值代表正面舆情占优 | RQ_SDK (news_emotion_indicator) / UQER_HTTP (sentimentIndex) |
| `NEWS_HEAT_Z` | 新闻热度 Z 值 | σ | 当日关联新闻量相对近 20 日均值的标准分，|Z|>2 视为舆情异动 | UQER_HTTP (heatIndex) / EM_COMMENT (关注指数) / JQ_SDK (雪球热度) |
| `NEG_SHARE` | 负面舆情占比 | % | 负向情感新闻条数 / 全部关联新闻条数；>35% 触发风险提示 | RQ_SDK (news_negative_weight) / SELF_NLP (自建词库) |
| `EVENT_RISK` | 突发事件风险分 | 0-100 | 监管/诉讼/违约/退市/减持/质押等高风险词加权命中，单日取最大值 | EM_NEWS / TUSHARE_NEWS / JQ_SDK（公告+新闻文本）→ 自建词库打分 |

**上线三步**

1. 境内机器（或境内自建 runner）配置凭据环境变量后跑 `--live`，把 `api_probe_report.json` 结论落到本报告；
2. 权限确认：米筐/聚宽/优矿任一开通即接 T0；未开通则只上 T1+T2（免费源 + 自建词库），因子留 `platform_native=0` 标记，回测时单独分组；
3. 先跑 20 个交易日影子模式：只记录因子值不下单，核对 `NEWS_HEAT_Z` 与真实涨停/跌停事件的相关性，再进选股（舆情因子单独 IC 通常 0.02–0.05，须与量价/基本面合成）。

## 六、需复核清单（confidence = needs_check）

- `CHINASCOPE` 数库 Chinascope（免费公开）：实测风险：原域名 www.chinascope.com 已 302 跳至 .com.cn 首页，inews/senti/index 疑随官网改版下线；上线前必须先探一次 404/302 再决定是否保留本层
- `RQ_HTTP` 米筐 RiceQuant：公开渠道未给出通用 HTTP 端点，本条目为占位，签约后再据实填写，勿据此写死代码
- `JIN10_WEIBO` 金十数据（免费公开）：私有请求头 + 无 SLA，随时可能加签名；只做预警辅助，不入主因子
- `UQER_HTTP` 优矿 Uqer（通联数据）：优矿近年迭代放缓（文档变更日志停在早期），DataAPI 可用性与字段名需在有权环境实测复核后再上线

## 七、风险提示

- 舆情/新闻因子含大量转载与标题党，**极性误判集中在反问句、引述与"否认传闻"类表述**，实盘前需对高风险词命中项做人工抽检；
- 免费公开接口（东财、金十、数库）无 SLA、可能随时改路径或加签名，必须保留降级与本地缓存；
- 转载第三方新闻正文仅用于内部研究，不对外再分发；抓取须遵守各站 robots 与频率自律；
- 本报告仅为数据接口评测，不构成投资建议。

> 🔎 **本次为 mock 运行**：评分依据公开文档基线与录制报文，接口连通性、真实延迟、权限状态尚未实测；在境内有权环境执行 `python3 tools/probe_sentiment_apis.py --live` 即可把「文档基线」升级为「实测」。
