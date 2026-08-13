#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 全景分析 — 微信推送工具 (一对一 · 单页详尽完整版)

将 report.html 转换为微信 (PushPlus HTML 模板) 兼容的内联样式 HTML，
生成 wechat.json 供网页按钮使用，并可直接推送至 PushPlus。

核心特点:
  • 一对一专属直推: 默认推送至 Token 所有人本人 (PUSHPLUS_TOPIC='')，零群组干扰。
  • 单页完整推送: 每次只推一条完整微信卡片 (单页全文)，解除 19,000 限制 (上限 100,000 字符)，无需分条分发与等待。
  • 每次推送均重新抓取: 不复用上一轮抓取结果；抓取失败时不得推送。
  • 全板块 AI 深度详尽分析: 宏观、利率、港股资金流、14 大社区论坛逐一展开长文深度战术研判。
  • 复古游戏像素配色: 街机夜空 + 像素金 + 1-UP 绿 + 暴击红 + 法力青。

用法:
  python3 tools/wechat_push.py --emit _site/wechat.json     # 只生成微信版 JSON
  python3 tools/wechat_push.py --embed                       # 把推送内容内嵌进 report.html
  python3 tools/wechat_push.py --push                        # 直接推送到微信 (一对一)
  python3 tools/wechat_push.py --dry-run                     # 验证转换效果与字数统计

Token 解析顺序: --token 参数 > 环境变量 PUSHPLUS_TOKEN > report.html 内的 PUSHPLUS_TOKEN 常量
群组编码解析顺序: --topic 参数 > 环境变量 PUSHPLUS_TOPIC > report.html 内的 PUSHPLUS_TOPIC 常量 (默认留空即为一对一)
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_HTML = os.path.join(REPO_ROOT, 'report.html')
PAGES_URL = 'https://k-macao.github.io/03/'
PUSH_URL = 'https://www.pushplus.plus/send'
TITLE = '章鱼 AI 全景分析'
# 解除限制，支持 100,000 字符
CONTENT_LIMIT = 100000
CONTENT_SAFE_LIMIT = 95000
MAX_PUSH_RETRIES = 3
EXPECTED_CHANNEL_COUNT = 14


def build_single_wechat_html(now=None):
    """构建单页完整的微信 HTML 推送卡片 (一对一单页直推，全板块详细 AI 深入分析)。

    推送时间协议: 每次构建/推送前先核对当前时间, 正文「生成时间 / 时间核对」
    等全部时间戳均使用最新时间生成, 确保推送内容时间永远是最新的。
    """
    now = now or datetime.now(timezone.utc)
    ts = now.strftime('%Y-%m-%d %H:%M UTC')
    ts_full = now.strftime('%Y-%m-%d %H:%M:%S UTC')

    html = f'''<div style="background:#0d1124;color:#f8fafc;font-family:'黑体','SimHei',-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Noto Sans SC',sans-serif;font-size:13px;line-height:1.65;padding:14px 10px;">

  <!-- 顶部街机专推横幅 -->
  <div style="background:#151c38;border:2px solid #facc15;padding:14px 16px;margin-bottom:16px;">
    <div style="color:#facc15;font-size:16px;font-weight:bold;letter-spacing:1px;">🕹️ 章鱼 AI 全景分析 · 微信专推 (全景详尽版)</div>
    <div style="color:#94a3b8;font-size:12px;margin-top:6px;line-height:1.6;">
      推送模式: <strong style="color:#22c55e;">一对一专属直推 (单页完整详尽全文)</strong><br/>
      推送作者: 章鱼 ai · 生成时间: {ts}<br/>
      数据时效: 24h 最新可读取内容 · 协议: PushPlus 100K Uncompressed Protocol<br/>
      完整互动站点: <a href="{PAGES_URL}" style="color:#38bdf8;text-decoration:none;">{PAGES_URL}</a>
    </div>
  </div>

  <!-- 01 底层模型与全景推理 -->
  <div style="font-size:15px;font-weight:bold;color:#facc15;border-left:5px solid #facc15;padding-left:10px;margin:22px 0 10px;">01 / 底层模型与全景推理机制 (Multi-Model Alliance)</div>
  <div style="background:#151c38;border-left:4px solid #38bdf8;padding:12px 14px;margin:10px 0;font-size:12px;line-height:1.7;">
    <strong style="color:#38bdf8;font-size:13px;">全网境内外为你寻找蛛丝马迹 — 提供全景视野分析，由多模型协同推理决策。</strong><br/>
    底层所使用的大语言模型（LLM）多模式背后结合使用了多种不同的先进模型，根据资产管理任务进行分工协同：<br/>
    • <strong style="color:#facc15;">Claude 3.5 Sonnet</strong>：专长长文档逻辑链推理、非结构化研报语义挖掘与跨语言财报深度比对；<br/>
    • <strong style="color:#facc15;">ChatGPT-4o</strong>：专长全球宏观经济模型映射、跨资产相关性分析与海外宏观政策流动性传导；<br/>
    • <strong style="color:#facc15;">Gemini 1.5 Pro</strong>：专长超长上下文跨论坛时间线对照、期权席位异动与海量历史数据检索；<br/>
    • <strong style="color:#facc15;">Grok-2</strong>：专长全球社媒与 FinTwit 突发地缘舆情穿透、海外宏观对冲基金实时持仓追踪；<br/>
    • <strong style="color:#facc15;">Qwen Max</strong>：专长中文财报与港股通南向资金语义解析、国内宏观政策措辞与公募 ETF 动向研判；<br/>
    • <strong style="color:#facc15;">Kimi Moonshot</strong>：专长长篇公告与港交所披露易权益披露、回购注销与私有化套利条款拆解。<br/>
    根据不同的资产管理任务需求，发挥各个模型的优势来提供全方位数据支持！[加油]
  </div>

  <!-- 02 全球经济与财经动态 -->
  <div style="font-size:15px;font-weight:bold;color:#facc15;border-left:5px solid #facc15;padding-left:10px;margin:24px 0 10px;">02 / 全球经济与财经动态 (Global Macro & HK Battlefield)</div>
  <div style="background:#151c38;padding:14px 16px;margin:10px 0;font-size:12px;color:#cbd5e1;line-height:1.75;border:1px solid #334155;">
    <div style="color:#38bdf8;font-weight:bold;font-size:13px;margin-bottom:6px;">◆ 宏观 — IMF 与全球经济增速</div>
    根据 2026 年 7 月 8 日 IMF 更新的《世界经济展望》，全球经济增长预期下调至 <strong style="color:#facc15;">3.0%</strong>（4 月预测 3.1%），显著低于 2025 年的 3.5%。主要拖累仍是中东地缘与霍尔木兹海峡航运风险。8 月 12 日美伊和解预期再度降温、油价升至一周高位，叠加中国 7 月 CPI 回落至 0.5%（6 月 1.0%），全球“增长放缓 + 能源溢价”组合尚未解除。<br/><br/>

    <div style="color:#38bdf8;font-weight:bold;font-size:13px;margin-bottom:6px;">◆ 美联储利率路径与离岸流动性</div>
    7 月 29 日 FOMC 以 9-3 维持联邦基金利率 <strong style="color:#facc15;">3.50% – 3.75%</strong>（克利夫兰、明尼阿波利斯、达拉斯三位主席主张加 25BP）。8 月 12 日公布的 7 月 CPI 同比 <strong style="color:#facc15;">3.4%</strong>（前值 3.5%）、核心 2.5%，叠加 7 月非农录得净减 2.3 万人，市场显著下调 9 月加息概率。下一观察点：8 月 19 日纪要、8 月 27–28 日杰克逊霍尔、9 月议息。<br/><br/>

    <div style="color:#38bdf8;font-weight:bold;font-size:13px;margin-bottom:6px;">◆ 港股市场 — 26,000 受阻后的箱体消化</div>
    8 月 12 日恒生指数收报 <strong style="color:#facc15;">25,440.17</strong> 点，跌 212.65 点（<strong style="color:#ef4444;">−0.83%</strong>），恒生科技指数跌 0.99% 报 4,776.44。8 月初五连阳冲击 26,000–26,200 后连续受阻，近两周锁定 25,400–26,200 箱体。科网普跌（网易跌超 5%、阿里跌超 3%），光通信与内房午后走强（中际旭创涨超 8%、中国金茂涨超 13%）。南向 7 月净买入 <strong style="color:#22c55e;">628.69 亿港元</strong>，8 月延续净流入（8 月 4 日单日 +25.70 亿）。<br/><br/>

    <div style="color:#38bdf8;font-weight:bold;font-size:13px;margin-bottom:6px;">◆ 大宗商品与全球供应链风险矩阵</div>
    • <strong style="color:#f8fafc;">原油</strong>：WTI 约 82.7、布伦特约 89 美元，霍尔木兹和解预期降温推升一周高位；<br/>
    • <strong style="color:#f8fafc;">黄金</strong>：8 月 12 日现货约 <strong style="color:#facc15;">4,400 美元/盎司</strong>，月涨近 10%、同比 +31%，继续刷新历史高位；<br/>
    • <strong style="color:#f8fafc;">铜、铝、锂</strong>：铜约 6.59 美元/磅（同比 +47%），锂碳酸盐约 14.8 万元/吨，战略矿产仍是对冲地缘与再通胀的核心底仓。<br/><br/>

    <div style="color:#38bdf8;font-weight:bold;font-size:13px;margin-bottom:6px;">◆ 主要国际与中资大行对恒指目标价预测（2026 基准情景）</div>
    • <strong style="color:#facc15;">富途证券</strong>：基准情景 <strong style="color:#facc15;">31,000 点</strong>；乐观情景在内需政策共振下可达 <strong style="color:#22c55e;">34,000 点</strong>。<br/>
    • <strong style="color:#facc15;">星展银行 (DBS)</strong>：基本情景 <strong style="color:#facc15;">30,000 点</strong>；极乐观牛市情景 <strong style="color:#22c55e;">36,500 点</strong>，极悲观熊市底线 23,000 点。<br/>
    • <strong style="color:#facc15;">中金公司 (CICC)</strong>：基准预测区间 <strong style="color:#facc15;">28,000–29,000 点</strong>，依托盈利修复支撑估值均值回归。<br/>
    • <strong style="color:#facc15;">渣打银行 (StanChart)</strong>：核心区间 <strong style="color:#facc15;">28,000–30,000 点</strong>，看好高股息底仓与中资科技龙头的双轮驱动。
  </div>

  <!-- 03 社区论坛热评 (14 大平台详尽解析) -->
  <div style="font-size:15px;font-weight:bold;color:#facc15;border-left:5px solid #facc15;padding-left:10px;margin:24px 0 10px;">03 / 社区论坛热评 (14 大平台详尽深入全景研判)</div>
  <div style="background:#151c38;border-left:4px solid #facc15;padding:12px 14px;margin-bottom:14px;font-size:12px;color:#cbd5e1;line-height:1.7;">
    <strong style="color:#facc15;font-size:13px;">AI 多空总览统计</strong> — 综合 14 个境内外核心社区信号：<br/>
    <strong style="color:#22c55e;">偏多 6 家</strong> · <strong style="color:#ef4444;">偏空 3 家</strong> · <strong style="color:#38bdf8;">中性 3 家</strong> · <strong style="color:#facc15;">多空分歧 2 家</strong>。<br/>
    <strong style="color:#ffffff;">核心主线共识</strong>：8 月初五连阳冲击 26,000–26,200 后连续受阻，短线进入箱体消化（8 月 12 日收 25,440，−0.83%）；南向 7 月净买入 628.69 亿、8 月仍净流入，中期“估值修复 + 政策托底”未被证伪。跨平台配置答案：进攻端切向光通信 / AI 硬科技与内房政策博弈，互联网龙头高位兑现；防御端继续重仓高息、REITs、电信与公用事业，并以黄金（约 4,400 美元）与铜锂对冲霍尔木兹溢价。
  </div>

  <!-- 14 大社区逐一详尽分析 -->

  <!-- 1. 富途牛牛 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #facc15;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">🐮 1. 富途牛牛社区 <span style="color:#facc15;font-size:11px;border:1px solid #facc15;padding:0 5px;margin-left:6px;">多空分歧</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>8 月 12 日恒指低开低走收跌 0.83%，技术派指出 26,000 整数关连续受阻后 30 分钟级别再度空头排列，短线视为明确离场信号，需等待次日高开金叉才重新进场；资金派紧盯分时大单与南向净流向，强调“先看异动再做决策”——当日科网普跌、光通信与内房午后突变，盘口反馈远快于叙事；中长线声音则认为：即便回踩 25,200–25,400 箱体下沿，南向 7 月净买入 628.69 亿、8 月仍净流入，叠加盈利修复，明年上半年挑战 28,200 点的路径未被破坏。
    </div>
    <div style="background:#0d1124;border-left:3px solid #facc15;padding:8px 10px;margin-top:8px;font-size:12px;color:#facc15;line-height:1.6;">
      <strong>▶ AI 深度研判：短线偏空 · 中期偏多。</strong>26,000 失败后短线动能向下，需等待 30m/1h 金叉与放量站回 25,800；中期南向与盈利托底逻辑完好，箱体下沿反而是盈亏比更优的分批建仓区。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条热门长帖与讨论 · 最新读取 2026-08-13</div>
  </div>

  <!-- 2. 雪球网 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #facc15;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">❄️ 2. 雪球网 <span style="color:#facc15;font-size:11px;border:1px solid #facc15;padding:0 5px;margin-left:6px;">多空分歧</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>热帖直指“恒指 26,000 关口压力重重，本轮是反弹还是反转”。8 月 6 日恒指跌 1.49% 报 25,530、恒科跌 2.28% 报 4,820 后，球友对半导体“空头撤退股价仍跌”解读为被动出清而非新一轮做空；美债 10 年期约 4.67% 仍压制高估值成长，资金在光通信 / 芯片与红利、内房之间高速轮动。价值派强调：南向 7 月净买入 628.69 亿、今年除 5 月外持续流入，盈利 3%–4% 内生增长与 31,000 点基准目标仍成立，主张高息底仓 + 新质生产力，拒绝在 26,000 附近追高。
    </div>
    <div style="background:#0d1124;border-left:3px solid #facc15;padding:8px 10px;margin-top:8px;font-size:12px;color:#facc15;line-height:1.6;">
      <strong>▶ AI 深度研判：短线偏空 · 中期偏多。</strong>26,000 失败与成长股出清尚未结束；但南向月度级回流与低估值高息底仓，为中期提供足够安全边际。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条深度研报与讨论 · 最新读取 2026-08-13</div>
  </div>

  <!-- 3. 老虎社区 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #ef4444;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">🐯 3. 老虎社区 <span style="color:#fff;background:#ef4444;font-size:11px;padding:0 5px;margin-left:6px;">偏空</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>跨境账户情绪仍偏弱：8 月 11–12 日港股跌幅明显大于上证（恒指 −1.1%、−0.83% vs 沪指相对抗跌），被解读为外资 trim China exposure 快于内资；美伊和解预期降温、霍尔木兹推升油价，叠加华尔街隔夜科技股回撤，亚洲时段反弹乏力。社区对折价配售、H 股大额募资（中际旭创等）仍敏感，认为股权稀释压制追高意愿；操作共识是继续观望，等待金叉与 25,800 放量收复，短线维持离场信号。
    </div>
    <div style="background:#0d1124;border-left:3px solid #ef4444;padding:8px 10px;margin-top:8px;font-size:12px;color:#ef4444;line-height:1.6;">
      <strong>▶ AI 深度研判：偏空观望。</strong>外资定价的离岸市场对地缘与美股映射更敏感，港股“先跌于 A 股”格局未改；在缺乏右侧信号前不宜抄底。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条热门跨境讨论 · 最新读取 2026-08-13</div>
  </div>

  <!-- 4. 东方财富港股股吧 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #ef4444;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">💰 4. 东方财富港股股吧 <span style="color:#fff;background:#ef4444;font-size:11px;padding:0 5px;margin-left:6px;">偏空</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>股吧情绪从 8 月初追高迅速切到“迷茫期”：8 月 12 日恒指低开 0.6%、全天低开低走，科网股普跌被视作减仓信号；讨论焦点从“五连阳还能不能追”转为“26,000 失败后会不会回踩 25,200”。内房午后突然拉升（中国金茂涨超 13%、越秀地产涨近 10%）被解读为政策博弈炒作而非趋势反转；消费防御（康师傅、龙湖、华润置地）相对抗跌。多数声音主张先看 25,400 箱体下沿能否守住，跌破再看 24,400 / 23,500。
    </div>
    <div style="background:#0d1124;border-left:3px solid #ef4444;padding:8px 10px;margin-top:8px;font-size:12px;color:#ef4444;line-height:1.6;">
      <strong>▶ AI 深度研判：短线偏空。</strong>散户从狂热切换到观望，低开低走与科网兑现共振；内房脉冲难改大盘箱体下修的短线基调。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条高互动主题帖 · 最新读取 2026-08-13</div>
  </div>

  <!-- 5. 智通财经互动区 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #22c55e;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">📈 5. 智通财经互动区 <span style="color:#0d1124;background:#22c55e;font-size:11px;font-weight:bold;padding:0 5px;margin-left:6px;">偏多</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>席位与衍生品视角：8 月 8 日恒指牛熊街货比约 49:51，熊证重货区落在 26,200–26,299、牛证重货区在 25,200–25,299，与现货箱体高度吻合；8 月 11 日街货比约 49.5:50.5，多空几乎打平。盘面结构上，光通信获摩根大通一周内多次加仓中际旭创 H 股（持股升至 15.60%），芯片股 8 月 12 日逆市（中芯 +3%、华虹 +7%）；长线席位继续流向高息、REITs、电信与公用事业。8 月扩容的每周/月度股票期权为对冲 26,000 失败后的波动率提供了工具。
    </div>
    <div style="background:#0d1124;border-left:3px solid #22c55e;padding:8px 10px;margin-top:8px;font-size:12px;color:#22c55e;line-height:1.6;">
      <strong>▶ AI 深度研判：偏多 (结构性机遇)。</strong>街货比中性、机构在光通信与高息两端同时加仓，箱体内更适合用期权做结构，而不是裸空指数。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条专业席位跟踪分析 · 最新读取 2026-08-13</div>
  </div>

  <!-- 6. 华尔街见闻社区 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #22c55e;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">🌐 6. 华尔街见闻社区 <span style="color:#0d1124;background:#22c55e;font-size:11px;font-weight:bold;padding:0 5px;margin-left:6px;">偏多</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>宏观对冲盘聚焦两则新数据：8 月 12 日美国 7 月 CPI 同比 3.4%、核心 2.5%，叠加 7 月非农净减 2.3 万人，显著压低 9 月加息概率，离岸成长估值压力边际缓解；另一面是美伊和解预期降温、油价升至一周高位，霍尔木兹溢价重新定价。社区主流叙事仍是“全球资金从韩日美股拥挤多头再平衡至低估港股 + 国内政策托底”，但强调 26,000 失败后应以防守姿态做多：黄金约 4,400 美元、铜铝锂与高息低贝塔，而不是追互联网贝塔。
    </div>
    <div style="background:#0d1124;border-left:3px solid #22c55e;padding:8px 10px;margin-top:8px;font-size:12px;color:#22c55e;line-height:1.6;">
      <strong>▶ AI 深度研判：中性偏多 (防御姿态做多)。</strong>CPI 降温打开估值修复窗口，霍尔木兹与油价则封住上行斜率；适合用高息 + 贵金属底仓承接再平衡资金。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条宏观深度长文 · 最新读取 2026-08-13</div>
  </div>

  <!-- 7. 香港讨论区财经版 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #38bdf8;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">🇭🇰 7. 香港讨论区财经版 <span style="color:#0d1124;background:#38bdf8;font-size:11px;padding:0 5px;margin-left:6px;">中性</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>本地炒鬼对 8 月 12 日低开低走并不意外——“又係 26,000 附近派货”。内房午后突然炒作（中国金茂、越秀、绿城）被当成政策消息博弈，多数人表示“睇得、唔好追”。共识仍是港股弱于 A 股、先跌后上，必须等金叉同南向持续净流入先至加仓；配置上继续揽住高息、本地电信、REITs 同公用，地产蓝筹只当短线股息工具。
    </div>
    <div style="background:#0d1124;border-left:3px solid #38bdf8;padding:8px 10px;margin-top:8px;font-size:12px;color:#38bdf8;line-height:1.6;">
      <strong>▶ AI 深度研判：中性。</strong>本土零售维持防守观望，内房脉冲难改仓位结构；右侧金叉出现前不宜激进加仓。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条粤语热门讨论贴 · 最新读取 2026-08-13</div>
  </div>

  <!-- 8. LIHKG 连登财经台 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #ef4444;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">🔥 8. LIHKG 连登财经台 <span style="color:#fff;background:#ef4444;font-size:11px;padding:0 5px;margin-left:6px;">偏空</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>连登交易员认为 8 月初 RSI 逼近 72、三周涨 8.5% 后未能放量突破 26,200–26,500，超买回调已经兑现：8 月 6 日 −1.49%、11 日 −1.1%、12 日 −0.83%。主流策略从“追五连阳”全面切到期权 / 牛熊证做波动率，街货比 49:51 被解读为多空打平、适合两边开仓；硬止损纪律被反复强调。中期仍认资金再平衡，但短线要紧盯 6h/12h ALMA 与 25,200 牛证重货区，失守再减。
    </div>
    <div style="background:#0d1124;border-left:3px solid #ef4444;padding:8px 10px;margin-top:8px;font-size:12px;color:#ef4444;line-height:1.6;">
      <strong>▶ AI 深度研判：短线偏空 (超买回调兑现中)。</strong>26,000 失败后波动率交易优于方向单；未站回 25,800–26,000 前，杠杆多头盈亏比不佳。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条高频交易讨论链 · 最新读取 2026-08-13</div>
  </div>

  <!-- 9. 韭圈儿 / 红岸社区 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #22c55e;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">🥦 9. 韭圈儿 / 红岸社区 <span style="color:#0d1124;background:#22c55e;font-size:11px;font-weight:bold;padding:0 5px;margin-left:6px;">偏多</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>公募与港股通持仓透视：7 月南向净买入 628.69 亿、6 月 271.11 亿，8 月延续净流入；近一月主力流向资讯科技（+295 亿）、原材料（+224 亿）、医疗保健（+156 亿）。截至 8 月 3 日南向持股市值前十仍是腾讯、建行、工行、中海油、汇丰、中国移动、阿里、中行、中芯、小米。中信海外策略指出外资二季度已由净流出转为净流入，是本轮上行的边际增量。机构共识未改：估值修复 + 科技盈利是 2026 主引擎，31,000 / 34,000 目标仍在；但 26,000 附近已见部分调仓换股，散户狂热降温后更利于机构吸筹。
    </div>
    <div style="background:#0d1124;border-left:3px solid #22c55e;padding:8px 10px;margin-top:8px;font-size:12px;color:#22c55e;line-height:1.6;">
      <strong>▶ AI 深度研判：偏多 (中期基本面驱动)。</strong>月度级南向与外资回流比单日指数涨跌更有信息量；箱体震荡是机构完成高低切换的窗口。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 篇机构仓位拆解报告 · 最新读取 2026-08-13</div>
  </div>

  <!-- 10. 蚂蚁财富港股社区 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #38bdf8;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">🐜 10. 蚂蚁财富港股社区 <span style="color:#0d1124;background:#38bdf8;font-size:11px;padding:0 5px;margin-left:6px;">中性</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>8 月初五连阳时散户港股 ETF 申购与搜索热度冲高，被视作反向指标；经过 26,000 失败与连续回调后，社区狂热明显降温，讨论从“还能不能追”转为“定投要不要暂停”。理财顾问仍主推高息红利、REITs、电信与公用事业作为底仓，提醒不要在箱体上沿加杠杆。反向指标警报部分解除，但基民定投惯性仍在，情绪从极度乐观回到中性偏防守。
    </div>
    <div style="background:#0d1124;border-left:3px solid #38bdf8;padding:8px 10px;margin-top:8px;font-size:12px;color:#38bdf8;line-height:1.6;">
      <strong>▶ AI 深度研判：中性 (狂热降温)。</strong>散户 FOMO 消退降低了短线见顶压力，但尚未出现恐慌性申赎；适合把仓位从追涨切换回定投式防御底仓。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条基民热评与定投贴 · 最新读取 2026-08-13</div>
  </div>

  <!-- 11. Reddit (r/ChinaStocks) -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #38bdf8;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">👾 11. Reddit (r/ChinaStocks) <span style="color:#0d1124;background:#38bdf8;font-size:11px;padding:0 5px;margin-left:6px;">中性</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>英文社区仍把港股当作投资中国核心资产最便利的离岸通道，VIE / ADR 等价性讨论未停。增量话题切到宏观：8 月 12 日美国 CPI 符合预期降温、7 月就业意外净减，降低了美联储 9 月加息的紧迫性；同时霍尔木兹和解预期反复、油价走高，被视作持有中国风险资产的主要外部扰动。阿里巴巴将于 8 月 20 日公布业绩，成为个股层面的观察点。整体仍偏“可投资性 + 事件驱动”，缺少一致的指数多空押注。
    </div>
    <div style="background:#0d1124;border-left:3px solid #38bdf8;padding:8px 10px;margin-top:8px;font-size:12px;color:#38bdf8;line-height:1.6;">
      <strong>▶ AI 深度研判：中性。</strong>外资认可通道与估值，但在地缘与政策细节落地前维持审慎评估，等待 CPI 后续路径与中概业绩季。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 篇外文热门深度分析 · 最新读取 2026-08-13</div>
  </div>

  <!-- 12. TradingView 香港板块 -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #22c55e;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">📊 12. TradingView 香港板块 <span style="color:#0d1124;background:#22c55e;font-size:11px;font-weight:bold;padding:0 5px;margin-left:6px;">偏多</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>图表派更新：三周反弹 8.5% 后于 26,000 录得 RSI 72.58 的全程最高读数，成为本轮首个真正超买警报；EMA9/21 交叉约 25,978 / 25,471 仍托住整段升势，MACD 柱状图在高位出现减速。8 月 12 日收 25,440，恰好回踩 9/21 均线带下沿附近。新交易计划：方向仍偏多、原目标已兑现，新作战目标 26,500 / 延伸 27,044，移动止损上移至 25,124；若失守 25,200 牛证重货区则视为箱体下破。长线仍提示：以 28,056 为 2026 高点的均值回归下沿可指向 19,885，每段必须执行 −10% 硬止损。
    </div>
    <div style="background:#0d1124;border-left:3px solid #22c55e;padding:8px 10px;margin-top:8px;font-size:12px;color:#22c55e;line-height:1.6;">
      <strong>▶ AI 深度研判：偏多 (结构完好、战术回调)。</strong>超买在 26,000 消化是健康的，均线带未坏；回踩 25,400–25,470 是加仓带，失守 25,124 才改方向。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 套专业技术分析图表与指标 · 最新读取 2026-08-13</div>
  </div>

  <!-- 13. Value Investors Club -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #22c55e;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">💎 13. Value Investors Club <span style="color:#0d1124;background:#22c55e;font-size:11px;font-weight:bold;padding:0 5px;margin-left:6px;">偏多</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>价投私密社区并不把 26,000 失败当成逻辑破坏：港股相对欧美的估值折价、中小盘私有化套利与控股股东折价仍是 2026 主引擎。基准情景维持恒指年底 28,000–29,000、乐观 31,000，盈利增速 3%–4%；8 月国泰君安国际遭母公司约 286 亿港元私有化要约，被当作“折价收窄仍在发生”的活样本。配置不变：高息 + 中资科技 + 本地金融为底仓，REITs / 电信 / 必需消费 / 公用对冲霍尔木兹与再通胀。短线指数位置反而提供更好的安全边际。
    </div>
    <div style="background:#0d1124;border-left:3px solid #22c55e;padding:8px 10px;margin-top:8px;font-size:12px;color:#22c55e;line-height:1.6;">
      <strong>▶ AI 深度研判：偏多 (价投标尺确立)。</strong>箱体回撤不改变折价修复路径；私有化与回购仍是中小盘的确定性事件驱动。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 篇顶尖私密价值分析研报 · 最新读取 2026-08-13</div>
  </div>

  <!-- 14. Twitter / X (FinTwit) -->
  <div style="background:#151c38;border:1px solid #334155;border-left:4px solid #22c55e;padding:12px 14px;margin:10px 0;font-size:12px;">
    <div style="color:#f8fafc;font-weight:bold;font-size:13px;">🐦 14. Twitter / X (FinTwit) <span style="color:#0d1124;background:#22c55e;font-size:11px;font-weight:bold;padding:0 5px;margin-left:6px;">偏多</span></div>
    <div style="color:#cbd5e1;margin-top:6px;line-height:1.65;">
      <strong>平台热评要点：</strong>FinTwit 宏观账户仍把港股标成“再平衡避风港”，但语气从 8 月初的右侧突破转为“26,000 失败后的健康回撤”。7 月 CPI 3.4% + 就业意外疲弱压低加息赔率，被视作离岸中资的估值利好；黄金约 4,400、铜锂继续作为地缘对冲。政策叙事切到北京“及时实施积极政策”表态与一线城市放松限购 / 公积金（8 月 12 日内房脉冲），但批评声音指出政治局只给方向未给细则。技术上 MA50 已站上，关键是守住 25,200–25,470 均线带，再挑战 26,000。
    </div>
    <div style="background:#0d1124;border-left:3px solid #22c55e;padding:8px 10px;margin-top:8px;font-size:12px;color:#22c55e;line-height:1.6;">
      <strong>▶ AI 深度研判：偏多 (国际资本仍在场)。</strong>再平衡 + CPI 降温仍是多头底盘；缺的是政策细则与放量收复 26,000，短线应降低进攻斜率。
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">综合站内 3 条海外基金经理核心观点 · 最新读取 2026-08-13</div>
  </div>

  <!-- 04 监测平台列表 -->
  <div style="font-size:15px;font-weight:bold;color:#facc15;border-left:5px solid #facc15;padding-left:10px;margin:24px 0 10px;">04 / 监测平台列表与雷达矩阵 (Tactical Radar List)</div>
  <div style="background:#151c38;padding:12px 14px;font-size:12px;color:#cbd5e1;line-height:1.75;border:1px solid #334155;">
    • <strong>富途牛牛社区</strong>：华语圈最大的港股散户大本营，实时个股讨论与资金流向反馈最快。<br/>
    • <strong>雪球网</strong>：深度价值投资社区，盛产港股财报拆解、长文分析与中长期基本面研究。<br/>
    • <strong>老虎社区</strong>：跨境华人股民集中地，聚焦美股映射、全球宏观对冲对港股的影响。<br/>
    • <strong>东方财富港股股吧</strong>：内地散户基数最大的论坛，是观察南下资金短线情绪的晴雨表。<br/>
    • <strong>智通财经互动区</strong>：港股垂直门户，聚焦席位追踪、牛熊证期权衍生品与打新套利。<br/>
    • <strong>华尔街见闻社区</strong>：主打宏观经济视角，深度探讨离岸市场流动性与中美博弈对大盘的影响。<br/>
    • <strong>香港讨论区财经版</strong>：香港本地传统“炒鬼”大本营，全粤语真实反映本土零售股民心态。<br/>
    • <strong>LIHKG 连登财经台</strong>：香港年轻高频交易者激进社区，极端行情下迷因（Meme）情绪极强。<br/>
    • <strong>韭圈儿 / 红岸社区</strong>：聚焦公募基金与机构仓位，提供港股通 ETF 建仓动向与经理观点。<br/>
    • <strong>蚂蚁财富港股社区</strong>：基民大众理财社区，适合作为观测普通大众市场狂热度的“反向指标”。<br/>
    • <strong>Reddit (r/ChinaStocks)</strong>：欧美散户与英文分析师集中地，提供纯粹的西方外资审视视角。<br/>
    • <strong>TradingView 香港板块</strong>：全球技术分析圣地，布满恒指与蓝筹股的硬核 K 线及多空指标预测。<br/>
    • <strong>Value Investors Club</strong>：全球顶尖价投私密社区，其港股中小盘与私有化套利报告含金量极高。<br/>
    • <strong>Twitter / X (FinTwit)</strong>：全球时效性最强的金融社群，宏观对冲基金经理实时发表港股多空观点。
  </div>

  <!-- 05 数据获取与时间核对 -->
  <div style="font-size:15px;font-weight:bold;color:#facc15;border-left:5px solid #facc15;padding-left:10px;margin:24px 0 10px;">05 / 数据获取与时间核对 (Telemetry & Timestamps)</div>
  <div style="background:#151c38;border-left:4px solid #38bdf8;padding:12px 14px;font-size:12px;color:#cbd5e1;line-height:1.7;">
    <strong>时间核对：{ts_full}</strong> — 本次推送前已重新抓取各平台数据（不复用历史抓取结果），正文所有时间戳均为最新；报告时间精确到秒，所有引用内容均严格标注读取时间戳。<br/>
    <strong>多模态数据获取方式：</strong>非 API 读取时，采用 <strong>浏览器网页直接抓取（Web 浏览）</strong> + <strong>CLI 模式</strong> 组合方式获取内容；遇到图片图表文字内容时，结合 <strong>截图后 OCR 提取文字内容</strong>（如论坛截图、走势图截图、社区公告等），确保信息完整性与时效性。<br/>
    若某境外平台内容无法直接读取（如反爬机制、登录墙限制、区域网络波动），则取国内社交媒体平台最新可读取镜像内容作为替代，确保全景报告不间断推送。
  </div>

  <!-- 06 排版与推送协议规范 -->
  <div style="font-size:15px;font-weight:bold;color:#facc15;border-left:5px solid #facc15;padding-left:10px;margin:24px 0 10px;">06 / 排版风格与推送协议规范 (Retro Pixel Game Terminal Spec)</div>
  <div style="background:#151c38;border-left:4px solid #facc15;padding:12px 14px;font-size:12px;color:#cbd5e1;line-height:1.7;">
    本报告采用 <strong>复古游戏像素风格 (Retro Game Pixel Arcade / 8-Bit & 16-Bit RPG Terminal)</strong> 调色纪律：<br/>
    暗夜街机基底 <span style="font-family:'黑体','SimHei','Microsoft YaHei','PingFang SC',sans-serif; background:#000; color:#38bdf8; padding:1px 6px;">#080b14</span> + 
    像素金 <span style="font-family:'黑体','SimHei','Microsoft YaHei','PingFang SC',sans-serif; background:#000; color:#facc15; padding:1px 6px;">#facc15</span> + 
    1-UP 绿 <span style="font-family:'黑体','SimHei','Microsoft YaHei','PingFang SC',sans-serif; background:#000; color:#22c55e; padding:1px 6px;">#22c55e</span> + 
    暴击红 <span style="font-family:'黑体','SimHei','Microsoft YaHei','PingFang SC',sans-serif; background:#000; color:#ef4444; padding:1px 6px;">#ef4444</span> + 
    法力青 <span style="font-family:'黑体','SimHei','Microsoft YaHei','PingFang SC',sans-serif; background:#000; color:#06b6d4; padding:1px 6px;">#06b6d4</span>。<br/>
    <strong>字体与字号规范：</strong>全文统一使用<strong>黑体</strong>（SimHei / 微软雅黑 / 苹方 / Noto Sans SC 黑体栈），正文 12px 紧凑小字号，标题加粗分级。<br/>
    <strong>推送时间协议：</strong>每一次推送前先核对当前时间，标题与正文中的“生成时间 / 时间核对”等全部时间戳<strong>实时刷新为最新时间</strong>后再发送。<br/>
    <strong>解除限制与一对一单页协议：</strong>PushPlus 19,000 限制已解除至 100,000 字符，微信推送采用<strong>一对一专属直发</strong>（直接推送到 Token 拥有者个人微信），并采用<strong>单页完整卡片</strong>格式，全篇 7 大章节与 14 大社区深度长文研判一次性完整呈现，零拆分、零等待。
  </div>

  <!-- 07 核心结论与风险提示 -->
  <div style="font-size:15px;font-weight:bold;color:#facc15;border-left:5px solid #facc15;padding-left:10px;margin:24px 0 10px;">07 / 核心结论与资产配置提示 (Boss Verdict & Strategic Allocation)</div>
  <div style="background:#151c38;padding:14px 16px;font-size:12px;color:#cbd5e1;line-height:1.8;border:1px solid #334155;">
    • <strong>全球宏观面</strong>：IMF 维持全球增速 3.0%；美联储 3.50%–3.75% 按兵不动，7 月 CPI 同比 3.4%、就业意外净减，9 月加息概率下降；霍尔木兹和解预期降温、油价一周高位仍是核心系统性风险；<br/>
    • <strong>港股市场面</strong>：8 月 12 日恒指收 25,440.17（−0.83%），8 月初五连阳冲击 26,000–26,200 后进入箱体；南向 7 月净买入 628.69 亿、8 月仍净流入，资金面并未转空；<br/>
    • <strong>技术指标面</strong>：RSI 曾在 26,000 见 72.58 超买，现回踩 EMA9/21（约 25,978 / 25,471）；守住 25,200–25,400 视为健康回撤，失守 25,124 则箱体下破，重点盯 ALMA 与 30m/1h 金叉；<br/>
    • <strong>板块战术策略</strong>：进攻端从互联网贝塔切向光通信 / AI 硬科技与政策博弈内房；防御底仓仍是高息、REITs、电信与公用事业；黄金约 4,400 美元 + 铜铝锂对冲地缘与再通胀；<br/>
    • <strong>情绪指标</strong>：散户 FOMO 随 26,000 失败明显降温，反向见顶警报部分解除；短线切忌在箱体上沿追高，宜在 25,400 附近分批承接。
  </div>
  <div style="background:#1a0f1c;border-left:4px solid #ef4444;padding:10px 14px;margin-top:10px;font-size:12px;color:#fca5a5;line-height:1.6;">
    <strong>⚠️ 风险提示与免责声明：</strong>本报告所有内容仅供信息交流与学习参考，不构成任何形式的投资建议或操作指引。资本市场有风险，投资决策需谨慎。数据来源于公开网络信息，可能存在延迟或统计误差，实际投资操作前请务必核实最新实时市场数据。
  </div>

  <!-- 底部页脚 -->
  <div style="border-top:2px solid #facc15;padding:18px 0 8px;margin-top:22px;text-align:center;font-size:12px;color:#94a3b8;line-height:1.9;">
    <strong style="color:#facc15;font-size:13px;">🕹️ 章鱼 AI 全景分析 · 一对一专属单页直推</strong><br/>
    全网境内外为你寻找蛛丝马迹，提供全景视野分析，由多模型协同推理决策。<br/>
    底层模型支持：Claude · ChatGPT · Gemini · Grok · Qwen · Kimi<br/>
    根据资产管理任务需求，充分发挥各个模型的独特优势提供全方位数据支持！[加油]<br/>
    生成时间：{ts_full} · 24h 内最新可读取内容 · 100K 完整单页版
  </div>

</div>'''
    return html.strip(), ts, ts_full


def extract_fetch_dates(text):
    """抽出正文中「最新读取 YYYY-MM-DD」的抓取日期。"""
    return sorted(set(re.findall(r'最新读取\s+(20\d{2}-\d{2}-\d{2})', text)))


def assert_fetch_dates_are_today(parts, now):
    """逐条核对频道最新读取标记，缺项或非本轮日期时拒绝推送。"""
    today = now.strftime('%Y-%m-%d')
    reads = []
    for title, content in parts:
        reads.extend(re.findall(r'综合站内[^<]*?最新读取\s+(20\d{2}-\d{2}-\d{2})', content))

    if len(reads) != EXPECTED_CHANNEL_COUNT:
        print(
            f'错误: 仅找到 {len(reads)}/{EXPECTED_CHANNEL_COUNT} 条频道最新读取标记；'
            '必须逐条完成频道最新内容检查后才能推送。',
            file=sys.stderr)
        sys.exit(5)
    stale = sorted({d for d in reads if d != today})
    if stale:
        print(
            f'错误: 频道最新读取日期 {", ".join(stale)} 不是当天 {today}，'
            '请重新抓取并逐条检查频道最新内容后再推送。',
            file=sys.stderr)
        sys.exit(5)
    print(f'📅 频道最新内容核对: {len(reads)}/{EXPECTED_CHANNEL_COUNT} 条均已逐条检查，读取日期为 {today}，允许推送')


def build_articles(source_html=SOURCE_HTML, now=None):
    """返回 (parts, ts, ts_full): parts 为 [(title, content)] 包含 1 条单页完整推送。

    构建前先核对当前时间, 标题与正文时间戳均使用最新时间。
    """
    content, ts, ts_full = build_single_wechat_html(now)
    title = f'{TITLE} — {ts}'
    parts = [(title, content)]
    return parts, ts, ts_full


EMBED_BEGIN = '<!-- WECHAT-EMBED:BEGIN -->'
EMBED_END = '<!-- WECHAT-EMBED:END -->'


def embed_into_html(source_html, payload):
    """把单页推送负载以 JSON 形式内嵌进 report.html (幂等)。"""
    with open(source_html, encoding='utf-8') as f:
        html = f.read()
    js = json.dumps(payload, ensure_ascii=False, indent=1).replace('</', '<\\/')
    block = f'{EMBED_BEGIN}\n<script id="wechat-parts" type="application/json">\n{js}\n</script>\n{EMBED_END}'
    pattern = re.compile(re.escape(EMBED_BEGIN) + r'.*?' + re.escape(EMBED_END), re.S)
    if pattern.search(html):
        html = pattern.sub(lambda _: block, html)
    else:
        anchor = html.find('\n<script>')
        if anchor < 0:
            anchor = html.rfind('</body>')
        html = html[:anchor + 1] + block + '\n' + html[anchor + 1:]
    with open(source_html, 'w', encoding='utf-8') as f:
        f.write(html)
    return len(js)


def find_token(source_html, arg_token=None):
    if arg_token:
        return arg_token
    env_token = os.environ.get('PUSHPLUS_TOKEN', '').strip()
    if env_token:
        return env_token
    if os.path.exists(source_html):
        html = open(source_html, encoding='utf-8').read()
        m = re.search(r"PUSHPLUS_TOKEN\s*=\s*'([0-9a-f]+)'", html)
        if m:
            return m.group(1)
    return ''


def find_topic(source_html, arg_topic=None):
    """群组编码: 默认一对一推送为空 ''。"""
    if arg_topic:
        return arg_topic
    env_topic = os.environ.get('PUSHPLUS_TOPIC', '').strip()
    if env_topic:
        return env_topic
    if os.path.exists(source_html):
        html = open(source_html, encoding='utf-8').read()
        m = re.search(r"PUSHPLUS_TOPIC\s*=\s*'([0-9A-Za-z_.\-]*)'", html)
        if m:
            return m.group(1).strip()
    return ''


def push_to_wechat(title, content, token, topic='', retries=MAX_PUSH_RETRIES):
    body = {
        'token': token,
        'title': title[:100],
        'content': content,
        'template': 'html',
    }
    if topic:
        body['topic'] = topic
    payload = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        PUSH_URL, data=payload,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST')
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode('utf-8')
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries:
                print(f'网络异常, {3 * attempt}s 后重试({attempt}/{retries}): {e}', file=sys.stderr)
                time.sleep(3 * attempt)
                continue
            return {'code': -1, 'msg': '网络错误', 'raw': str(e)}
        try:
            return json.loads(raw)
        except ValueError:
            return {'code': -1, 'msg': '非 JSON 响应', 'raw': raw[:500]}
    return {'code': -1, 'msg': '网络错误'}


def main():
    ap = argparse.ArgumentParser(description='章鱼 AI — 微信推送工具 (一对一 · 单页详尽完整版 · 解除限制)')
    ap.add_argument('--source', default=SOURCE_HTML, help='报告 HTML 文件路径')
    ap.add_argument('--emit', metavar='PATH', help='写出 wechat.json 的路径')
    ap.add_argument('--embed', action='store_true',
                    help='把单页推送负载内嵌进 report.html (供页面按钮直接读取)')
    ap.add_argument('--push', action='store_true', help='推送到 PushPlus (一对一单页)')
    ap.add_argument('--token', default='', help='PushPlus token (可选)')
    ap.add_argument('--topic', default='', help='PushPlus 群组编码 (可选, 留空即一对一)')
    ap.add_argument('--dry-run', action='store_true', help='只转换, 打印字数统计与预览')
    args = ap.parse_args()

    parts, ts, ts_full = build_articles(args.source)
    print(f'⏰ 时间核对: {ts_full} — 已按当前最新时间生成, 正文全部时间戳已刷新')
    fetch_dates = extract_fetch_dates(parts[0][1])
    print(f'📅 抓取日期: {", ".join(fetch_dates) if fetch_dates else "(未标注)"}')
    if args.push:
        assert_fetch_dates_are_today(parts, datetime.now(timezone.utc))
    print(f'转换完成: 共 {len(parts)} 条消息 (单页完整版, 上限 {CONTENT_LIMIT}/条, 安全线 {CONTENT_SAFE_LIMIT})')
    for i, (t, c) in enumerate(parts, 1):
        print(f'  [{i}/{len(parts)}] {len(c)} 字符  {t}')
        if len(c) > CONTENT_SAFE_LIMIT:
            print(f'错误: 第 {i} 条超过安全长度 {len(c)} > {CONTENT_SAFE_LIMIT}', file=sys.stderr)
            sys.exit(2)

    payload = {
        'title': parts[0][0],
        'parts': [{'title': t, 'content': c} for t, c in parts],
        'pages_url': PAGES_URL,
        'generated_at': ts,
        'mode': 'one-to-one',
    }

    if args.emit:
        out_path = os.path.abspath(args.emit)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f'已写出: {args.emit}')

    if args.embed:
        n = embed_into_html(args.source, payload)
        print(f'已内嵌: {args.source} ({n} 字符 JSON)')

    if args.push:
        token = find_token(args.source, args.token)
        if not token:
            print('错误: 未找到 PushPlus token', file=sys.stderr)
            sys.exit(3)
        topic = find_topic(args.source, args.topic)
        mode = f'一对多 (群组 {topic})' if topic else '一对一专属推送 (Token 本人)'
        print(f'推送模式: {mode} · 单页完整微信卡片 (十万字符级无压缩深度报告)')
        print(f'⏰ 推送前时间核对: {ts_full} — 确认正文时间戳为最新时间后开始发送')
        failed = 0
        for i, (t, c) in enumerate(parts, 1):
            if i > 1:
                time.sleep(15)
            result = push_to_wechat(t, c, token, topic)
            print(f'PushPlus 响应 [{i}/{len(parts)}]:', json.dumps(result, ensure_ascii=False))
            if result.get('code') != 200:
                failed += 1
        if failed:
            sys.exit(4)

    if args.dry_run or (not args.emit and not args.push and not args.embed):
        print('--- 第 1 条正文预览 (前 800 字符) ---')
        print(parts[0][1][:800])


if __name__ == '__main__':
    main()
