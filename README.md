# 03 — 章鱼 AI 全景分析 (Editorial E-Ink Edition)

自动生成的分析报告站点: <https://k-macao.github.io/03/>

## 结构

| 文件 | 说明 |
|---|---|
| `report.html` | 报告源文件（**电子杂志 × 电子墨水**风格 · 浅灰底 + 正文纯黑 + 荧光绿标题 · 小字号竖版长页），内含“手动推送”按钮及内嵌的单页微信版全文 (`<script id="wechat-parts">`)；推送前自动核对并刷新时间戳 |
| `tools/wechat_push.py` | 微信推送工具：把 `report.html` 转为微信兼容的单页完整内联样式 HTML，经 PushPlus **一对一**推送到微信 |
| `.github/workflows/m.yml` | CI：部署 Pages、支持一键触发微信单页推送，并**每天北京时间 09:00 定时自动推送** |

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

## 微信推送 (PushPlus · 一对一单页完整版)

- **一对一专属推送**：默认直接推送给 Token 拥有者本人，零群组干扰。
- **页面只推一个微信页**：点击“手动推送”立即发送**单页完整微信卡片**，全篇 7 大章节与 14 大社区论坛研判一次性送达，无需拆条分发与 15s 等待。
- **⏰ 推送前时间核对**：每一次推送前先读取当前时间，标题与正文中的“生成时间 / 时间核对”等全部时间戳**实时刷新为最新时间**后再发送（网页按钮与命令行推送均已内置）。
- **📅 推送前抓取日期核对**：检查 14 大社区「最新读取」日期，**手动推送**若不是当天则拒绝推送；**定时推送** (`--scheduled`) 则仅警告不阻断，确保每天 09:00 定时任务可运行。
- **命令行推送**：`python3 tools/wechat_push.py --push`
- **定时自动推送**：`python3 tools/wechat_push.py --push --scheduled`
- **验证转换效果**：`python3 tools/wechat_push.py --dry-run`
- **重新内嵌内容**：报告更新后，运行 `python3 tools/wechat_push.py --embed`（幂等）。

Token 维护在 `report.html` 的 `PUSHPLUS_TOKEN` 常量中，网页按钮与推送工具共用。群组编码 `PUSHPLUS_TOPIC` 保持留空 `''` 即为一对一推送。

## ⏰ 每天北京时间早上九点自动推送

`.github/workflows/m.yml` 内置 `schedule` 定时任务（UTC `0 1 * * *`，即**北京时间每天 09:00**），自动执行 `python3 tools/wechat_push.py --push --scheduled`，无需手动操作即可把最新全景报告推送到微信。

> 提示：GitHub Actions 定时任务存在少量延迟属正常现象；若需精确到秒的定时，可结合仓库 Secrets (PUSHPLUS_TOKEN) 与外部 Cron 服务。
