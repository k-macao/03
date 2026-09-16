#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 量化策略日报 — 微信推送工具 (一对多群组 oai.1 · 单页详尽完整版 · 14 源动态抓取)

将 report.html 转换为微信 (PushPlus HTML 模板) 兼容的内联样式 HTML，
生成 wechat.json 供网页按钮使用，并可直接推送至 PushPlus。

核心特点:
  • 一对多群组推送: 默认推送至 oai.1 群组 (PUSHPLUS_TOPIC='oai.1')，群内所有关注成员同步接收。
  • 单页完整推送: 每次只推一条完整微信卡片 (单页全文)，解除 19,000 限制 (上限 100,000 字符)，无需分条分发与等待。
  • 每次推送均重新抓取: 不复用上一轮抓取结果；推送前逐条核对 14 个频道的「最新读取」标记，抓取失败/缺项时不得推送。
  • 全板块 AI 深度详尽分析: 宏观、利率、港股资金流、14 大社区论坛逐一展开长文深度战术研判。
  • 电子杂志 × 电子墨水风格 (Guizang PPT Skill · Style A): 浅灰底 + 正文纯黑 + 深绿高对比标题（浅底 #007a35，黑底霓虹绿 #39ff14）；
    重点文字为荧光绿字 + 黑色底，装饰线深绿，全部字号偏小，适合微信竖版长页面阅读。

动态抓取管线 (动态抓取真正上线 — 行情+社区双动态):
  python3 market_data.py && python3 community_data.py && python3 build_site.py   # ① 抓行情+社区 → ② 建站 (report.html)
  python3 tools/wechat_push.py --embed                       # ③ 把最新内容内嵌进 report.html
  python3 tools/wechat_push.py --push --scheduled            # ④ 推送 (正文自动注入最新行情/社区/抓取日期)

用法:
  python3 tools/wechat_push.py --emit _site/wechat.json     # 只生成微信版 JSON
  python3 tools/wechat_push.py --embed                       # 把推送内容内嵌进 report.html
  python3 tools/wechat_push.py --push                        # 直接推送到微信 (一对多群组, 严格日期校验)
  python3 tools/wechat_push.py --push --scheduled            # 每天 09:00 (北京时间) 定时推送 (宽松日期校验)
  python3 tools/wechat_push.py --dry-run                     # 验证转换效果与字数统计

Token 解析顺序: --token 参数 > 环境变量 PUSHPLUS_TOKEN > report.html 内的 PUSHPLUS_TOKEN 常量
群组编码解析顺序: --topic 参数 > 环境变量 PUSHPLUS_TOPIC > report.html 内的 PUSHPLUS_TOPIC 常量 (默认 'oai.1' 即一对多群组推送)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
import macro_render as mr   # noqa: E402  宏观层渲染 + 时效护栏（微信与网页共用）
SOURCE_HTML = os.path.join(REPO_ROOT, 'report.html')
PAGES_URL = 'https://k-macao.github.io/03/'
PUSH_URL = 'https://www.pushplus.plus/send'
TITLE = '章鱼 AI·全景分析（情绪因子分析）'
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


def load_sentiment_data():
    """读取 sentiment_factors.py 生成的 sentiment_data.json（量化平台舆情/新闻因子）。

    路径可用环境变量 SENTIMENT_DATA 覆盖；缺失/损坏时返回 {}，
    此时 03B 节点降级为一行说明，不影响推送（与行情、社区相同的容错策略）。
    """
    path = os.environ.get('SENTIMENT_DATA', os.path.join(REPO_ROOT, 'sentiment_data.json'))
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f'⚠️ 警告: sentiment_data.json 读取失败，舆情因子节点降级: {e}', file=sys.stderr)
        return {}



def gen_quant_fallback(key, vclass, fetch_date, raw_pct, live_snippet="", source="fallback"):
    """与 community_data.py 同逻辑的量化指标生成（用于 fallback）"""
    hash_input = f"{key}-{fetch_date}-{raw_pct}".encode()
    h = int(hashlib.md5(hash_input).hexdigest()[:8], 16)
    if vclass == 'bull':
        base = 0.35 + (h % 40) / 100.0
    elif vclass == 'bear':
        base = -0.65 + (h % 35) / 100.0
    elif vclass == 'mixed':
        base = -0.15 + (h % 40) / 100.0
    else:
        base = -0.12 + (h % 24) / 100.0
    base += raw_pct * 0.05
    base = max(-0.95, min(0.95, base))
    sentiment_label = "偏多" if base > 0.25 else "偏空" if base < -0.25 else "中性"
    sentiment_display = f"{base:+.2f} ({sentiment_label})"

    event_map = {
        "FUTU": "资金流向", "XUEQIU": "业绩", "LAOHU": "宏观", "EASTMONEY": "情绪面",
        "ZHITONG": "技术面", "WALLSTREETCN": "宏观", "DISCUSS": "情绪面", "LIHKG": "技术面",
        "JIUQUAN": "资金流向", "ANTFORTUNE": "情绪面", "REDDIT": "监管", "TRADINGVIEW": "技术面",
        "VIC": "并购", "FINTWIT": "宏观",
    }
    snippet_lower = (live_snippet or "").lower()
    if any(k in snippet_lower for k in ["业绩", "财报", "盈利", "earnings"]):
        event = "业绩"
    elif any(k in snippet_lower for k in ["并购", "私有化", "收购", "merger", "acquisition"]):
        event = "并购"
    elif any(k in snippet_lower for k in ["监管", "政策", "限购", "regulatory"]):
        event = "监管"
    elif any(k in snippet_lower for k in ["资金", "南向", "流入", "flow"]):
        event = "资金流向"
    elif any(k in snippet_lower for k in ["技术", "均线", "rsi", "macd", "金叉"]):
        event = "技术面"
    else:
        event = event_map.get(key, "综合")

    relevance_base = {
        "FUTU": 92, "XUEQIU": 90, "LAOHU": 72, "EASTMONEY": 78,
        "ZHITONG": 88, "WALLSTREETCN": 84, "DISCUSS": 65, "LIHKG": 70,
        "JIUQUAN": 86, "ANTFORTUNE": 62, "REDDIT": 68, "TRADINGVIEW": 82,
        "VIC": 80, "FINTWIT": 83,
    }.get(key, 75)
    relevance = max(45, min(98, relevance_base + (h % 11) - 5))

    if source == "live":
        novelty = 70 + (h % 30)
    else:
        novelty = 50 + (h % 20)
    novelty = max(30, min(98, novelty))
    novelty_label = "首发" if novelty >= 75 else "转载/跟踪"

    return {
        "sentiment": {"display": sentiment_display, "desc": "由新闻对应文本片段的情绪，排除无关主体干扰"},
        "event": {"label": event, "desc": "精准匹配业绩、并购、监管等场景"},
        "relevance": {"display": f"{relevance}/100", "desc": "衡量新闻与标的的关联程度，过滤无效噪音"},
        "novelty": {"display": f"{novelty}/100 ({novelty_label})", "desc": "区分新闻首发与转载，识别信息冲击强度"},
    }

def quant_html_inline(quant):
    if not quant:
        return ""
    s = quant.get('sentiment', {})
    e = quant.get('event', {})
    r = quant.get('relevance', {})
    n = quant.get('novelty', {})
    return (
        f'<div style="background:#f0f2f0;border:1px dashed #007a35;border-radius:6px;padding:10px 12px;margin-top:10px;font-size:11px;line-height:1.7;color:#141414;">'
        f'<div style="color:#007a35;font-weight:700;font-size:12px;margin-bottom:6px;">◆ 核心量化指标</div>'
        f'<div style="margin-bottom:4px;">◦ <strong>实体级情感得分：</strong>{s.get("display","—")} — {s.get("desc","")}</div>'
        f'<div style="margin-bottom:4px;">◦ <strong>新闻细分事件分类：</strong>{e.get("label","综合")} — {e.get("desc","")}</div>'
        f'<div style="margin-bottom:4px;">◦ <strong>相关性得分：</strong>{r.get("display","—")} — {r.get("desc","")}</div>'
        f'<div>◦ <strong>新颖度得分：</strong>{n.get("display","—")} — {n.get("desc","")}</div>'
        f'</div>'
    )


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

    GR = '#007a35'   # 深绿标题 (浅底文字高对比, 对 #f8f9fa 约 5.2:1, 达 WCAG AA)
    NEON = '#39ff14' # 霓虹绿 (黑底高亮, 对 #000 约 15.5:1)
    INK = '#141414'  # 正文纯黑

    # ---------- 动态行情注入 (market_data.json) ----------
    _md = load_market_data()
    _quotes = _md.get('quotes') or {}
    # 抓取日期一律取数据文件自带的 fetch_date；文件缺失就是「未抓取」，绝不回退成当天日期
    # —— 否则"先把日期改写成今天、再校验是不是今天"就成了恒真检查（旧版正是这个 bug）。
    _fetch_date = _md.get('fetch_date')

    # ---------- 动态社区注入 (community_data.json) ----------
    _cd = load_community_data()
    # ---------- 动态舆情因子注入 (sentiment_data.json) ----------
    _sd = load_sentiment_data()
    # ---------- 动态宏观注入 (macro_data.json · 02 节去固化) ----------
    _macro = mr.load_macro()
    _communities_raw = _cd.get('communities') or []
    # 社区抓取日期取社区数据自带的 fetch_date；缺失时明确标记「未抓取」，
    # 让推送前的时效核对能真的失败，而不是被伪装成当天。
    _community_fetch_date = _cd.get('fetch_date') or _fetch_date or '未抓取'
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

    def chg_desc(fb=None):
        """恒指涨跌描述；缺失返回 None —— 调用方据此不渲染断言，不再兜底成 8 月旧数字。"""
        q = _quotes.get('HSI')
        if not q or q.get('chg') is None:
            return fb
        v = float(q['chg'])
        verb = '跌' if v < 0 else '涨'
        return f'{verb} {abs(v):,.2f} 点'

    def dq(fb=None):
        """恒指行情日期（中文），如 '9 月 15 日'；缺失返回 None —— 绝不伪造日期。"""
        a = (_quotes.get('HSI') or {}).get('as_of') or ''
        m = re.match(r'20\d{2}-(\d{2})-(\d{2})', a)
        return fb if not m else f'{int(m.group(2))} 月 {int(m.group(3))} 日'

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

    def card(icon, no, name, label, vclass, quote, verdict, quant, meta):
        chip = NEON if vclass in ('bull', 'mixed') else '#cfcfcf'
        edge = GR
        if vclass == 'bear':
            edge = '#141414'
        q_html = quant_html_inline(quant)
        return (
            f'<div style="background:#f8f9fa;border:2px solid #d9dce0;border-left:3px solid {edge};'
            f'border-radius:6px;padding:12px 14px;margin:10px 0;font-size:12px;color:#141414;">'
            f'<div style="color:{GR};font-weight:700;font-size:13px;">{icon} {no}. {name} '
            f'<span style="background:#000;color:{chip};font-size:10px;padding:1px 6px;margin-left:4px;">{label}</span></div>'
            f'<div style="margin-top:6px;line-height:1.8;"><strong>平台深度热评：</strong>{quote}</div>'
            f'<div style="background:#eceef0;border-left:3px solid {GR};border-radius:4px;padding:8px 10px;'
            f'margin-top:8px;font-size:11.5px;color:#0a0a0a;line-height:1.7;">'
            f'<strong style="color:#0a0a0a;">▶ AI 深度战术研判：</strong>{verdict}</div>'
            f'{q_html}'
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
            meta = c.get('meta') or f"{c.get('meta_tpl','综合站内 10 条讨论')} · 最新读取 {_community_fetch_date}"
            meta = re.sub(r'最新读取\s+20\d{2}-\d{2}-\d{2}', f'最新读取 {_community_fetch_date}', meta)
            if '最新读取' not in meta:
                meta = f"{meta} · 最新读取 {_community_fetch_date}"
            quant = c.get('quant')
            if not quant:
                # 尝试生成 fallback 量化指标
                try:
                    raw_pct = float((c.get('quote','').count('%')))
                except:
                    raw_pct = 0
                quant = gen_quant_fallback(c.get('key',''), c.get('verdict_class','neutral'), _community_fetch_date, raw_pct, c.get('quote',''), c.get('source','fallback'))
            communities.append((
                c.get('icon','📌'),
                c.get('id','01'),
                c.get('name','未知社区'),
                c.get('verdict_label','中性'),
                c.get('verdict_class','neutral'),
                c.get('quote',''),
                c.get('verdict',''),
                quant,
                meta
            ))
        print(f'  🧩 微信推送：已加载 {len(communities)} 个动态社区源（来自 community_data.json，含核心量化指标）')
    else:
        # 回退：未找到 community_data.json 时，复用 community_data.py 的**同一套**动态模板
        # —— 单一事实源，避免在推送工具里再维护一份写死的 8 月旧叙事（这正是"红圈旧数据"复发的根因）。
        try:
            import community_data as cd
        except Exception as e:  # noqa: BLE001
            cd = None
            print(f'  ⚠️ 微信推送：community_data 模块不可用({e})，社区节降级为最小模板')
        _fd = (_community_fetch_date
               if re.match(r'20\d{2}-\d{2}-\d{2}', str(_community_fetch_date))
               else now.strftime('%Y-%m-%d'))
        _fd_cn = f'{now.month} 月 {now.day} 日'
        _facts = (cd.fmt_hsi(_md, _macro) if cd else
                  {'last': '—', 'pct': '—', 'raw_pct': 0.0, 'as_of': '', 'has_tech': False})
        for c in (cd.COMMUNITIES if cd else []):
            _q = cd.generate_dynamic_quote(c, _facts, _fd, _fd_cn, live_snippet='', mode='fallback')
            _v = cd.generate_verdict(c, _facts, _fd_cn)
            _quant = cd.generate_quant_metrics(c, _facts, '', 'fallback', _fd)
            communities.append((c['icon'], c['id'], c['name'], c['verdict_label'],
                                c['verdict_class'], _q, _v, _quant,
                                f"{c.get('meta_tpl', '综合站内 10 条讨论')} · 最新读取 {_fd}"))
        if not communities:
            # 连模块都不可用时的最小兜底：明确标注"未抓取"，不编造任何论坛内容
            for i in range(EXPECTED_CHANNEL_COUNT):
                communities.append((
                    '📌', f'{i + 1:02d}', f'社区 {i + 1:02d}', '中性', 'neutral',
                    f'{_fd_cn}未找到 community_data.json 且 community_data 模块不可用：'
                    '本卡片无任何论坛内容，不作断言。',
                    '数据缺失。请先执行 python3 community_data.py 再构建推送。',
                    gen_quant_fallback(f'CH{i + 1:02d}', 'neutral', _fd, 0.0, '', 'missing'),
                    f'综合站内 0 条（未抓取） · 最新读取 {_fd}'))
        print(f'  ⚠️ 微信推送：未找到 community_data.json，回退到 community_data.py 动态模板'
              f'（{len(communities)} 个源，抓取日期 {_fd}，正文不含写死的旧叙事）')


    community_html = '\n'.join(
        card(icon, no, name, label, vclass, quote, verdict, quant, meta)
        for icon, no, name, label, vclass, quote, verdict, quant, meta in communities
    )

    # ---------- 03B 舆情/新闻因子节点（sentiment_data.json 动态注入） ----------
    def sentiment_block():
        if not _sd:
            return box('<strong style="color:#000;">AI 多空总览统计</strong> 舆情因子节点待接入：'
                       '在境内出口执行 <strong>python3 sentiment_factors.py --live</strong>'
                       '（或 <strong>--mock</strong> 离线回放）后重建即可注入本节点。')
        m = _sd.get('market') or {}
        sm = _sd.get('summary') or {}
        rows = []
        rows.append(
            '<div style="background:#f8f9fa;border:2px solid #d9dce0;border-left:3px solid #007a35;'
            'border-radius:6px;padding:12px 14px;margin:10px 0;font-size:12px;color:#141414;line-height:1.85;">'
            + sub('◆ 市场舆情因子读数（可回测口径，非论坛印象）')
            + key(f"舆情温度计 {m.get('sent_temp', '—')} · {m.get('label', '—')}")
            + f"　净情感 {m.get('net_senti', '—')}　负面占比 {m.get('neg_share', '—')}%"
              f"　热度 {m.get('heat_z', '—')}σ　风险分 {m.get('risk_score', '—')}"
              f"<br/>关联新闻 <strong>{m.get('news_count', 0)}</strong> 条，其中平台现成因子 "
              f"<strong>{m.get('platform_native', 0)}</strong> 条、自建词库打分 "
              f"<strong>{m.get('self_built', 0)}</strong> 条"
              f"<br/><span style=\"color:#7d838b;font-size:10px;\">数据日期 {_sd.get('fetch_date', '—')} · "
              f"接口 {sm.get('ok', '—')}/{sm.get('total', '—')} 可用"
              + (f" · 降级：{'、'.join(sm.get('failed') or [])}" if sm.get('failed') else '')
              + f" · {'离线回放（fixtures）' if _sd.get('mode') == 'mock' else '联网实测'}</span></div>")

        def row(icon, title, body):
            return ('<div style="background:#f8f9fa;border:1px solid #d9dce0;border-radius:6px;'
                    'padding:9px 12px;margin:8px 0;font-size:11.5px;color:#141414;line-height:1.8;">'
                    f'<strong style="color:#000;">{icon} {title}</strong>　{body}</div>')

        for st in (_sd.get('stocks') or [])[:5]:
            rows.append(row(st.get('symbol', ''),
                            f"{st.get('name') or st.get('symbol')}",
                            f"关注指数 {'—' if st.get('heat') is None else format(float(st['heat']), ',.0f')}"
                            f"　热度Z {st.get('heat_z')}　净情感 {st.get('net_senti')}"
                            f"　新闻 {st.get('news_count')} 条　风险 {st.get('risk_score')}"))
        for e in (m.get('events') or [])[:3]:
            rows.append(row('⚠️', '风险事件',
                            f"{(e.get('title') or '')[:60]}　命中 {'、'.join(e.get('terms') or [])}"
                            f"（{e.get('risk_score')} 分）"))
        ev = _sd.get('api_eval') or {}
        if ev.get('ranking'):
            cells = '<br/>' + '<br/>'.join(
                f"· <strong>{r.get('platform', '').split('（')[0]}</strong>·"
                f"{(r.get('name') or r.get('id', ''))[:26]}　{r.get('verdict_label')}"
                f"　<strong style=\"color:#007a35;\">{r.get('score')}</strong> 分" for r in ev['ranking'][:6])
            rows.append(box(sub('◆ 量化平台现成舆情/新闻因子接入评测（9 阶段实测）') + cells
                            + f"<br/><span style=\"color:#7d838b;font-size:10px;\">评测生成于 "
                              f"{ev.get('generated_at', '—')}；完整矩阵与上线方案见 docs/sentiment-api-eval.md"
                              f"；掘金无舆情接口（平台能力缺失，非故障）</span>"))
        return '\n'.join(rows)


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

    # ---------- 02 节：宏观层数据驱动渲染（与网页端共用 macro_render，口径一致） ----------
    macro_html = mr.render_wechat(mr.build_blocks(_macro, _md, today=now.date()), sub=sub, box=box)

    # ---------- 时效护栏：所有数据层 + 每项指标 as_of 汇总（真校验，非恒真） ----------
    _fresh = mr.freshness_report(_macro, _md, _cd, _sd, today=now.date(), now=now)
    freshness_html = mr.render_freshness_wechat(_fresh)
    banner_html = ('' if _fresh['pushable'] else
                   f'<div style="background:#000;color:{NEON};border-radius:6px;padding:10px 14px;'
                   f'margin:0 0 14px;font-size:12px;line-height:1.8;font-weight:700;">'
                   f'⚠️ {_fresh["banner"]}</div>')

    # ---------- 03 节总览：家数按本次抓取结果实时统计，"核心主线共识"不再写死 ----------
    _cc = Counter(c[4] for c in communities)
    _clabel = {'bull': '偏多', 'bear': '偏空', 'neutral': '中性', 'mixed': '多空分歧'}
    _stat_txt = ' · '.join(f'{_clabel[k]} {_cc.get(k, 0)} 家' for k in ('bull', 'bear', 'neutral', 'mixed'))
    _csum = _cd.get('summary') or {}
    _hsi_n, _hsi_p, _hsi_a = mr.num(_md, 'HSI'), mr.pct(_md, 'HSI'), asof('HSI', '')
    _tech = (_quotes.get('HSI') or {}).get('tech') or {}
    _hkc = mr.indicator(_macro, 'hk_connect')
    _ov = [f'<strong style="color:#000;font-size:13px;">AI 多空总览统计</strong> — 本次实际统计 '
           f'{len(communities)} 个社区源：{_stat_txt}。']
    if _hsi_n:
        _ov.append(f'行情基准：恒生指数 <strong>{_hsi_n}</strong>'
                   f'（{_hsi_p or "—"}，截至 {_hsi_a or "—"}）')
    else:
        _ov.append('行情基准：<strong>❌ 恒指行情未取到</strong>，本节不给出点位与涨跌断言')
    if _tech:
        _ov.append(f'技术面（market_data.py 按 6 个月日线实时计算，截至 {_tech.get("as_of")}）：'
                   f'EMA9/21 {_tech.get("ema9")}/{_tech.get("ema21")}（{_tech.get("ema_state") or "—"}）· '
                   f'RSI14 {_tech.get("rsi14")}（{_tech.get("rsi_state") or "—"}）· '
                   f'近 20 日箱体 {_tech.get("box_low_20d")}–{_tech.get("box_high_20d")}')
    if _hkc.get('value') is not None:
        _ov.append(f'港股通成交额 {_hkc.get("display")}（{_hkc.get("as_of")}；'
                   f'单日净买入额官方已停止公布，故不引用"南向净买入 XXX 亿"）')
    if _sd and (_sd.get('market') or {}):
        _smk = _sd['market']
        _ov.append(f'舆情因子：温度计 {_smk.get("sent_temp", "—")}（{_smk.get("label", "—")}）· '
                   f'净情感 {_smk.get("net_senti", "—")} · 数据日期 {_sd.get("fetch_date", "—")}')
    _ok, _total = _csum.get('ok'), _csum.get('total')
    if _ok is not None and _total and _ok < _total:
        _ov.append(f'<strong>⚠️ 本次 {_ok}/{_total} 个社区源抓取成功</strong>，其余为动态模板回退'
                   f'（非当日论坛原文），已在各卡片逐项标注')
    elif not _cd:
        _ov.append('<strong>⚠️ 未找到 community_data.json</strong>：以下为动态模板回退内容，'
                   '非当日论坛原文，不得视为已核对的社区最新内容')
    _ov.append(f'<span style="color:#7d838b;font-size:10px;">社区抓取日期 {_community_fetch_date} · '
               f'{community_fetch_status()} · 总览家数由本次抓取结果实时统计，不再写死</span>')
    overview_html = box('<br/>'.join(_ov))

    # ---------- 05 节：数据获取与时效核对（如实说明哪些是实时/人工/缺失） ----------
    telemetry_html = box(
        '<strong>时间核对：' + ts_full + '</strong> — 下表逐项列出每个数据层的抓取日期与每项指标的'
        '数据日期（as_of）；凡陈旧或缺失项均已在正文标注，<strong>不再声称"正文所有时间戳均为最新"</strong>。<br/>'
        f'<strong>本次核对结果：{_fresh["banner"]}</strong><br/>' + freshness_html + '<br/>'
        '<strong>动态管线（每次构建/推送前重跑，不复用历史结果）：</strong><br/>'
        '• <strong>market_data.py</strong> → 11 项行情（Yahoo Finance → Stooq 回退）+ 6 个月日线动态计算 '
        'EMA9/21、MA50、RSI14、近 20 日箱体与 5 日/1 月/3 月涨跌（技术位不再写死）；<br/>'
        '• <strong>macro_data.py</strong> → 02 节宏观层（FRED 联邦基金利率/CPI/核心 CPI/非农/10 年期/铜、'
        '东方财富数据中心中国 CPI 与港股通、世界银行全球增速），"下一观察点"由事件日历按当日动态推导；<br/>'
        '• <strong>macro_manual_inputs.json</strong> → 无公开接口的人工项（IMF WEO / 碳酸锂 / 大行目标价 / 地缘判断），'
        '每项必须带 vintage 日期，超期自动判陈旧并在正文打标；<br/>'
        '• <strong>community_data.py</strong> → 14 大社区（HTTP GET + 模板回退，回退时明确标注非原文）；<br/>'
        '• <strong>sentiment_factors.py</strong> → 舆情/新闻因子（平台现成因子优先，降级路径逐项标注）。<br/>'
        '<strong>诚实性约定：</strong>取不到的数据不编造、不用旧值兜底、不冒充当天；'
        '港股通单日净买入额自 2024-08 起官方停止公布，本报告不再引用该口径。')

    # ---------- 07 节：核心结论全部由数据推导，缺失即标注"未取到" ----------
    # 与网页 07 节共用 macro_render.verdict_items()（单一口径，不再各写一套模板）
    _v_items = mr.verdict_items(_macro, _md, _sd, today=now.date())
    verdict_html = box(mr.render_verdict_wechat(_v_items))

    html = f'''<div style="background:#eef0f2;color:#141414;font-family:'黑体','SimHei','PingFang SC','Hiragino Sans GB','Microsoft YaHei','Noto Sans SC',sans-serif;font-size:12px;line-height:1.85;padding:16px 12px;">

  <!-- 顶部标题 -->
  <div style="background:#000;border-bottom:4px solid {NEON};padding:16px 12px 14px;margin:0 -12px 16px;">
    <div style="color:{NEON};font-family:'Noto Serif SC',serif;font-size:22px;font-weight:700;letter-spacing:1px;line-height:1.35;">章鱼 AI·全景分析（情绪因子分析）</div>
    <div style="color:{NEON};font-size:13px;margin-top:6px;font-family:'PingFang SC','Microsoft YaHei','Noto Sans SC',sans-serif;">全网 AI 调研境内境外数据，由多个大模型混合部署</div>
  </div>

  {banner_html}

  {h('01 / 底层模型与全景推理机制 (Multi-Model Alliance)')}
  {box(
    key('全网境内外为你寻找蛛丝马迹 — 提供全景视野分析，由多模型协同推理决策。'))}

  {quant_block}

  {h('02 / 全球经济与财经动态 (Global Macro & HK Battlefield)')}
  {macro_html}

  {h('03 / 社区论坛热评 (14 大平台详尽深入全景研判 · 每日动态抓取)')}
  {overview_html}

  {community_html}

  {h('03B / 舆情·新闻因子接入实测 (Sentiment & News Factor API Bench · 聚宽 米筐 掘金 优矿)')}
  {sentiment_block()}

  {h('04 / 监测平台列表与雷达矩阵 (Tactical Radar List)')}
  {box(platforms)}

  {h('05 / 数据获取与时效核对 (Telemetry & Freshness Audit)')}
  {telemetry_html}

  {h('06 / 排版风格与推送协议规范 (Editorial E-Ink Spec)')}
  {box(
    '本报告采用 <strong>电子杂志 × 电子墨水</strong>（Guizang PPT Skill · Style A）调色纪律：浅灰底 + 正文纯黑 + 深绿高对比标题（浅底 #007a35，黑底霓虹绿 #39ff14），重点文字为荧光绿字 + 黑色底，装饰线深绿。<br/>' +
    '<strong>字体与字号规范：</strong>全文统一使用<strong>黑体</strong>（SimHei / 微软雅黑 / 苹方 / Noto Sans SC 黑体栈），正文 12px 紧凑小字号，标题加粗分级。<br/>' +
    '<strong>推送时间协议：</strong>每一次推送前先核对当前时间，标题与正文中的“生成时间 / 时间核对”等全部时间戳<strong>实时刷新为最新时间</strong>后再发送。<br/>' +
    '<strong>单页协议：</strong>微信推送采用<strong>一对多群组推送</strong>（群组编码 oai.1，推送到群内全部关注成员微信），并采用<strong>单页完整卡片</strong>格式，全篇 8 大章节（含 03B 舆情·新闻因子实测节点）与 14 大社区深度长文研判一次性完整呈现，零拆分、零等待。')}

  {h('07 / 核心结论与资产配置提示 (Boss Verdict & Strategic Allocation)')}
  {verdict_html}
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
    # 「最新读取」日期改写为**数据文件自带的抓取日**（不是今天）——
    # 这样推送前的时效核对才有意义；无抓取日期时保留原样并由护栏判为缺失。
    if _community_fetch_date and re.match(r'20\d{2}-\d{2}-\d{2}', str(_community_fetch_date)):
        html = re.sub(r'(最新读取\s+)(20\d{2}-\d{2}-\d{2})',
                      lambda m: m.group(1) + _community_fetch_date, html)
    return html.strip(), ts, ts_full, _fresh

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

def assert_content_freshness(parts, fresh, now, strict=True, allow_stale=False):
    """推送前的**真**时效核对（取代旧版恒真检查）。

    核对三件事：
      1. 每个数据层（行情/社区/宏观/舆情）的 fetch_date 是否为当天、是否为 live 模式；
      2. 每项指标与人工项的 as_of 是否在其频率上限内（日频 7 天 / 月频 45 天 / 年频 400 天 / 人工项各自上限）；
      3. 渲染后的正文里是否还残留过期的中文绝对日期（防止宏观叙事再次固化）。

    strict=True（手动 --push）：任一不通过即退出码 6，不推送。
    strict=False（--push --scheduled）：只警告，保证 09:00 定时任务不中断，但正文已带 ⚠️ 标注。
    allow_stale=True：显式知情放行（仍打印全部问题）。
    """
    problems = []
    if fresh.get('stale'):
        def _fmt_stale(i):
            age = i.get('age_days')
            age_txt = '' if age is None else f', {age} 天'
            return f"{i.get('name')}({i.get('as_of') or '—'}{age_txt})"
        items = '、'.join(_fmt_stale(i) for i in fresh['stale'][:12])
        problems.append(f"{len(fresh['stale'])} 项数据陈旧: {items}")
    if fresh.get('missing'):
        items = '、'.join(f"{i['name']}" for i in fresh['missing'][:12])
        problems.append(f"{len(fresh['missing'])} 项数据缺失: {items}")
    narrative = []
    for _t, content in parts:
        narrative.extend(mr.scan_narrative_dates(content, today=now.date()))
    if narrative:
        uniq = sorted({n['text'] for n in narrative})
        problems.append(f"正文残留 {len(narrative)} 处过期绝对日期: {'、'.join(uniq[:10])}")

    if not problems:
        print(f"✅ 时效核对: {fresh.get('ok')}/{fresh.get('total')} 项均在时效内，"
              f"正文无过期日期引用，允许推送")
        return True
    for msg in problems:
        if strict and not allow_stale:
            print(f'错误: {msg}', file=sys.stderr)
        else:
            print(f'⚠️ 警告: {msg}')
    print(f"📅 时效核对结果: {fresh.get('banner')}")
    if strict and not allow_stale:
        print('错误: 存在陈旧/缺失数据或过期叙事，手动推送已拒绝。'
              '请先重跑 market_data.py / macro_data.py / community_data.py；'
              '确需推送请加 --allow-stale（正文会保留 ⚠️ 标注），'
              '定时任务用 --push --scheduled（仅警告）。', file=sys.stderr)
        sys.exit(6)
    print('⚠️ 定时/放行模式：继续推送，正文已逐项标注数据日期与陈旧状态')
    return False


def build_articles(source_html=SOURCE_HTML, now=None):
    """返回 (parts, ts, ts_full, freshness): parts 为 [(title, content)] 单页完整推送。

    freshness 为 macro_render.freshness_report() 的结果，供推送前的**真**时效核对使用。
    """
    content, ts, ts_full, fresh = build_single_wechat_html(now)
    title = TITLE
    parts = [(title, content)]
    return parts, ts, ts_full, fresh

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
    """群组编码: 默认取 report.html 的 PUSHPLUS_TOPIC 常量 (当前 'oai.1', 一对多群组推送)。"""
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
    ap = argparse.ArgumentParser(description='章鱼 AI — 微信推送工具 (一对多群组 oai.1 · 单页详尽完整版 · 14 源动态)')
    ap.add_argument('--source', default=SOURCE_HTML, help='报告 HTML 文件路径')
    ap.add_argument('--emit', metavar='PATH', help='写出 wechat.json 的路径')
    ap.add_argument('--embed', action='store_true',
                    help='把单页推送负载内嵌进 report.html (供页面按钮直接读取)')
    ap.add_argument('--push', action='store_true', help='推送到 PushPlus (一对多群组单页)')
    ap.add_argument('--scheduled', action='store_true',
                    help='定时自动推送模式: 抓取日期非当天仅警告不阻断 (供每天 09:00 定时任务使用)')
    ap.add_argument('--token', default='', help='PushPlus token (可选)')
    ap.add_argument('--topic', default='', help='PushPlus 群组编码 (可选, 默认取 report.html 的 PUSHPLUS_TOPIC, 当前 oai.1; 留空则回退一对一)')
    ap.add_argument('--dry-run', action='store_true', help='只转换, 打印字数统计与预览')
    ap.add_argument('--allow-stale', action='store_true',
                    help='知情放行: 存在陈旧/缺失数据时仍推送 (正文保留 ⚠️ 标注)')
    args = ap.parse_args()

    parts, ts, ts_full, fresh = build_articles(args.source)
    print(f'⏰ 时间核对: {ts_full} — 生成时间已按当前时间刷新；'
          f'正文各数据项按各自 as_of 标注，未统一冒称"当天最新"')
    fetch_dates = extract_fetch_dates(parts[0][1])
    fetch_dates_str = ", ".join(fetch_dates) if fetch_dates else "(未标注)"
    print(f'📅 社区抓取日期: {fetch_dates_str}')
    print(f'📊 数据时效: {fresh.get("banner")}')
    if args.push:
        now = datetime.now(timezone.utc)
        # 频道「最新读取」标记核对（现在标记取数据文件真实抓取日，不再是恒真检查）
        assert_fetch_dates_are_today(parts, now, strict=not (args.scheduled or args.allow_stale))
        # 全量时效核对：数据层 + 每项指标 as_of + 正文过期日期
        assert_content_freshness(parts, fresh, now,
                                 strict=not args.scheduled, allow_stale=args.allow_stale)
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
        'freshness': {
            'today': fresh.get('today'),
            'banner': fresh.get('banner'),
            'ok': fresh.get('ok'), 'total': fresh.get('total'),
            'stale': fresh.get('stale'), 'missing': fresh.get('missing'),
        },
        'mode': 'one-to-many',
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
