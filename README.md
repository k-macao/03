# 03 — 章鱼 AI 全景分析 (Retro Pixel Edition)

自动生成的分析报告站点: <https://k-macao.github.io/03/>

## 结构

| 文件 | 说明 |
|---|---|
| `report.html` | 报告源文件（**复古街机配色 · 黑体小字排版**，街机夜空 + 像素金 + 1-UP 绿 + 暴击红配色），内含“手动推送”按钮及内嵌的单页微信版全文 (`<script id="wechat-parts">`)，支持 8-Bit 音效与 CRT 扫描线开关；推送前自动核对并刷新时间戳 |
| `tools/wechat_push.py` | 微信推送工具：把 `report.html` 转为微信兼容的单页完整内联样式 HTML，经 PushPlus **一对一**推送到微信 |
| `.github/workflows/m.yml` | CI：部署 Pages 并支持一键触发微信单页推送 |

## 微信推送 (PushPlus · 一对一单页完整版)

- **一对一专属推送**：默认直接推送给 Token 拥有者本人，零群组干扰。
- **页面只推一个微信页**：点击“手动推送”立即发送**单页完整微信卡片**，全篇 7 大章节与 14 大社区论坛研判一次性送达，无需拆条分发与 15s 等待。
- **⏰ 推送前时间核对**：每一次推送前先读取当前时间，标题与正文中的“生成时间 / 时间核对”等全部时间戳**实时刷新为最新时间**后再发送（网页按钮与命令行推送均已内置）。
- **命令行推送**：`python3 tools/wechat_push.py --push`
- **验证转换效果**：`python3 tools/wechat_push.py --dry-run`
- **重新内嵌内容**：报告更新后，运行 `python3 tools/wechat_push.py --embed`（幂等）。

Token 维护在 `report.html` 的 `PUSHPLUS_TOKEN` 常量中，网页按钮与推送工具共用。群组编码 `PUSHPLUS_TOPIC` 保持留空 `''` 即为一对一推送。

## 页面风格系统

- **视觉基调**：经典 8-Bit / 16-Bit 复古街机与 RPG 终端（Arcade Cabinet / CRT Terminal）。
- **字体系统**：全站统一**黑体**（SimHei / 微软雅黑 / 苹方 PingFang SC / Noto Sans SC 黑体栈），正文 13px 紧凑小字号，标题加粗分级。
- **调色系统**：街机夜空 `#080b14` + 像素金 `#facc15` + 1-UP 绿 `#22c55e` + 暴击红 `#ef4444` + 法力青 `#06b6d4`。
- **互动特性**：
  - 📺 **CRT 扫描线**：支持动态开启/关闭扫描线荧光效果。
  - 🔊 **8-Bit 音效引擎**：基于 Web Audio API 合成投币、升级与菜单交互音效。
  - 👾 **14 平台多空研判**：支持按偏多、偏空、中性、多空分歧动态筛选。
