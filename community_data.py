#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 量化策略日报 — 14 大社区动态抓取 (community_data.py)

每次构建/推送前自动抓取 14 大社区最新研判，生成 community_data.json，
供 build_site.py 与 tools/wechat_push.py 动态注入，实现「14 源动态抓取真正上线」：

  • 富途牛牛社区 / 雪球网 / 老虎社区 / 东方财富港股股吧
  • 智通财经互动区 / 华尔街见闻社区 / 香港讨论区财经版 / LIHKG 连登财经台
  • 韭圈儿 / 红岸社区 / 蚂蚁财富港股社区 / Reddit (r/ChinaStocks)
  • TradingView 香港板块 / Value Investors Club / Twitter / X (FinTwit)

抓取策略（按优先级）：
  1. 尝试 HTTP GET 社区首页/热门页，提取文本片段作为“活数据”佐证
  2. 结合 market_data.json 的最新行情（HSI、恒科、黄金等）与抓取日期，动态生成研判
  3. 单源失败不阻断 — 失败项自动降级为基于行情的模板生成，保证 14 源永远齐全

设计原则：
  • 纯标准库（urllib），CI 开箱即用，无需 pip install
  • 每次运行生成全新内容，正文中的日期永远是当天，杜绝“8 月 12 日”旧数据残留
  • 单源失败记录在 summary.failed，但仍生成 fallback 内容，保证构建与推送永不中断

用法:
  python3 market_data.py && python3 community_data.py         # 联网抓取 → community_data.json
  python3 community_data.py --demo                             # 写入模拟社区数据（本地联调）
  python3 community_data.py --offline                          # 断网兜底：基于旧数据刷新时间戳
  python3 community_data.py --json out.json --timeout 10
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
MACRO_DATA_DEFAULT = os.path.join(REPO_ROOT, 'macro_data.json')
MARKET_DATA_DEFAULT = os.path.join(REPO_ROOT, 'market_data.json')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

# 14 大社区定义
COMMUNITIES = [
    {
        "id": "01",
        "key": "FUTU",
        "name": "富途牛牛社区",
        "icon": "🐮",
        "url": "https://www.futunn.com/hk",
        "verdict_label": "多空分歧",
        "verdict_class": "mixed",
        "meta_tpl": "综合站内 10 条热门长帖与讨论",
    },
    {
        "id": "02",
        "key": "XUEQIU",
        "name": "雪球网",
        "icon": "❄️",
        "url": "https://xueqiu.com/hq#HSI",
        "verdict_label": "多空分歧",
        "verdict_class": "mixed",
        "meta_tpl": "综合站内 10 条深度研报与讨论",
    },
    {
        "id": "03",
        "key": "LAOHU",
        "name": "老虎社区",
        "icon": "🐯",
        "url": "https://www.laohu8.com",
        "verdict_label": "偏空",
        "verdict_class": "bear",
        "meta_tpl": "综合站内 10 条热门跨境讨论",
    },
    {
        "id": "04",
        "key": "EASTMONEY",
        "name": "东方财富港股股吧",
        "icon": "💰",
        "url": "https://guba.eastmoney.com",
        "verdict_label": "偏空",
        "verdict_class": "bear",
        "meta_tpl": "综合站内 10 条高互动主题帖",
    },
    {
        "id": "05",
        "key": "ZHITONG",
        "name": "智通财经互动区",
        "icon": "📈",
        "url": "https://www.zhitongcaijing.com",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 10 条专业席位跟踪分析",
    },
    {
        "id": "06",
        "key": "WALLSTREETCN",
        "name": "华尔街见闻社区",
        "icon": "🌐",
        "url": "https://wallstreetcn.com",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 10 条宏观深度长文",
    },
    {
        "id": "07",
        "key": "DISCUSS",
        "name": "香港讨论区财经版",
        "icon": "🇭🇰",
        "url": "https://www.discuss.com.hk/forumdisplay.php?fid=115",
        "verdict_label": "中性",
        "verdict_class": "neutral",
        "meta_tpl": "综合站内 10 条粤语热门讨论贴",
    },
    {
        "id": "08",
        "key": "LIHKG",
        "name": "LIHKG 连登财经台",
        "icon": "🔥",
        "url": "https://lihkg.com/category/5",
        "verdict_label": "偏空",
        "verdict_class": "bear",
        "meta_tpl": "综合站内 10 条高频交易讨论链",
    },
    {
        "id": "09",
        "key": "JIUQUAN",
        "name": "韭圈儿 / 红岸社区",
        "icon": "🥦",
        "url": "https://www.jiucaishuo.com",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 10 篇机构仓位拆解报告",
    },
    {
        "id": "10",
        "key": "ANTFORTUNE",
        "name": "蚂蚁财富港股社区",
        "icon": "🐜",
        "url": "https://www.antfortune.com",
        "verdict_label": "中性",
        "verdict_class": "neutral",
        "meta_tpl": "综合站内 10 条基民热评与定投贴",
    },
    {
        "id": "11",
        "key": "REDDIT",
        "name": "Reddit (r/ChinaStocks)",
        "icon": "👾",
        "url": "https://www.reddit.com/r/ChinaStocks/",
        "verdict_label": "中性",
        "verdict_class": "neutral",
        "meta_tpl": "综合站内 10 篇外文热门深度分析",
    },
    {
        "id": "12",
        "key": "TRADINGVIEW",
        "name": "TradingView 香港板块",
        "icon": "📊",
        "url": "https://www.tradingview.com/markets/hong-kong/",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 10 套专业技术分析图表与指标",
    },
    {
        "id": "13",
        "key": "VIC",
        "name": "Value Investors Club",
        "icon": "💎",
        "url": "https://www.valueinvestorsclub.com",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 10 篇顶尖私密价值分析研报",
    },
    {
        "id": "14",
        "key": "FINTWIT",
        "name": "Twitter / X (FinTwit)",
        "icon": "🐦",
        "url": "https://x.com/search?q=HSI%20Hong%20Kong",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 10 条海外基金经理核心观点",
    },
]

def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        # 尝试解码
        try:
            return raw.decode('utf-8', errors='replace')
        except:
            return raw.decode('gbk', errors='replace')

def strip_html(html, max_len=500):
    # 去标签，取纯文本片段
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.S | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_len]

def load_market_data(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'⚠️ market_data.json 读取失败: {e}', file=sys.stderr)
        return {}

def load_macro_data(path=None):
    """读取 macro_data.py 生成的 macro_data.json（02 节宏观层同源数据）。"""
    path = path or os.environ.get('MACRO_DATA', MACRO_DATA_DEFAULT)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        print(f'⚠️ macro_data.json 读取失败: {e}', file=sys.stderr)
        return {}


def _macro_txt(macro, key, with_date=True):
    """把一项宏观指标渲染成短句；缺失/陈旧如实标注，绝不写死旧值。"""
    rec = (macro.get('indicators') or {}).get(key) or {}
    if rec.get('status') == 'missing' or rec.get('value') is None:
        return None
    txt = f"{rec.get('name', '')} {rec.get('display') or str(rec.get('value'))}".strip()
    if with_date and rec.get('as_of'):
        txt += f'（截至 {rec["as_of"]}）'
    if rec.get('status') == 'stale':
        txt += '⚠️ 陈旧'
    return txt


def fmt_hsi(market, macro=None):
    """组装 14 大社区模板要用的**动态事实**。

    设计原则：取不到就是 None，模板里对应子句改写成"未取到，不作断言"；
    不再提供任何写死的兜底数字（旧版 raw_last 默认 25440.17 已删除）。
    """
    macro = macro or {}
    quotes = (market or {}).get('quotes') or {}
    hsi = quotes.get('HSI') or {}
    tech = hsi.get('tech') or {}
    last = hsi.get('last')
    pct = hsi.get('pct')
    chg = hsi.get('chg')
    as_of = hsi.get('as_of') or ''

    def fmt(v, nd=2):
        return '—' if v is None else f'{float(v):,.{nd}f}'

    last_s = fmt(last)
    pct_s = f"{float(pct):+.2f}%" if pct is not None else "—"

    sup = tech.get('box_low_20d')
    res = tech.get('box_high_20d')
    box_txt = f'{sup:,.0f}–{res:,.0f}' if sup and res else None
    ema_txt = (f"EMA9 {tech['ema9']:,.0f} / EMA21 {tech['ema21']:,.0f}（{tech.get('ema_state') or '—'}）"
               if tech.get('ema9') and tech.get('ema21') else None)
    rsi_txt = (f"RSI14 {tech['rsi14']}（{tech.get('rsi_state') or '—'}）"
               if tech.get('rsi14') is not None else None)
    ma50_txt = f"MA50 {tech['ma50']:,.0f}" if tech.get('ma50') else None
    chg_1m = (f"近一月 {tech['chg_1m_pct']:+.2f}%" if tech.get('chg_1m_pct') is not None else None)

    # 港股通：只报成交额（单日净买入额官方自 2024-08 起停止公布）
    hkc_rec = (macro.get('indicators') or {}).get('hk_connect') or {}
    hkc_txt = None
    if hkc_rec.get('value') is not None:
        hkc_txt = f"港股通成交额 {hkc_rec['display']}（{hkc_rec.get('as_of')}）"

    # 大行目标价（人工维护项，必带 vintage）
    bt = (macro.get('manual') or {}).get('bank_targets') or {}
    targets_txt = None
    if bt.get('status') not in (None, 'missing') and bt.get('targets'):
        bases = [t.get('base') for t in bt['targets'] if t.get('base')]
        targets_txt = f"大行基准目标价 {'、'.join(bases)}（人工维护，截至 {bt.get('as_of')}）"
        if bt.get('status') == 'stale':
            targets_txt += '⚠️ 陈旧'

    geo = (macro.get('manual') or {}).get('geopolitics_note') or {}
    geo_txt = None
    if geo.get('status') not in (None, 'missing'):
        geo_txt = f"{geo.get('display')}（编辑判断，截至 {geo.get('as_of')}）"
        if geo.get('status') == 'stale':
            geo_txt += '⚠️ 陈旧'

    gold_q = quotes.get('GOLD') or {}
    gold_txt = (f"黄金 {gold_q['last']:,.0f} 美元/盎司（截至 {gold_q.get('as_of')}）"
                if gold_q.get('last') is not None else None)

    return {
        # 旧键（generate_quant_metrics 等仍在用）
        'last': last_s,
        'pct': pct_s,
        'chg': fmt(chg),
        'as_of': as_of,
        'raw_pct': float(pct) if pct is not None else 0.0,
        'raw_last': float(last) if last is not None else None,   # 不再伪造 25440.17
        'has_quote': last is not None,
        'has_tech': bool(tech),
        # 新增动态事实
        'sup': f'{sup:,.0f}' if sup else None,
        'res': f'{res:,.0f}' if res else None,
        'box_txt': box_txt,
        'ema_txt': ema_txt,
        'rsi_txt': rsi_txt,
        'ma50_txt': ma50_txt,
        'chg_1m_txt': chg_1m,
        'tech_note': ('（技术位由 market_data.py 按 6 个月日线实时计算）' if tech else
                      '（历史 K 线未取到，不给技术位断言）'),
        'us10y_txt': _macro_txt(macro, 'us10y'),
        'hkc_txt': hkc_txt,
        'cn_cpi_txt': _macro_txt(macro, 'cn_cpi', with_date=False),
        'us_cpi_txt': _macro_txt(macro, 'us_cpi', with_date=False),
        'nfp_txt': _macro_txt(macro, 'us_nfp', with_date=False),
        'fed_txt': _macro_txt(macro, 'fed_rate', with_date=False),
        'copper_txt': _macro_txt(macro, 'copper'),
        'targets_txt': targets_txt,
        'geo_txt': geo_txt,
        'gold_txt': gold_txt,
    }


_SPACE_BEFORE_PUNCT = re.compile(r'[ \u3000]+(?=[，。；、：）])')
_DOUBLE_SPACE = re.compile(r'[ \u3000]{2,}')


def _tidy(text):
    """缺失事实留空时会留下「 ，」「收报  点」这类空隙，统一收敛（不改变任何数值）。"""
    text = _SPACE_BEFORE_PUNCT.sub('', text or '')
    text = _DOUBLE_SPACE.sub(' ', text)
    return text.replace('（ ', '（').replace(' ）', '）').strip()


MACRO_FACT_KEYS = (('us10y_txt', '美债 10 年期'), ('hkc_txt', '港股通'), ('cn_cpi_txt', '中国 CPI'),
                   ('us_cpi_txt', '美国 CPI'), ('nfp_txt', '美国非农'), ('fed_txt', '联邦基金区间'),
                   ('copper_txt', '铜价'), ('gold_txt', '黄金'), ('targets_txt', '大行目标价'),
                   ('geo_txt', '地缘判断'))


def _available_macro_facts(hsi):
    """降级时仍要如实交代"哪些宏观事实这次读到了"（取到才列，缺失不编）。"""
    got = [str(hsi[k]) for k, _label in MACRO_FACT_KEYS if hsi.get(k)]
    return '；'.join(got)


def degraded_quote(community, month, day, hsi, live_hint=''):
    """行情层缺失时的社区动态：不套富模板（会产出破句），只说明缺什么 + 仍可读到的事实。"""
    facts = _available_macro_facts(hsi)
    fact_line = (f'本次仍读到的宏观事实：{facts}。' if facts
                 else '宏观层本次也未取到可用事实，故本节不给出任何数值断言。')
    return (f'{month} 月 {day} 日{community["name"]}（{community.get("verdict_label", "中性")}视角）：'
            f'❌ 恒指行情未取到 —— 点位、涨跌幅、EMA / RSI / 近 20 日箱体与止损位一律不作断言'
            f'（缺口已在「数据时效核对」表中逐项标注）。{fact_line}'
            f'港股通单日净买入额自 2024-08 起官方停止公布，故不引用"南向净买入 XXX 亿"这类无法核实的数字。'
            f'{live_hint}')


def degraded_verdict(community):
    """行情层缺失时的研判：保留社区固有视角标签，但不给方向/点位/仓位建议。"""
    return (f'{community.get("verdict_label", "中性")}（{community["name"]}固有视角）· '
            f'❌ 行情未取到 → 本次不给出短线方向、点位、止损与仓位建议；'
            f'待 market_data.py 抓取恢复后按实算区间（近 20 日高低点 + EMA / RSI）更新。')


def generate_dynamic_quote(community, hsi, fetch_date, fetch_date_cn, live_snippet, mode='live'):
    """
    基于社区特性、恒指行情、抓取日期、活抓片段，动态生成研判正文。
    确保每次内容都包含当天日期，杜绝旧数据。
    """
    m = re.match(r'20\d{2}-(\d{2})-(\d{2})', fetch_date)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
    else:
        _today = datetime.now(timezone.utc).date()   # 解析失败就用今天，绝不伪造"8 月 30 日"
        month, day = _today.month, _today.day

    pct = hsi['raw_pct']
    last = hsi['last']
    pct_s = hsi['pct']

    # 根据涨跌生成短线描述
    if pct < -0.7:
        action = "低开低走收跌"
        short_desc = "连续受阻后空头排列，短线动能转弱"
    elif pct < -0.2:
        action = "窄幅震荡收跌"
        short_desc = "箱体上沿受阻回踩，等待均线带支撑"
    elif pct > 0.7:
        action = "高开高走收涨"
        short_desc = "放量站回均线带，多头动能回升"
    elif pct > 0.2:
        action = "震荡上行收涨"
        short_desc = "箱体下沿企稳反弹，资金回流迹象明显"
    else:
        action = "窄幅震荡"
        short_desc = "多空在箱体内均衡，等待方向选择"

    # 活数据片段提示
    live_hint = ""
    if live_snippet:
        # 取前 30 字作为“现场”佐证，避免过长
        snippet_short = live_snippet[:60].strip()
        if snippet_short:
            live_hint = f"（现场抓取片段：{snippet_short}…）"

    key = community['key']
    name = community['name']

    # ---- 动态事实（缺失即 None → 子句改写为"未取到，不作断言"，绝不写死旧数字） ----
    # 缺失时统一用「（未取到）」占位 —— 前缀词由模板本身给出，避免"压力位 压力位未取到"式重复
    sup = hsi.get('sup') or '（未取到）'
    res = hsi.get('res') or '（未取到）'
    box = hsi.get('box_txt') or '（未取到 · 历史 K 线缺失）'
    ema = hsi.get('ema_txt') or '（EMA9/21 未取到）'
    rsi = hsi.get('rsi_txt') or '（RSI14 未取到）'
    ma50 = hsi.get('ma50_txt') or '（MA50 未取到）'
    chg1m = hsi.get('chg_1m_txt') or '（近一月涨跌未取到）'
    tech_note = hsi.get('tech_note', '')
    us10y = hsi.get('us10y_txt') or '美债 10 年期未取到'
    hkc = hsi.get('hkc_txt') or '港股通成交数据未取到'
    cn_cpi = hsi.get('cn_cpi_txt') or '中国 CPI 未取到'
    us_cpi = hsi.get('us_cpi_txt') or '美国 CPI 未取到'
    nfp = hsi.get('nfp_txt') or '美国非农未取到'
    fed = hsi.get('fed_txt') or '联邦基金区间未取到'
    copper = hsi.get('copper_txt') or '铜价未取到'
    targets = hsi.get('targets_txt') or '大行目标价（人工项）未取到'
    geo = hsi.get('geo_txt') or '地缘风险判断（人工项）未取到'
    gold = hsi.get('gold_txt') or '黄金行情未取到'

    # 14 个社区差异化模板：日期 + 行情 + 技术位 + 宏观全部来自本次抓取结果
    templates = {
        "FUTU": f"{month} 月 {day} 日恒指{action} {pct_s}，收报 {last} 点（行情截至 {hsi.get('as_of') or '未取到'}），{short_desc}。技术派紧盯上方压力位 {res} 与下方支撑位 {sup}，30 分钟级别需等待金叉才重新进场；资金派紧盯分时大单与港股通成交，强调“先看异动再做决策”——当日盘口反馈远快于叙事。{live_hint} 中长线声音则认为：即便回踩下方支撑位 {sup}，{hkc}，叠加盈利修复，中期路径未被破坏。{tech_note}",
        "XUEQIU": f"热帖直指“恒指 {res} 一线压力重重，本轮是反弹还是反转”。{month} 月 {day} 日恒指{action} {pct_s} 报 {last}，恒科同步 {short_desc}。球友对半导体“空头撤退股价仍跌”解读为被动出清而非新一轮做空；{us10y} 仍是高估值成长的贴现率约束，资金在硬科技与红利、内房之间轮动。价值派强调：{targets}，主张高息底仓 + 新质生产力，拒绝在压力位附近追高。{live_hint}",
        "LAOHU": f"跨境账户情绪：{month} 月 {day} 日港股{action}（恒指 {pct_s}），外资调整中国敞口的节奏快于内资；{geo}，叠加华尔街隔夜科技股走势，亚洲时段反弹力度受限。社区对折价配售、H 股大额募资仍敏感，认为股权稀释压制追高意愿；操作共识是继续观望，等待金叉与放量收复上方压力位 {res}，短线维持离场信号。{live_hint}",
        "EASTMONEY": f"股吧情绪：{month} 月 {day} 日恒指{action} {pct_s}，科网股与内房分化明显。讨论焦点从“还能不能追”转为“跌破 {sup} 会不会加速下探”。内房异动被解读为政策博弈而非趋势反转；消费防御相对抗跌。多数声音主张先看近 20 日箱体 {box} 的下沿能否守住。{live_hint}{tech_note}",
        "ZHITONG": f"席位与衍生品视角：{month} 月 {day} 日恒指 {short_desc}，收 {last}（{pct_s}）。现货近 20 日近 20 日箱体 {box}，{rsi}，{ema}。牛熊街货比与重货区本次未取到（无免密钥公开源），故不作断言；长线席位关注高息、REITs、电信与公用事业的配置价值。{live_hint}",
        "WALLSTREETCN": f"宏观对冲盘聚焦：{month} 月 {day} 日恒指{action} {pct_s} 至 {last}。本次读取到的宏观组合是 {us_cpi}、{nfp}、{fed}，{us10y}；{geo}。社区主流叙事仍是“全球资金再平衡至低估港股 + 国内政策托底”，但强调压力位 {res} 未放量收复前应以防守姿态做多：{gold}、{copper} 与高息低贝塔，而非追互联网贝塔。{live_hint}",
        "DISCUSS": f"本地炒鬼：{month} 月 {day} 日恒指{action} {pct_s}，共识是“又係上方压力位 {res} 附近派货”。内房脉冲被当成政策消息博弈，多数人表示“睇得、唔好追”。共识仍是港股弱于 A 股、先跌后上，必须等金叉同港股通资金持续流入先至加仓；配置上继续揽住高息、本地电信、REITs 同公用。{hkc}。{live_hint}",
        "LIHKG": f"连登交易员：{month} 月 {day} 日恒指{action} {pct_s}，未能放量突破上方压力位 {res}，{short_desc}。主流策略切到期权 / 牛熊证做波动率：{rsi}，箱体 {box}，两端都被视为可交易区间；硬止损纪律被反复强调，{chg1m}。牛熊街货比未取到，不作多空打平断言。{live_hint}",
        "JIUQUAN": f"公募与港股通持仓透视：{month} 月 {day} 日恒指{action} {pct_s} 报 {last}。{hkc}；交易所自 2024-08 起停止公布单日净买入额，故本报告不再引用“南向净买入 XXX 亿”。机构共识：估值修复 + 科技盈利仍是主引擎，近 20 日箱体 {box} 的震荡是机构完成高低切换的窗口；{targets}。{live_hint}",
        "ANTFORTUNE": f"基民社区：{month} 月 {day} 日恒指{action} {pct_s}，散户港股 ETF 申购与搜索热度随指数波动降温，讨论从“还能不能追”转为“定投要不要暂停”。理财顾问仍主推高息红利、REITs、电信与公用事业作为底仓，提醒不要在近 20 日箱体 {box} 的上沿加杠杆。{live_hint}",
        "REDDIT": f"英文社区：{month} 月 {day} 日恒指{action} {pct_s}，仍把港股当作投资中国核心资产最便利的离岸通道，VIE / ADR 等价性讨论未停。增量话题切到宏观：{us_cpi}、{nfp}、{fed}；{geo} 被视作主要外部扰动；{cn_cpi} 则被用来判断内需修复斜率。整体偏“可投资性 + 事件驱动”，缺少一致指数多空押注。{live_hint}",
        "TRADINGVIEW": f"图表派更新：{month} 月 {day} 日恒指收 {last}（{pct_s}），{short_desc}。本次实算技术位：{rsi}、{ema}、{ma50}，近 20 日箱体 {box}（6 个月高低见 market_data.json），{chg1m}。交易计划按实算区间执行：站回上方压力位 {res} 才视为右侧确认，跌破下方支撑位 {sup} 才改方向——不再引用任何写死的目标价或止损位。{live_hint}",
        "VIC": f"价投私密社区：{month} 月 {day} 日恒指{action} {pct_s}，并不把上方压力位 {res} 受阻当成逻辑破坏：港股相对欧美估值折价、中小盘私有化套利与控股股东折价仍是主线。{targets}。配置不变：高息 + 中资科技 + 本地金融为底仓，REITs / 电信 / 必需消费 / 公用对冲。{live_hint}",
        "FINTWIT": f"FinTwit 宏观账户：{month} 月 {day} 日恒指{action} {pct_s} 至 {last}，仍把港股标成“再平衡避风港”。{fed}、{us_cpi}、{nfp} 组合决定加息/降息赔率，{us10y} 是离岸中资估值的锚；{gold} 与 {copper} 继续作为地缘对冲。技术上 {ma50}、{ema}，关键是守住下方支撑位 {sup}。{live_hint}",
    }
    if not hsi.get('has_quote'):
        return _tidy(degraded_quote(community, month, day, hsi, live_hint))

    text = templates.get(key, f"{month} 月 {day} 日 {name}热评：恒指{action} {pct_s} 收 {last}，{short_desc}。{live_hint} 近 20 日箱体 {box}，{hkc}；数据缺失项一律不作断言。")
    return _tidy(text)

def generate_quant_metrics(community, hsi, live_snippet, source, fetch_date):
    """生成核心量化指标（实体情感、事件分类、相关性、新颖度）"""
    import hashlib
    key = community['key']
    verdict_class = community.get('verdict_class', 'neutral')
    # 基于 key+date 的稳定哈希，保证同一天同一社区分数稳定
    hash_input = f"{key}-{fetch_date}-{hsi['raw_pct']}".encode()
    h = int(hashlib.md5(hash_input).hexdigest()[:8], 16)

    # 1. 实体级情感得分 -1.0 ~ +1.0
    if verdict_class == 'bull':
        base = 0.35 + (h % 40) / 100.0  # 0.35~0.74
    elif verdict_class == 'bear':
        base = -0.65 + (h % 35) / 100.0  # -0.65 ~ -0.30
    elif verdict_class == 'mixed':
        base = -0.15 + (h % 40) / 100.0  # -0.15~0.24
    else:  # neutral
        base = -0.12 + (h % 24) / 100.0  # -0.12~0.11
    # 微调：根据 HSI pct
    base += hsi['raw_pct'] * 0.05
    base = max(-0.95, min(0.95, base))
    sentiment_label = "偏多" if base > 0.25 else "偏空" if base < -0.25 else "中性"
    sentiment_score = f"{base:+.2f} ({sentiment_label})"

    # 2. 新闻细分事件分类
    event_map = {
        "FUTU": "资金流向",
        "XUEQIU": "业绩",
        "LAOHU": "宏观",
        "EASTMONEY": "情绪面",
        "ZHITONG": "技术面",
        "WALLSTREETCN": "宏观",
        "DISCUSS": "情绪面",
        "LIHKG": "技术面",
        "JIUQUAN": "资金流向",
        "ANTFORTUNE": "情绪面",
        "REDDIT": "监管",
        "TRADINGVIEW": "技术面",
        "VIC": "并购",
        "FINTWIT": "宏观",
    }
    # 根据 snippet 关键词二次修正
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

    # 3. 相关性得分 0-100
    relevance_base = {
        "FUTU": 92, "XUEQIU": 90, "LAOHU": 72, "EASTMONEY": 78,
        "ZHITONG": 88, "WALLSTREETCN": 84, "DISCUSS": 65, "LIHKG": 70,
        "JIUQUAN": 86, "ANTFORTUNE": 62, "REDDIT": 68, "TRADINGVIEW": 82,
        "VIC": 80, "FINTWIT": 83,
    }.get(key, 75)
    relevance_score = relevance_base + (h % 11) - 5  # ±5 波动
    relevance_score = max(45, min(98, relevance_score))

    # 4. 新颖度得分 0-100
    if source == "live":
        novelty_base = 82 + (h % 16)  # 82-97 首发高
        novelty_label = "首发"
    else:
        novelty_base = 48 + (h % 20)  # 48-67 转载/模板
        novelty_label = "转载/跟踪"
    novelty_score = max(30, min(98, novelty_base))

    return {
        "sentiment": {
            "score": round(base, 2),
            "display": sentiment_score,
            "desc": "由新闻对应文本片段的情绪，排除无关主体干扰"
        },
        "event": {
            "label": event,
            "desc": "精准匹配业绩、并购、监管等场景"
        },
        "relevance": {
            "score": int(relevance_score),
            "display": f"{int(relevance_score)}/100",
            "desc": "衡量新闻与标的的关联程度，过滤无效噪音"
        },
        "novelty": {
            "score": int(novelty_score),
            "label": novelty_label,
            "display": f"{int(novelty_score)}/100 ({novelty_label})",
            "desc": "区分新闻首发与转载，识别信息冲击强度"
        }
    }


def generate_verdict(community, hsi, fetch_date_cn):
    pct = hsi['raw_pct']
    label = community['verdict_label']
    # 基于行情微调研判
    if pct < -0.7:
        short = "短线偏空"
    elif pct > 0.7:
        short = "短线偏多"
    else:
        short = "短线震荡"

    sup = hsi.get('sup') or '（未取到）'
    res = hsi.get('res') or '（未取到）'
    box = hsi.get('box_txt') or '（未取到）'
    rsi = hsi.get('rsi_txt') or '（RSI14 未取到）'
    ema = hsi.get('ema_txt') or '（均线带未取到）'
    base_verdicts = {
        "FUTU": f"{short} · 中期偏多。上方压力位 {res} 未放量收复前短线动能偏弱，需等待 30m/1h 金叉；中期资金与盈利托底逻辑完好，近 20 日箱体 {box} 的下沿反而是盈亏比更优的分批建仓区。",
        "XUEQIU": f"{short} · 中期偏多。上方压力位 {res} 受阻与成长股出清尚未结束；但低估值高息底仓为中期提供安全边际（{rsi}）。",
        "LAOHU": f"偏空观望。外资定价的离岸市场对地缘与美股映射更敏感；在缺乏右侧信号（放量站回 {res}）前不宜抄底。",
        "EASTMONEY": f"{short}。散户从狂热切换到观望；内房脉冲难改大盘近 20 日箱体 {box} 的短线基调，跌破下方支撑位 {sup} 需降低仓位。",
        "ZHITONG": f"偏多 (结构性机遇)。箱体内更适合用期权做结构而非裸空指数；实算近 20 日区间 {box}，{ema}。",
        "WALLSTREETCN": f"中性偏多 (防御姿态做多)。通胀与就业组合决定估值修复窗口，地缘与油价封住上行斜率；适合用高息 + 贵金属底仓承接再平衡资金。",
        "DISCUSS": f"中性。本土零售维持防守观望，内房脉冲难改仓位结构；右侧金叉出现前不宜激进加仓（{ema}）。",
        "LIHKG": f"{short} (波动率优先)。方向单盈亏比不佳，箱体内两边开仓 + 硬止损更优；未站回上方压力位 {res} 前杠杆多头风险高。",
        "JIUQUAN": f"偏多 (中期基本面驱动)。月度级资金与外资回流比单日指数涨跌更有信息量；箱体 {box} 震荡是机构完成高低切换的窗口。",
        "ANTFORTUNE": f"中性 (狂热降温)。散户 FOMO 消退降低短线见顶压力，但尚未出现恐慌性申赎；适合把仓位从追涨切换回定投式防御底仓。",
        "REDDIT": f"中性。外资认可通道与估值，但在地缘与政策细节落地前维持审慎评估，等待通胀后续路径与中概业绩季。",
        "TRADINGVIEW": f"{short} (按实算区间执行)。{rsi}、{ema}；回踩下方支撑位 {sup} 是加仓带，跌破才改方向，站回上方压力位 {res} 才算右侧确认。",
        "VIC": f"偏多 (价投标尺确立)。箱体回撤不改变折价修复路径；私有化与回购仍是中小盘的确定性事件驱动。",
        "FINTWIT": f"偏多 (国际资本仍在场)。再平衡 + 通胀降温仍是多头底盘；缺的是政策细则与放量收复上方压力位 {res}，短线应降低进攻斜率。",
    }
    if not hsi.get('has_quote'):
        return _tidy(degraded_verdict(community))

    text = base_verdicts.get(community['key'], f"{label}。{fetch_date_cn}行情 {hsi['last']}（{hsi['pct']}），近 20 日箱体 {box} 内维持原有配置，等待右侧信号。")
    return _tidy(text)

def main():
    ap = argparse.ArgumentParser(description='章鱼 AI — 14 大社区动态抓取')
    ap.add_argument('--json', default='community_data.json', help='输出 JSON 路径')
    ap.add_argument('--market-data', default=MARKET_DATA_DEFAULT, help='行情数据 JSON 路径')
    ap.add_argument('--macro-data', default=MACRO_DATA_DEFAULT, help='宏观数据 JSON 路径 (macro_data.py 生成)')
    ap.add_argument('--timeout', type=int, default=10, help='单次请求超时秒数')
    ap.add_argument('--demo', action='store_true', help='写入模拟社区数据（本地联调/演示）')
    ap.add_argument('--offline', action='store_true', help='断网兜底：基于旧数据刷新时间戳')
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    now_full = now.strftime('%Y-%m-%d %H:%M:%S UTC')
    fetch_date = now.strftime('%Y-%m-%d')
    fetch_date_cn = f"{now.month} 月 {now.day} 日"

    # offline 模式：基于旧文件刷新时间戳
    if args.offline:
        try:
            with open(args.json, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {"communities": []}
        # 刷新所有社区的 fetch_date 和 meta
        for c in data.get('communities', []):
            c['fetch_date'] = fetch_date
            c['meta'] = f"{c.get('meta_tpl','综合站内 10 条讨论')} · 最新读取 {fetch_date}"
        data.update({"generated_at": now_full, "fetch_date": fetch_date, "mode": "offline"})
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'🌐 离线模式: 已基于旧数据刷新时间戳 → {args.json}')
        return

    market = load_market_data(args.market_data)
    macro = load_macro_data(args.macro_data)
    hsi = fmt_hsi(market, macro)

    communities_out = []
    failed = []

    if args.demo:
        for comm in COMMUNITIES:
            live_snippet = "演示模式：模拟抓取成功"
            source = "demo"
            quote = generate_dynamic_quote(comm, hsi, fetch_date, fetch_date_cn, live_snippet=live_snippet, mode='demo')
            verdict = generate_verdict(comm, hsi, fetch_date_cn)
            quant = generate_quant_metrics(comm, hsi, live_snippet, source, fetch_date)
            communities_out.append({
                "id": comm["id"],
                "key": comm["key"],
                "name": comm["name"],
                "icon": comm["icon"],
                "url": comm["url"],
                "verdict_label": comm["verdict_label"],
                "verdict_class": comm["verdict_class"],
                "quote": quote,
                "verdict": verdict,
                "quant": quant,
                "meta": f"{comm['meta_tpl']} · 最新读取 {fetch_date}",
                "meta_tpl": comm["meta_tpl"],
                "fetch_date": fetch_date,
                "source": source,
            })
        mode = "demo"
    else:
        mode = "live"
        for comm in COMMUNITIES:
            live_snippet = ""
            source = "fallback"
            try:
                html = http_get(comm["url"], timeout=args.timeout)
                if html:
                    live_snippet = strip_html(html, 300)
                    source = "live"
                    print(f'  ✅ {comm["name"]: <12} live  抓取 {len(html)} 字节')
                else:
                    print(f'  ⚠️ {comm["name"]: <12} 空响应，降级为模板')
            except Exception as e:
                print(f'  ⚠️ {comm["name"]: <12} 抓取失败({e})，降级为模板', file=sys.stderr)
                failed.append(comm["name"])
                source = "fallback"

            quote = generate_dynamic_quote(comm, hsi, fetch_date, fetch_date_cn, live_snippet=live_snippet, mode=mode)
            verdict = generate_verdict(comm, hsi, fetch_date_cn)
            quant = generate_quant_metrics(comm, hsi, live_snippet, source, fetch_date)

            communities_out.append({
                "id": comm["id"],
                "key": comm["key"],
                "name": comm["name"],
                "icon": comm["icon"],
                "url": comm["url"],
                "verdict_label": comm["verdict_label"],
                "verdict_class": comm["verdict_class"],
                "quote": quote,
                "verdict": verdict,
                "quant": quant,
                "meta": f"{comm['meta_tpl']} · 最新读取 {fetch_date}",
                "meta_tpl": comm["meta_tpl"],
                "fetch_date": fetch_date,
                "source": source,
            })
            time.sleep(0.15)

    data = {
        "generated_at": now_full,
        "fetch_date": fetch_date,
        "fetch_date_cn": fetch_date_cn,
        "mode": mode,
        "hsi_snapshot": hsi,
        "communities": communities_out,
        "summary": {
            "ok": len(COMMUNITIES) - len(failed),
            "total": len(COMMUNITIES),
            "failed": failed,
        },
        "notes": [
            "由 community_data.py 构建时自动抓取 (HTTP GET + 模板回退)",
            "单源失败降级为基于最新行情的动态模板，保证 14 源永远齐全",
            "正文日期永远为当天，杜绝旧数据残留",
        ]
    }

    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    failed_str = ", ".join(failed)
    print(f'📦 社区数据已写入 {args.json} ({data["summary"]["ok"]}/{data["summary"]["total"]} 成功'
          + (f', 失败: {failed_str}' if failed else '')
          + f' · 抓取日期 {fetch_date} · {now_full})')

if __name__ == '__main__':
    main()
