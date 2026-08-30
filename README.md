# 03 — 章鱼 AI 全景分析 (Editorial E-Ink Edition)

自动生成的分析报告站点: <https://k-macao.github.io/03/>

## 🔄 动态抓取真正上线 — 行情+社区双动态 (每次构建/推送自动更新)

每次 push、手动触发或每天 09:00 定时任务，都会**先自动抓取最新行情+14 大社区最新研判，再构建报告并推送**，
页面与微信收到的永远是当天最新数据，杜绝“8 月 12 日”旧内容残留：

```bash
python3 market_data.py               # ① 动态抓取行情 → market_data.json (Yahoo→Stooq回退)
python3 community_data.py            # ② 动态抓取14社区 → community_data.json (HTTP GET+模板回退，每次刷新当天日期)
python3 build_site.py                # ③ 动态建站 → report.html (注入行情+社区+日期/时间戳，14源动态注入)
python3 tools/wechat_push.py --embed # ④ 内嵌最新推送负载进 report.html
python3 tools/wechat_push.py --push --scheduled   # ⑤ 推送完整报告到微信
```

- **行情源**：Yahoo Finance chart API → Stooq CSV 多源自动回退（纯标准库，CI 无需安装依赖）。
- **社区源**：14 大社区（富途牛牛/雪球/老虎/东方财富/智通财经/华尔街见闻/香港讨论区/LIHKG/韭圈儿/蚂蚁财富/Reddit/TradingView/VIC/FinTwit）**每次构建均 HTTP GET 尝试抓取**，提取文本片段作为活数据佐证，结合最新行情动态生成研判；单源失败自动降级为基于最新行情的动态模板，保证 14 源永远齐全，**正文日期永远为当天**。
- **覆盖标的**：恒指 / 恒生科技 / 恒生国企 / 标普 500 / 纳斯达克 / 道琼斯 / 现货黄金 / WTI / 布伦特 / 美元离岸与在岸人民币。
- **失败降级**：单品行情/单社区抓取失败自动降级（行情显示 "—"，社区显示动态模板），并在页面标注，**不阻断构建与推送**，保证 09:00 定时任务永不中断。
- **日期联动**：14 大社区「最新读取」日期与正文中的“8 月 X 日”日期均随抓取日自动刷新（`community_data.py` 生成当天日期），推送前日期核对（`--push` 严格 / `--scheduled` 宽松）逻辑保持不变。
- 本地联调可用 `python3 market_data.py --demo && python3 community_data.py --demo` 生成模拟行情+社区。

## 结构

| 文件 | 说明 |
|---|---|
| `market_data.py` | **动态行情抓取**：多源回退抓取最新行情，生成 `market_data.json`（构建产物，不入库） |
| `community_data.py` | **动态社区抓取**：14 大社区 HTTP GET + 动态模板回退，生成 `community_data.json`（构建产物，不入库），每次刷新当天日期与研判正文 |
| `build_site.py` | **动态建站**：把 `report.html` 模板中的 `{{占位符}}` 替换为最新行情/抓取日期/时间戳，并把 `community_data.json` 的 14 条最新研判注入 `<!-- COMMUNITY_LIST -->` 标记 |
| `report.html` | 报告**模板源文件**（**电子杂志 × 电子墨水**风格 · 浅灰底 + 正文纯黑 + 荧光绿标题 · 小字号竖版长页），内含"手动推送"按钮与 `<!-- COMMUNITY_LIST:BEGIN/END -->` 动态注入标记；仓库中始终保持模板版本，构建产物不提交（误提交构建产物时 `git checkout -- report.html` 恢复） |
| `tools/wechat_push.py` | 微信推送工具：读取 `market_data.json` + `community_data.json` 双动态数据，转为微信兼容的单页完整内联样式 HTML，经 PushPlus **一对一**推送到微信 |
| `.github/workflows/m.yml` | CI：动态抓取行情+社区 → 动态建站（双注入） → 部署 Pages + 一键触发微信单页推送 + **每天北京时间 09:00 定时自动推送** |

## 页面风格系统 (Style A · 电子杂志 × 电子墨水)

参考 [Guizang PPT Skill](https://github.com/op7418/guizang-ppt-skill) 的 **Style A「电子杂志 × 电子墨水」**，改造成适合微信阅读的竖版长页面。

- **视觉基调**：电子杂志 × 电子墨水 (Editorial Magazine × E-Ink)，像 *Monocle* 杂志贴上了代码。
- **字体系统**：标题用衬线宋体 **Noto Serif SC**，正文用黑体栈（SimHei / 微软雅黑 / 苹方 PingFang SC / Noto Sans SC），**全部字号偏小**（正文 12px 紧凑小字号）。
- **调色系统**：
  - 整体**浅灰色背景** `#eef0f2`
  - **正文纯黑** `#141414`
  - **标题荧光绿** `#00e05c`
  - **重点字体荧光绿文字 + 黑色背景** `#000` / `#39ff14`（霓虹绿高亮）
  - 其余配搭均为荧光绿与黑色。
- **标题与署名**：标题为「章鱼 AI 全景分析」，副标题「全网 AI 调研境内境外数据，由多个大模型混合部署」，**标题去除 pushplus 与时间戳**。正文末尾署名：**作者：章鱼 ai · 仅供参考，分析研究**，并附多模型协同说明。
- **01 节量化策略说明**：原「6 个模型卡片格子（model-grid）」已移除，原位替换为量化策略说明块（`.quant-box`）——「多量化策略 + 一百多因子 + 多模型 AI 智能分析」标题 + 三条要点（监控几百个指标分析公司利润与成交／动量、新闻情绪、热度等／由规则驱动，纪律执行，不受情绪干扰），落款「— 每日 章鱼 AI 提高理性分析」。**网页与微信推送两端同步呈现**（`report.html` 与 `tools/wechat_push.py` 的 `quant_block`）。

## 微信推送 (PushPlus · 一对一单页完整版 · 14 源动态)

- **一对一专属推送**：默认直接推送给 Token 拥有者本人，零群组干扰。
- **页面只推一个微信页**：点击"手动推送"立即发送**单页完整微信卡片**，全篇 7 大章节与 14 大社区论坛研判一次性送达，无需拆条分发与 15s 等待。
- **⏰ 推送前时间核对**：每一次推送前均重新抓取行情+社区数据，并读取当前时间；标题与正文中的"生成时间 / 时间核对"等全部时间戳**实时刷新为最新时间**后再发送（网页按钮与命令行推送均已内置）。
- **📅 推送前频道最新内容核对**：**每一次推送都重新抓取并逐条检查** 14 个频道内容是否为频道最新（`community_data.py` 每次生成当天日期），不因当天已抓取过而复用历史结果；任一频道缺少「最新读取」标记、检查失败或结果非当天，**手动推送**拒绝推送；**定时推送** (`--scheduled`) 则仅警告不阻断，确保每天 09:00 定时任务可运行。
- **命令行推送**：`python3 tools/wechat_push.py --push`
- **定时自动推送**：`python3 tools/wechat_push.py --push --scheduled`
- **验证转换效果**：`python3 tools/wechat_push.py --dry-run`
- **重新内嵌内容**：报告更新后，运行 `python3 tools/wechat_push.py --embed`（幂等）。

Token 维护在 `report.html` 的 `PUSHPLUS_TOKEN` 常量中，网页按钮与推送工具共用。群组编码 `PUSHPLUS_TOPIC` 保持留空 `''` 即为一对一推送。

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
