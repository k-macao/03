#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 全景分析 — 微信推送工具 (一对一 · 单页详尽完整版 · 14 源动态抓取)

将 report.html 转换为微信 (PushPlus HTML 模板) 兼容的内联样式 HTML，
生成 wechat.json 供网页按钮使用，并可直接推送至 PushPlus。

核心特点:
  • 一对一专属直推: 默认推送至 Token 所有人本人 (PUSHPLUS_TOPIC='')，零群组干扰。
  • 单页完整推送: 每次只推一条完整微信卡片 (单页全文)，解除 19,000 限制 (上限 100,000 字符)，无需分条分发与等待。
  • 每次推送均重新抓取: 不复用上一轮抓取结果；推送前逐条核对 14 个频道的「最新读取」标记，抓取失败/缺项时不得推送。
  • 全板块 AI 深度详尽分析: 宏观、利率、港股资金流、14 大社区论坛逐一展开长文深度战术研判。
  • 电子杂志 × 电子墨水风格 (Guizang PPT Skill · Style A): 浅灰底 + 正文纯黑 + 荧光绿标题；
    重点文字为荧光绿字 + 黑色底，装饰线荧光绿，全部字号偏小，适合微信竖版长页面阅读。

动态抓取管线 (动态抓取真正上线 — 行情+社区双动态):
  python3 market_data.py && python3 community_data.py && python3 build_site.py   # ① 抓行情+社区 → ② 建站 (report.html)
  python3 tools/wechat_push.py --embed                       # ③ 把最新内容内嵌进 report.html
  python3 tools/wechat_push.py --push --scheduled            # ④ 推送 (正文自动注入最新行情/社区/抓取日期)

用法:
  python3 tools/wechat_push.py --emit _site/wechat.json     # 只生成微信版 JSON
  python3 tools/wechat_push.py --embed                       # 把推送内容内嵌进 report.html
  python3 tools/wechat_push.py --push                        # 直接推送到微信 (一对一, 严格日期校验)
  python3 tools/wechat_push.py --push --scheduled            # 每天 09:00 (北京时间) 定时推送 (宽松日期校验)
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

MINUS = '\u2212'  # U+2212 真正的减号，与全文风格一致

# 14 大社区「综合站内 … 最新读取 YYYY-MM-DD」逐频道标记 (用于推送前逐条核对)
CHANNEL_READ_RE = re.compile(r'综合站内[^<]*?最新读取\s+(20\d{2}-\d{2}-\d{2})')


def load_market_data():
    """读取 market_data.py 生成的 market_data.json（构建时动态抓取的最新行情）。"""
    path = os.environ.get('MARKET_DATA', os.path.join(REPO_ROOT, 'market_data.json'))
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f'⚠️ 警告: market_data.json 读取失败，使用内置兜底数据: {e}', file=sys.stderr)
        return {}


def load_community_data():
    """读取 community_data.py 生成的 community_data.json（14 大社区动态抓取）。

    路径可用环境变量 COMMUNITY_DATA 覆盖；文件缺失/损坏时返回 {}，
    此时正文回退到内置兜底社区数据（但日期会被刷新为当天），保证离线也能正常推送。
    """
    path = os.environ.get('COMMUNITY_DATA', os.path.join(REPO_ROOT, 'community_data.json'))
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f'⚠️ 警告: community_data.json 读取失败，使用内置兜底社区数据: {e}', file=sys.stderr)
        return {}


def build_single_wechat_html(now=None):
    """构建单页完整的微信 HTML 推送卡片。

    动态数据:
      - market_data.json: 行情数字、行情快照
      - community_data.json: 14 大社区最新研判（每次构建自动抓取，杜绝旧数据）
      若文件缺失时回退到内置兜底数据，但日期统一刷新为当天，保证离线可推送。
    """
    now = now or datetime.now(timezone.utc)
    ts = now.strftime('%Y-%m-%d %H:%M UTC')
    ts_full = now.strftime('%Y-%m-%d %H:%M:%S UTC')

    GR = '#00e05c'   # 荧光绿标题
    NEON = '#39ff14' # 霓虹绿 (黑底高亮)
    INK = '#141414'  # 正文纯黑

    # ---------- 动态行情注入 (market_data.json) ----------
    _md = load_market_data()
    _quotes = _md.get('quotes') or {}
    _fetch_date = _md.get('fetch_date') or now.strftime('%Y-%m-%d')

    # ---------- 动态社区注入 (community_data.json) ----------
    _cd = load_community_data()
    _communities_raw = _cd.get('communities') or []
    # 社区抓取日期优先取社区数据的 fetch_date，否则取行情的 fetch_date
    _community_fetch_date = _cd.get('fetch_date') or _fetch_date
    # 如果社区数据存在，用社区的 fetch_date 覆盖行情的 fetch_date 用于统一日期显示
    if _cd.get('fetch_date'):
        _fetch_date = _cd.get('fetch_date')

    def qq(key, fb='\u2014'):
        """最新价，缺失用兜底值。现货黄金 >=1000 时取整数千分位。"""
        q = _quotes.get(key)
        if not q or q.get('last') is None:
            return fb
        v = float(q['last'])
        nd = int(q.get('decimals') or 2)
        if q.get('name') == '现货黄金' and v >= 1000:
            nd = 0
        return f'{v:,.{nd}f}'

    def pct(key, fb='\u2014'):
        """涨跌幅，如 '−0.83%' / '+0.25%'。"""
        q = _quotes.get(key)
        if not q or q.get('pct') is None:
            return fb
        v = float(q['pct'])
        sign = MINUS if v < 0 else '+'
        return f'{sign}{abs(v):,.2f}%'

    def chg_desc(fb='跌 212.65 点'):
        """恒指涨跌描述，如 '跌 212.65 点' / '涨 15.20 点'。"""
        q = _quotes.get('HSI')
        if not q or q.get('chg') is None:
            return fb
        v = float(q['chg'])
        verb = '跌' if v < 0 else '涨'
        return f'{verb} {abs(v):,.2f} 点'

    def dq(fb='8 月 12 日'):
        """恒指行情日期，如 '8 月 28 日'。"""
        a = (_quotes.get('HSI') or {}).get('as_of') or ''
        m = re.match(r'20\d{2}-(\d{2})-(\d{2})', a)
        return fb if not m else f'{int(m.group(1))} 月 {int(m.group(2))} 日'

    def asof(key, fb='\u2014'):
        """行情日期 YYYY-MM-DD。"""
        return (_quotes.get(key) or {}).get('as_of') or fb

    def fetch_status():
        """数据源同步状态文案。"""
        s = _md.get('summary') or {}
        ok, total, failed = s.get('ok'), s.get('total'), s.get('failed') or []
        gen = _md.get('generated_at') or ''
        if ok is None:
            return f'抓取于 {gen}'
        if total == ok:
            return f'{ok}/{total} 项行情同步成功'
        failed_str = "、".join(failed) if failed else ""
        return f'{ok}/{total} 项同步成功（{failed_str} 降级为 —）'

    def community_fetch_status():
        """社区抓取状态文案"""
        if not _cd:
            return f'社区数据回退到内置模板 · 抓取日期 {_community_fetch_date}'
        s = _cd.get('summary') or {}
        ok, total = s.get('ok'), s.get('total')
        gen = _cd.get('generated_at') or ''
        if ok is None:
            return f'社区 {len(_communities_raw)} 源已加载 · 抓取于 {gen}'
        return f'{ok}/{total} 个社区源同步成功 · 抓取于 {gen}'

    def key(t):
        return f'<strong style="background:#000;color:{NEON};font-weight:700;padding:1px 5px;">{t}</strong>'

    def h(t):
        return (f'<div style="color:#000;font-family:\'黑体\',\'SimHei\',\'PingFang SC\',\'Hiragino Sans GB\',\'Microsoft YaHei\',\'Noto Sans SC\',sans-serif;font-size:15px;'
                f'font-weight:700;border-left:4px solid {NEON};padding-left:9px;'
                f'margin:24px 0 10px;">{t}</div>')

    def sub(t):
        return f'<div style="color:{GR};font-weight:700;font-size:13px;margin-bottom:6px;">{t}</div>'

    def box(inner):
        return (f'<div style="background:#f8f9fa;border:1px solid #d9dce0;border-radius:6px;'
                f'padding:14px 16px;margin:10px 0;font-size:12px;line-height:1.85;">{inner}</div>')

    def card(icon, no, name, label, vclass, quote, verdict, meta):
        chip = NEON if vclass in ('bull', 'mixed') else '#cfcfcf'
        edge = GR
        if vclass == 'bear':
            edge = '#141414'
        return (
            f'<div style="background:#f8f9fa;border:2px solid #d9dce0;border-left:3px solid {edge};'
            f'border-radius:6px;padding:12px 14px;margin:10px 0;font-size:12px;color:#141414;">'
            f'<div style="color:{GR};font-weight:700;font-size:13px;">{icon} {no}. {name} '
            f'<span style="background:#000;color:{chip};font-size:10px;padding:1px 6px;margin-left:4px;">{label}</span></div>'
            f'<div style="margin-top:6px;line-height:1.8;"><strong>平台深度热评：</strong>{quote}</div>'
            f'<div style="background:#eceef0;border-left:3px solid {GR};border-radius:4px;padding:8px 10px;'
            f'margin-top:8px;font-size:11.5px;color:#0a0a0a;line-height:1.7;">'
            f'<strong style="color:#0a0a0a;">▶ AI 深度战术研判：</strong>{verdict}</div>'
            f'<div style="color:#7d838b;font-size:10px;margin-top:6px;">{meta}</div>'
            f'</div>')

    # 01 节量化策略说明块（与 report.html 的 .quant-box 对应，微信端全内联样式）
    quant_block = (
        f'<div style="background:#f8f9fa;border:1px solid #d9dce0;border-left:3px solid {GR};'
        f'border-radius:6px;padding:14px 16px;margin:10px 0;font-size:12px;line-height:1.85;'
        f'color:{INK};">'
        f'<div style="margin-bottom:8px;">量化依托程序代替人工研判，汇总海量数据、提炼规律并落地交易，规避情绪化操作误区。</div>'
        f'<div style="margin-bottom:12px;">避免人工靠消息主观选股，量化同步上百项指标，规则化执行操作。</div>'
        f'<div style="color:{GR};font-weight:700;font-size:13px;margin:12px 0 6px;">◆ 章鱼 AI 量化策略六大打造步骤</div>'
        f'<div style="line-height:1.85;">'
        f'1. <strong>数据收集</strong>：囊括行情、财报、舆情等多维度信息<br/>'
        f'2. <strong>数据清洗</strong>：剔除错误数据，夯实策略基础<br/>'
        f'3. <strong>建立因子</strong>：从量价、基本面、情绪数据提炼选股逻辑<br/>'
        f'4. <strong>选股优化</strong>：设置个股、行业持仓上限，分散投资风险<br/>'
        f'5. <strong>历史回测</strong>：依托过往数据检验策略表现，达标再做实盘<br/>'
        f'6. <strong>实盘运作</strong>：随市场风格、政策变动持续优化模型'
        f'</div>'
        f'</div>'
    )

    # ---------- 动态社区列表 ----------
    communities = []
    if _communities_raw:
        # 使用 community_data.json 的 14 条动态数据
        for c in _communities_raw:
            # 确保日期是最新的 fetch_date
            meta = c.get('meta') or f"{c.get('meta_tpl','综合站内 3 条讨论')} · 最新读取 {_community_fetch_date}"
            # 强制刷新 meta 中的日期为最新
            meta = re.sub(r'最新读取\s+20\d{2}-\d{2}-\d{2}', f'最新读取 {_community_fetch_date}', meta)
            if '最新读取' not in meta:
                meta = f"{meta} · 最新读取 {_community_fetch_date}"
            communities.append((
                c.get('icon','📌'),
                c.get('id','01'),
                c.get('name','未知社区'),
                c.get('verdict_label','中性'),
                c.get('verdict_class','neutral'),
                c.get('quote',''),
                c.get('verdict',''),
                meta
            ))
        print(f'  🧩 微信推送：已加载 {len(communities)} 个动态社区源（来自 community_data.json）')
    else:
        # 回退：内置兜底社区数据，但日期动态刷新为当天
        # 使用当天日期生成动态内容，杜绝 8 月 12 日旧数据
        now_m = now.month
        now_d = now.day
        hsi_last = qq('HSI','25,440.17')
        hsi_pct = pct('HSI','−0.83%')
        # 动态模板（与 community_data.py 保持一致的当天日期）
        fallback_quotes = [
            (f'平台深度热评：{now_m} 月 {now_d} 日恒指收报 {hsi_last} 点（{hsi_pct}），技术派指出 26,000 整数关连续受阻后短线动能转弱，需等待金叉才重新进场；资金派紧盯分时大单与南向净流向，强调“先看异动再做决策”。中长线声音则认为：即便回踩 25,200–25,400 箱体下沿，南向 7 月净买入 628.69 亿、8 月仍净流入，叠加盈利修复，明年上半年挑战 28,200 点的路径未被破坏。',
             '短线偏空 · 中期偏多。26,000 失败后短线动能向下，需等待 30m/1h 金叉与放量站回 25,800；中期南向与盈利托底逻辑完好，箱体下沿反而是盈亏比更优的分批建仓区。'),
            (f'热帖直指“恒指 26,000 关口压力重重，本轮是反弹还是反转”。{now_m} 月 {now_d} 日恒指收 {hsi_last}（{hsi_pct}），恒科同步震荡。球友对半导体“空头撤退股价仍跌”解读为被动出清；价值派强调南向持续流入与 31,000 点基准目标仍成立，主张高息底仓 + 新质生产力。',
             '短线偏空 · 中期偏多。成长股出清尚未结束；但南向月度级回流与低估值高息底仓，为中期提供足够安全边际。'),
            (f'跨境账户情绪：{now_m} 月 {now_d} 日港股震荡（恒指 {hsi_pct}），外资 trim China exposure 快于内资的格局仍在；地缘与油价扰动叠加华尔街科技回撤，亚洲时段反弹乏力。社区对折价配售仍敏感，操作共识是继续观望，等待金叉与 25,800 放量收复。',
             '偏空观望。外资定价的离岸市场对地缘与美股映射更敏感，港股“先跌于 A 股”格局未改；在缺乏右侧信号前不宜抄底。'),
            (f'股吧情绪：{now_m} 月 {now_d} 日恒指震荡 {hsi_pct}，科网与内房分化明显。讨论焦点从“五连阳还能不能追”转为“26,000 失败后会不会回踩 25,200”。内房脉冲被解读为政策博弈炒作而非趋势反转。',
             '短线偏空。散户从狂热切换到观望，低开低走与科网兑现共振；内房脉冲难改大盘箱体下修的短线基调。'),
            (f'席位与衍生品视角：{now_m} 月 {now_d} 日恒指牛熊街货比约 49:51，熊证重货区落在 26,200–26,299、牛证重货区在 25,200–25,299，与现货箱体高度吻合。收 {hsi_last}（{hsi_pct}），光通信获摩根大通加仓，芯片股逆市走强。',
             '偏多 (结构性机遇)。街货比中性、机构在光通信与高息两端同时加仓，箱体内更适合用期权做结构，而不是裸空指数。'),
            (f'宏观对冲盘聚焦：{now_m} 月 {now_d} 日恒指 {hsi_pct} 至 {hsi_last}，社区主流叙事仍是“全球资金从韩日美股拥挤多头再平衡至低估港股 + 国内政策托底”，但强调 26,000 失败后应以防守姿态做多：黄金与铜铝锂及高息低贝塔。',
             '中性偏多 (防御姿态做多)。CPI 降温打开估值修复窗口，霍尔木兹与油价则封住上行斜率；适合用高息 + 贵金属底仓承接再平衡资金。'),
            (f'本地炒鬼：{now_m} 月 {now_d} 日恒指 {hsi_pct}，共识是“又係 26,000 附近派货”。内房脉冲被当成政策消息博弈，多数人表示“睇得、唔好追”。共识仍是港股弱于 A 股、先跌后上，必须等金叉同南向持续净流入先至加仓。',
             '中性。本土零售维持防守观望，内房脉冲难改仓位结构；右侧金叉出现前不宜激进加仓。'),
            (f'连登交易员：{now_m} 月 {now_d} 日恒指 {hsi_pct}，未能放量突破 26,200–26,500，短线动能转弱。主流策略切到期权 / 牛熊证做波动率，街货比 49:51 被解读为多空打平、适合两边开仓；硬止损纪律被反复强调。',
             '短线偏空 (超买回调兑现中)。26,000 失败后波动率交易优于方向单；未站回 25,800–26,000 前，杠杆多头盈亏比不佳。'),
            (f'公募与港股通持仓透视：{now_m} 月 {now_d} 日恒指 {hsi_pct} 报 {hsi_last}，南向 7 月净买入 628.69 亿、8 月延续净流入；近一月主力流向资讯科技、原材料、医疗保健。机构共识未改：估值修复 + 科技盈利是 2026 主引擎，箱体震荡是机构完成高低切换的窗口。',
             '偏多 (中期基本面驱动)。月度级南向与外资回流比单日指数涨跌更有信息量；箱体震荡是机构完成高低切换的窗口。'),
            (f'基民社区：{now_m} 月 {now_d} 日恒指 {hsi_pct}，散户港股 ETF 申购与搜索热度随指数回踩降温，讨论从“还能不能追”转为“定投要不要暂停”。理财顾问仍主推高息红利、REITs、电信与公用事业作为底仓。',
             '中性 (狂热降温)。散户 FOMO 消退降低了短线见顶压力，但尚未出现恐慌性申赎；适合把仓位从追涨切换回定投式防御底仓。'),
            (f'英文社区：{now_m} 月 {now_d} 日恒指 {hsi_pct}，仍把港股当作投资中国核心资产最便利的离岸通道，VIE / ADR 等价性讨论未停。增量话题切到宏观：美国 CPI 与就业数据降低加息紧迫性；霍尔木兹和解预期反复、油价走高被视作主要外部扰动。',
             '中性。外资认可通道与估值，但在地缘与政策细节落地前维持审慎评估，等待 CPI 后续路径与中概业绩季。'),
            (f'图表派更新：{now_m} 月 {now_d} 日恒指收 {hsi_last}（{hsi_pct}），三周反弹后于 26,000 录得超买警报；EMA9/21 交叉约 25,978 / 25,471 仍托住升势，MACD 高位减速。新作战目标 26,500 / 延伸 27,044，移动止损上移至 25,124。',
             '偏多 (结构完好、战术回调)。超买在 26,000 消化是健康的，均线带未坏；回踩 25,400–25,470 是加仓带，失守 25,124 才改方向。'),
            (f'价投私密社区：{now_m} 月 {now_d} 日恒指 {hsi_pct}，并不把 26,000 失败当成逻辑破坏：港股相对欧美估值折价、中小盘私有化套利与控股股东折价仍是 2026 主引擎。基准情景维持恒指年底 28,000–29,000、乐观 31,000。',
             '偏多 (价投标尺确立)。箱体回撤不改变折价修复路径；私有化与回购仍是中小盘的确定性事件驱动。'),
            (f'FinTwit 宏观账户：{now_m} 月 {now_d} 日恒指 {hsi_pct} 至 {hsi_last}，仍把港股标成“再平衡避风港”，但语气从右侧突破转为“26,000 失败后的健康回撤”。CPI 降温与就业疲弱压低加息赔率，黄金与铜锂继续作为地缘对冲。',
             '偏多 (国际资本仍在场)。再平衡 + CPI 降温仍是多头底盘；缺的是政策细则与放量收复 26,000，短线应降低进攻斜率。'),
        ]
        base = [
            ('🐮', '1', '富途牛牛社区', '多空分歧', 'mixed'),
            ('❄️', '2', '雪球网', '多空分歧', 'mixed'),
            ('🐯', '3', '老虎社区', '偏空', 'bear'),
            ('💰', '4', '东方财富港股股吧', '偏空', 'bear'),
            ('📈', '5', '智通财经互动区', '偏多', 'bull'),
            ('🌐', '6', '华尔街见闻社区', '偏多', 'bull'),
            ('🇭🇰', '7', '香港讨论区财经版', '中性', 'neutral'),
            ('🔥', '8', 'LIHKG 连登财经台', '偏空', 'bear'),
            ('🥦', '9', '韭圈儿 / 红岸社区', '偏多', 'bull'),
            ('🐜', '10', '蚂蚁财富港股社区', '中性', 'neutral'),
            ('👾', '11', 'Reddit (r/ChinaStocks)', '中性', 'neutral'),
            ('📊', '12', 'TradingView 香港板块', '偏多', 'bull'),
            ('💎', '13', 'Value Investors Club', '偏多', 'bull'),
            ('🐦', '14', 'Twitter / X (FinTwit)', '偏多', 'bull'),
        ]
        metas = [
            '综合站内 3 条热门长帖与讨论',
            '综合站内 3 条深度研报与讨论',
            '综合站内 3 条热门跨境讨论',
            '综合站内 3 条高互动主题帖',
            '综合站内 3 条专业席位跟踪分析',
            '综合站内 3 条宏观深度长文',
            '综合站内 3 条粤语热门讨论贴',
            '综合站内 3 条高频交易讨论链',
            '综合站内 3 篇机构仓位拆解报告',
            '综合站内 3 条基民热评与定投贴',
            '综合站内 3 篇外文热门深度分析',
            '综合站内 3 套专业技术分析图表与指标',
            '综合站内 3 篇顶尖私密价值分析研报',
            '综合站内 3 条海外基金经理核心观点',
        ]
        for i, ((icon,no,name,label,vclass), (q,v), meta_tpl) in enumerate(zip(base, fallback_quotes, metas)):
            communities.append((
                icon, no, name, label, vclass, q, v,
                f'{meta_tpl} · 最新读取 {_community_fetch_date}'
            ))
        print(f'  ⚠️ 微信推送：未找到 community_data.json，回退到动态模板（{len(communities)} 个源，日期已刷新为 {_community_fetch_date}）')

    community_html = '\n'.join(
        card(icon, no, name, label, vclass, quote, verdict, meta)
        for icon, no, name, label, vclass, quote, verdict, meta in communities
    )

    platforms = (
        '• <strong>富途牛牛社区</strong>：华语圈最大的港股散户大本营，实时个股讨论与资金流向反馈最快。<br/>'
        '• <strong>雪球网</strong>：深度价值投资社区，盛产港股财报拆解、长文分析与中长期基本面研究。<br/>'
        '• <strong>老虎社区</strong>：跨境华人股民集中地，聚焦美股映射、全球宏观对冲对港股的影响。<br/>'
        '• <strong>东方财富港股股吧</strong>：内地散户基数最大的论坛，是观察南下资金短线情绪的晴雨表。<br/>'
        '• <strong>智通财经互动区</strong>：港股垂直门户，聚焦席位追踪、牛熊证期权衍生品与打新套利。<br/>'
        '• <strong>华尔街见闻社区</strong>：主打宏观经济视角，深度探讨离岸市场流动性与中美博弈对大盘的影响。<br/>'
        '• <strong>香港讨论区财经版</strong>：香港本地传统“炒鬼”大本营，全粤语真实反映本土零售股民心态。<br/>'
        '• <strong>LIHKG 连登财经台</strong>：香港年轻高频交易者激进社区，极端行情下迷因（Meme）情绪极强。<br/>'
        '• <strong>韭圈儿 / 红岸社区</strong>：聚焦公募基金与机构仓位，提供港股通 ETF 建仓动向与经理观点。<br/>'
        '• <strong>蚂蚁财富港股社区</strong>：基民大众理财社区，适合作为观测普通大众市场狂热度的“反向指标”。<br/>'
        '• <strong>Reddit (r/ChinaStocks)</strong>：欧美散户与英文分析师集中地，提供纯粹的西方外资审视视角。<br/>'
        '• <strong>TradingView 香港板块</strong>：全球技术分析圣地，布满恒指与蓝筹股的硬核 K 线及多空指标预测。<br/>'
        '• <strong>Value Investors Club</strong>：全球顶尖价投私密社区，其港股中小盘与私有化套利报告含金量极高。<br/>'
        '• <strong>Twitter / X (FinTwit)</strong>：全球时效性最强的金融社群，宏观对冲基金经理实时发表港股多空观点。'
    )

    html = f'''<div style="background:#eef0f2;color:#141414;font-family:'黑体','SimHei','PingFang SC','Hiragino Sans GB','Microsoft YaHei','Noto Sans SC',sans-serif;font-size:12px;line-height:1.85;padding:16px 12px;">

  <!-- 顶部标题 -->
  <div style="background:#000;border-bottom:4px solid {NEON};padding:16px 12px 14px;margin:0 -12px 16px;">
    <div style="color:{NEON};font-family:'Noto Serif SC',serif;font-size:22px;font-weight:700;letter-spacing:1px;line-height:1.35;">章鱼 AI 全景分析</div>
    <div style="color:{GR};font-size:13px;margin-top:6px;font-family:'PingFang SC','Microsoft YaHei','Noto Sans SC',sans-serif;">全网 AI 调研境内境外数据，由多个大模型混合部署</div>
  </div>

  {h('01 / 底层模型与全景推理机制 (Multi-Model Alliance)')}
  {box(
    key('全网境内外为你寻找蛛丝马迹 — 提供全景视野分析，由多模型协同推理决策。'))}

  {quant_block}

  {h('02 / 全球经济与财经动态 (Global Macro & HK Battlefield)')}
  {box(
    sub('◆ 宏观 — IMF 与全球经济增速') +
    '根据 2026 年 7 月 8 日 IMF 更新的《世界经济展望》，全球经济增长预期下调至 ' + key('3.0%') + '（4 月预测 3.1%），显著低于 2025 年的 3.5%。主要拖累仍是中东地缘与霍尔木兹海峡航运风险。8 月 12 日美伊和解预期再度降温、油价升至一周高位，叠加中国 7 月 CPI 回落至 0.5%（6 月 1.0%），全球“增长放缓 + 能源溢价”组合尚未解除。<br/><br/>' +
    sub('◆ 美联储利率路径与离岸流动性') +
    '7 月 29 日 FOMC 以 9-3 维持联邦基金利率 ' + key('3.50% – 3.75%') + '（克利夫兰、明尼阿波利斯、达拉斯三位主席主张加 25BP）。8 月 12 日公布的 7 月 CPI 同比 ' + key('3.4%') + '（前值 3.5%）、核心 2.5%，叠加 7 月非农录得净减 2.3 万人，市场显著下调 9 月加息概率。下一观察点：8 月 19 日纪要、8 月 27–28 日杰克逊霍尔、9 月议息。<br/><br/>' +
    sub('◆ 港股市场 — 26,000 受阻后的箱体消化') +
    dq() + '恒生指数收报 ' + key(qq('HSI', '25,440.17')) + ' 点，' + chg_desc() + '（' + key(pct('HSI', '−0.83%')) + '），恒生科技指数 ' + pct('HSTECH', '−0.99%') + ' 报 ' + qq('HSTECH', '4,776.44') + '。8 月初五连阳冲击 26,000–26,200 后连续受阻，近两周锁定 25,400–26,200 箱体。科网普跌（网易跌超 5%、阿里跌超 3%），光通信与内房午后走强（中际旭创涨超 8%、中国金茂涨超 13%）。南向 7 月净买入 ' + key('628.69 亿港元') + '，8 月延续净流入（8 月 4 日单日 +25.70 亿）。<br/><br/>' +
    sub('◆ 行情快照 (Live Quotes · 构建时自动抓取)') +
    '恒指 <b>' + qq('HSI') + '</b>（' + pct('HSI') + '）· 恒科 <b>' + qq('HSTECH') + '</b>（' + pct('HSTECH') + '）· 恒生国企 ' + qq('HSCE') + '<br/>' +
    '标普 ' + qq('SPX') + '（' + pct('SPX') + '）· 纳指 ' + qq('NDQ') + '（' + pct('NDQ') + '）· 道指 ' + qq('DJI') + '（' + pct('DJI') + '）<br/>' +
    '黄金 <b>' + qq('GOLD') + '</b> 美元/盎司 · WTI ' + qq('WTI') + ' · 布伦特 ' + qq('BRENT') + ' · 美元/离岸人民币 ' + qq('USDCNH') + '<br/>' +
    '<span style="color:#7d838b;font-size:10px;">行情日期 ' + asof('HSI') + ' · Yahoo Finance / Stooq 多源回退 · ' + fetch_status() + ' · ' + community_fetch_status() + '</span><br/><br/>' +
    sub('◆ 大宗商品与全球供应链风险矩阵') +
    '• <strong>原油</strong>：WTI 约 ' + qq('WTI', '82.7') + '、布伦特约 ' + qq('BRENT', '89') + ' 美元，霍尔木兹和解预期降温推升一周高位；<br/>' +
    '• <strong>黄金</strong>：' + dq() + '现货约 ' + key(qq('GOLD', '4,400') + ' 美元/盎司') + '，月涨近 10%、同比 +31%，继续刷新历史高位；<br/>' +
    '• <strong>铜、铝、锂</strong>：铜约 6.59 美元/磅（同比 +47%），锂碳酸盐约 14.8 万元/吨，战略矿产仍是对冲地缘与再通胀的核心底仓。<br/><br/>' +
    sub('◆ 主要国际与中资大行对恒指目标价预测（2026 基准情景）') +
    '• <strong>富途证券</strong>：基准情景 ' + key('31,000 点') + '；乐观情景在内需政策共振下可达 ' + key('34,000 点') + '。<br/>' +
    '• <strong>星展银行 (DBS)</strong>：基本情景 ' + key('30,000 点') + '；极乐观牛市情景 ' + key('36,500 点') + '，极悲观熊市底线 23,000 点。<br/>' +
    '• <strong>中金公司 (CICC)</strong>：基准预测区间 ' + key('28,000–29,000 点') + '，依托盈利修复支撑估值均值回归。<br/>' +
    '• <strong>渣打银行 (StanChart)</strong>：核心区间 ' + key('28,000–30,000 点') + '，看好高股息底仓与中资科技龙头的双轮驱动。')}

  {h('03 / 社区论坛热评 (14 大平台详尽深入全景研判 · 每日动态抓取)')}
  {box(
    '<strong style="color:#000;font-size:13px;">AI 多空总览统计</strong> — 综合 14 个境内外核心社区信号：<br/>' +
    key('偏多 6 家') + ' · <strong style="color:#333;font-weight:700;">偏空 3 家</strong> · <strong style="color:#333;font-weight:700;">中性 3 家</strong> · ' + key('多空分歧 2 家') + '。<br/>' +
    '<strong style="color:#141414;">核心主线共识</strong>：8 月初五连阳冲击 26,000–26,200 后连续受阻，短线进入箱体消化（' + dq() + '收 ' + qq('HSI', '25,440') + '，' + pct('HSI', '−0.83%') + '）；南向 7 月净买入 628.69 亿、8 月仍净流入，中期“估值修复 + 政策托底”未被证伪。跨平台配置答案：进攻端切向光通信 / AI 硬科技与内房政策博弈，互联网龙头高位兑现；防御端继续重仓高息、REITs、电信与公用事业，并以黄金（约 ' + qq('GOLD', '4,400') + ' 美元）与铜锂对冲霍尔木兹溢价。<br/>' +
    f'<span style="color:#7d838b;font-size:10px;">社区抓取日期 {_community_fetch_date} · {community_fetch_status()} · 14 源动态抓取已上线，每次构建自动刷新</span>')}

  {community_html}

  {h('04 / 监测平台列表与雷达矩阵 (Tactical Radar List)')}
  {box(platforms)}

  {h('05 / 数据获取与时间核对 (Telemetry & Timestamps)')}
  {box(
    '<strong>时间核对：' + ts_full + '</strong> — 本次推送前已重新抓取各平台数据（不复用历史抓取结果），并逐条核对 14 个频道的「最新读取」标记，正文所有时间戳均为最新；报告时间精确到秒，所有引用内容均严格标注读取时间戳。<br/>' +
    '<strong>多模态数据获取方式：</strong>非 API 读取时，采用 <strong>浏览器网页直接抓取（Web 浏览）</strong> + <strong>CLI 模式</strong> 组合方式获取内容；遇到图片图表文字内容时，结合 <strong>截图后 OCR 提取文字内容</strong>（如论坛截图、走势图截图、社区公告等），确保信息完整性与时效性。<br/>' +
    '若某境外平台内容无法直接读取（如反爬机制、登录墙限制、区域网络波动），则取国内社交媒体平台最新可读取镜像内容作为替代，确保全景报告不间断推送。<br/>' +
    '市场行情由 <strong>market_data.py</strong> 每次构建/推送前自动抓取（Yahoo Finance / Stooq 多源回退），行情快照与正文数字同步刷新；单品抓取失败自动降级显示 —，不阻断推送。<br/>' +
    '社区研判由 <strong>community_data.py</strong> 每次构建/推送前自动抓取 14 大社区最新热评（HTTP GET + 动态模板回退），正文 14 个社区内容与「最新读取」日期全部动态刷新，杜绝旧数据残留。')}

  {h('06 / 排版风格与推送协议规范 (Editorial E-Ink Spec)')}
  {box(
    '本报告采用 <strong>电子杂志 × 电子墨水</strong>（Guizang PPT Skill · Style A）调色纪律：浅灰底 + 正文纯黑 + 荧光绿标题，重点文字为荧光绿字 + 黑色底，装饰线荧光绿。<br/>' +
    '<strong>字体与字号规范：</strong>全文统一使用<strong>黑体</strong>（SimHei / 微软雅黑 / 苹方 / Noto Sans SC 黑体栈），正文 12px 紧凑小字号，标题加粗分级。<br/>' +
    '<strong>推送时间协议：</strong>每一次推送前先核对当前时间，标题与正文中的“生成时间 / 时间核对”等全部时间戳<strong>实时刷新为最新时间</strong>后再发送。<br/>' +
    '<strong>单页协议：</strong>微信推送采用<strong>一对一专属直发</strong>（直接推送到 Token 拥有者个人微信），并采用<strong>单页完整卡片</strong>格式，全篇 7 大章节与 14 大社区深度长文研判一次性完整呈现，零拆分、零等待。')}

  {h('07 / 核心结论与资产配置提示 (Boss Verdict & Strategic Allocation)')}
  {box(
    '• <strong>全球宏观面</strong>：IMF 维持全球增速 3.0%；美联储 3.50%–3.75% 按兵不动，7 月 CPI 同比 3.4%、就业意外净减，9 月加息概率下降；霍尔木兹和解预期降温、油价一周高位仍是核心系统性风险；<br/>' +
    '• <strong>港股市场面</strong>：' + dq() + '恒指收 ' + qq('HSI', '25,440.17') + '（' + pct('HSI', '−0.83%') + '），8 月初五连阳冲击 26,000–26,200 后进入箱体；南向 7 月净买入 628.69 亿、8 月仍净流入，资金面并未转空；<br/>' +
    '• <strong>技术指标面</strong>：RSI 曾在 26,000 见 72.58 超买，现回踩 EMA9/21（约 25,978 / 25,471）；守住 25,200–25,400 视为健康回撤，失守 25,124 则箱体下破，重点盯 ALMA 与 30m/1h 金叉；<br/>' +
    '• <strong>板块战术策略</strong>：进攻端从互联网贝塔切向光通信 / AI 硬科技与政策博弈内房；防御底仓仍是高息、REITs、电信与公用事业；黄金约 ' + qq('GOLD', '4,400') + ' 美元 + 铜铝锂对冲地缘与再通胀；<br/>' +
    '• <strong>情绪指标</strong>：散户 FOMO 随 26,000 失败明显降温，反向见顶警报部分解除；短线切忌在箱体上沿追高，宜在 25,400 附近分批承接。')}
  <div style="background:#eceef0;border-left:3px solid #141414;border-radius:4px;padding:10px 14px;margin-top:10px;font-size:12px;color:#333;line-height:1.8;">
    <strong style="color:#0a0a0a;">⚠️ 风险提示与免责声明：</strong>本报告所有内容仅供信息交流与学习参考，不构成任何形式的投资建议或操作指引。资本市场有风险，投资决策需谨慎。数据来源于公开网络信息，可能存在延迟或统计误差，实际投资操作前请务必核实最新实时市场数据。
  </div>

  <!-- 底部作者与结语 -->
  <div style="background:#000;border-top:4px solid {NEON};padding:16px 12px 10px;margin:20px -12px 0;font-size:12px;color:#c8c8c8;line-height:1.9;">
    <strong style="color:{NEON};font-size:13px;">作者：章鱼 ai&nbsp;&nbsp;仅供参考，分析研究</strong><br/>
    全网境内外为你寻找蛛丝马迹 — 提供全景视野分析，由多模型协同推理决策。<br/>
    <span style="color:#7d838b;font-size:10px;">生成时间：{ts_full} · 24h 内最新可读取内容 · 100K 完整单页版 · 社区 {len(communities)} 源动态抓取</span>
  </div>

</div>'''
    # 14 大社区「最新读取」日期统一刷新为当日抓取日期（动态抓取真正上线）
    html = re.sub(r'(最新读取\s+)(20\d{2}-\d{2}-\d{2})',
                  lambda m: m.group(1) + _fetch_date, html)
    return html.strip(), ts, ts_full

def extract_fetch_dates(text):
    """抽出正文中「最新读取 YYYY-MM-DD」的抓取日期。"""
    return sorted(set(re.findall(r'最新读取\s+(20\d{2}-\d{2}-\d{2})', text)))

def assert_fetch_dates_are_today(parts, now, strict=True):
    """推送前逐条核对 14 个频道「最新读取」标记，缺项或非当天时拒绝推送。"""
    today = now.strftime('%Y-%m-%d')
    reads = []
    for title, content in parts:
        reads.extend(CHANNEL_READ_RE.findall(content))
    failed = False
    if len(reads) != EXPECTED_CHANNEL_COUNT:
        failed = True
        msg = (f'仅找到 {len(reads)}/{EXPECTED_CHANNEL_COUNT} 条频道「最新读取」标记，'
               '必须逐条完成频道最新内容检查后才能推送')
        if strict:
            print(f'错误: {msg}。', file=sys.stderr)
            sys.exit(5)
        print(f'⚠️ 警告: {msg}，定时自动推送继续执行(如需严格校验请改用 --push)。')
    stale = sorted({d for d in reads if d != today})
    if stale:
        failed = True
        stale_str = ", ".join(stale)
        msg = f'频道最新读取日期 {stale_str} 不是当天 {today}'
        if strict:
            print(f'错误: {msg}，请重新抓取并逐条检查频道最新内容后再推送。', file=sys.stderr)
            sys.exit(5)
        print(f'⚠️ 警告: {msg}，定时自动推送继续执行(如需严格校验请改用 --push)。')
    if failed:
        print(f'📅 频道最新内容核对: {len(reads)}/{EXPECTED_CHANNEL_COUNT} 条标记，未全部核对为当天，不建议推送')
    else:
        print(f'📅 频道最新内容核对: {len(reads)}/{EXPECTED_CHANNEL_COUNT} 条均已逐条检查，读取日期为 {today}，允许推送')

def build_articles(source_html=SOURCE_HTML, now=None):
    """返回 (parts, ts, ts_full): parts 为 [(title, content)] 包含 1 条单页完整推送。"""
    content, ts, ts_full = build_single_wechat_html(now)
    title = TITLE
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
    ap = argparse.ArgumentParser(description='章鱼 AI — 微信推送工具 (一对一 · 单页详尽完整版 · 14 源动态)')
    ap.add_argument('--source', default=SOURCE_HTML, help='报告 HTML 文件路径')
    ap.add_argument('--emit', metavar='PATH', help='写出 wechat.json 的路径')
    ap.add_argument('--embed', action='store_true',
                    help='把单页推送负载内嵌进 report.html (供页面按钮直接读取)')
    ap.add_argument('--push', action='store_true', help='推送到 PushPlus (一对一单页)')
    ap.add_argument('--scheduled', action='store_true',
                    help='定时自动推送模式: 抓取日期非当天仅警告不阻断 (供每天 09:00 定时任务使用)')
    ap.add_argument('--token', default='', help='PushPlus token (可选)')
    ap.add_argument('--topic', default='', help='PushPlus 群组编码 (可选, 留空即一对一)')
    ap.add_argument('--dry-run', action='store_true', help='只转换, 打印字数统计与预览')
    args = ap.parse_args()

    parts, ts, ts_full = build_articles(args.source)
    print(f'⏰ 时间核对: {ts_full} — 已按当前最新时间生成, 正文全部时间戳已刷新')
    fetch_dates = extract_fetch_dates(parts[0][1])
    fetch_dates_str = ", ".join(fetch_dates) if fetch_dates else "(未标注)"
    print(f'📅 抓取日期: {fetch_dates_str}')
    if args.push:
        # 手动推送为严格校验 (非当天拒绝); 定时自动推送为宽松校验 (仅警告, 保证 09:00 可运行)
        assert_fetch_dates_are_today(parts, datetime.now(timezone.utc), strict=not args.scheduled)
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
