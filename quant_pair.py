#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 量化策略日报 — AI 量化 · 配对交易 (quant_pair.py)

挂在每一条内容后面：先按正文找到一条量化策略，再给出恰好两只标的的组合，
最后用当次涨跌幅按该策略的规则给出推荐。

策略家族只有「配对交易 / 相对收益均值回归」：
    价差 = 涨跌幅A − 涨跌幅B
    z    = 价差 / 残差波动
    残差波动 = sqrt(σA² + σB² − 2·ρ·σA·σB)
    |z| < 1     观望，不建配对仓
    z ≤ −1      做多 A、做空 B（A 相对偏弱，等待回归）
    z ≥ 1       做空 A、做多 B（A 相对偏强，等待回归）

σ 与 ρ 是策略参数（典型日波动、预设相关系数），不是某一天的行情事实。
两腿涨跌幅缺任何一条，就输出「数据不足」，不编方向、不回填历史点位。

纯标准库、纯函数、不联网。网页与微信共用本模块，避免两套口径漂移。

用法:
  python3 quant_pair.py --self-test
  python3 quant_pair.py --text "原油与布伦特价差走阔" --quotes market_data.json
"""
import argparse
import html
import json
import math
import os
import sys

MINUS = '\u2212'

# 策略参数：典型单日波动（百分点），不是写死的行情事实
DAILY_SIGMA = {
    'HSI': 1.20, 'HSTECH': 1.80, 'HSCE': 1.30,
    'SPX': 0.90, 'NDQ': 1.20, 'DJI': 0.80,
    'GOLD': 0.90, 'WTI': 1.80, 'BRENT': 1.60,
    'USDCNH': 0.25, 'USDCNY': 0.20,
}

NAMES = {
    'HSI': '恒生指数', 'HSTECH': '恒生科技指数', 'HSCE': '恒生中国企业指数',
    'SPX': '标普 500', 'NDQ': '纳斯达克', 'DJI': '道琼斯',
    'GOLD': '现货黄金', 'WTI': 'WTI 原油', 'BRENT': '布伦特原油',
    'USDCNH': '美元/离岸人民币', 'USDCNY': '美元/在岸人民币',
}

# 正文没有主题词时，用频道名落到默认配对；主题词命中仍可覆盖
NAME_TO_HINT = (
    ('富途', 'FUTU'), ('雪球', 'XUEQIU'), ('老虎', 'LAOHU'),
    ('东方财富', 'EASTMONEY'), ('智通', 'ZHITONG'), ('华尔街见闻', 'WALLSTREETCN'),
    ('香港讨论区', 'DISCUSS'), ('连登', 'LIHKG'), ('LIHKG', 'LIHKG'),
    ('韭圈', 'JIUQUAN'), ('蚂蚁财富', 'ANTFORTUNE'), ('Reddit', 'REDDIT'),
    ('TradingView', 'TRADINGVIEW'), ('Value Investors', 'VIC'),
    ('FinTwit', 'FINTWIT'), ('Twitter', 'FINTWIT'),
)

HINT_WEIGHT = 4
KEYWORD_WEIGHT = 6
Z_ENTRY = 1.0
Z_STRONG = 1.8

RULE = ('规则：价差 = 涨跌幅A − 涨跌幅B；z = 价差 / 残差波动'
        '（σ 为策略参数里的典型日波动，ρ 为预设相关系数）。'
        '|z|<1 观望，z≤−1 做多A做空B，z≥1 做空A做多B。不构成投资建议。')

# 每条策略恰好两只标的。hints 是栏目/频道/力量 key，keywords 从正文里找策略。
STRATEGIES = [
    {
        'id': 'hk_growth_value',
        'name': '港股成长/价值配对',
        'leg_a': 'HSTECH', 'leg_b': 'HSI', 'rho': 0.85,
        'hints': ['rotation', 'hk', 'HSTECH', 'FUTU', 'ZHITONG', 'TRADINGVIEW',
                  'sentiment', 'JIUQUAN'],
        'keywords': ['恒科', '恒生科技', '科网', '科技股', '成长', '轮动', '半导体',
                     '芯片', '光通信', '互联网', '腾讯', '阿里', '小米', '美团'],
        'logic': '恒生科技与恒指同属港股、长期同向。相对收益偏离残差后做均值回归。',
    },
    {
        'id': 'hk_structure',
        'name': '港股结构配对',
        'leg_a': 'HSI', 'leg_b': 'HSCE', 'rho': 0.90,
        'hints': ['hk_tape', 'bank_views', 'institution', 'XUEQIU', 'HSCE'],
        'keywords': ['国企', '恒生国企', '红筹', '中资股', '南向', '权重', '银行股', '金融'],
        'logic': '恒指与国企指数高度相关，结构价差偏离后回归。',
    },
    {
        'id': 'value_growth',
        'name': '国企与科技配对',
        'leg_a': 'HSCE', 'leg_b': 'HSTECH', 'rho': 0.72,
        'hints': ['HKPROP', 'DEFENSE', 'EASTMONEY', 'ANTFORTUNE', 'VIC', 'DISCUSS'],
        'keywords': ['内房', '地产', '高息', '红利', '股息', 'REITs', '公用', '电信', '防御'],
        'logic': '国企/高息与科技是港股内部的价值—成长两端，相对收益偏离后做配对回归。',
    },
    {
        'id': 'us_growth_value',
        'name': '美股成长/价值配对',
        'leg_a': 'NDQ', 'leg_b': 'DJI', 'rho': 0.75,
        'hints': ['DJI', 'global_risk'],
        'keywords': ['道指', '道琼斯', '蓝筹', '价值股'],
        'logic': '纳指与道指代表美股成长与价值，相对收益偏离后回归。',
    },
    {
        'id': 'us_beta',
        'name': '美股贝塔配对',
        'leg_a': 'NDQ', 'leg_b': 'SPX', 'rho': 0.88,
        'hints': ['NDQ', 'SPX'],
        'keywords': ['纳指', '纳斯达克', '标普'],
        'logic': '纳指相对标普的贝塔残差，偏离后做均值回归。',
    },
    {
        'id': 'cross_market',
        'name': '跨市场风险偏好配对',
        'leg_a': 'HSI', 'leg_b': 'SPX', 'rho': 0.45,
        'hints': ['macro', 'macro_growth', 'LAOHU', 'REDDIT'],
        'keywords': ['美股', '隔夜', '风险偏好', '再平衡', '外围'],
        'logic': '港股与标普是跨市场风险偏好的两端，相对收益偏离后做配对。',
    },
    {
        'id': 'growth_link',
        'name': '离岸科技联动配对',
        'leg_a': 'HSTECH', 'leg_b': 'NDQ', 'rho': 0.55,
        'hints': ['LIHKG'],
        'keywords': ['中概', 'ADR', '费城半导体'],
        'logic': '恒生科技与纳指同受全球成长因子驱动，联动残差偏离后回归。',
    },
    {
        'id': 'oil_curve',
        'name': '两油价差配对',
        'leg_a': 'WTI', 'leg_b': 'BRENT', 'rho': 0.92,
        'hints': ['commodities', 'WTI', 'BRENT', 'GEO'],
        'keywords': ['原油', '油价', 'WTI', '布伦特', '石油', 'OPEC', '欧佩克', '霍尔木兹'],
        'logic': 'WTI 与布伦特是同一能源因子的两条曲线，价差偏离后回归。',
    },
    {
        'id': 'cny_basis',
        'name': '离在岸人民币基差配对',
        'leg_a': 'USDCNH', 'leg_b': 'USDCNY', 'rho': 0.95,
        'hints': ['fed', 'fed_liquidity', 'USDCNH', 'USDCNY'],
        'keywords': ['离岸人民币', '在岸人民币', '人民币', 'CNH', 'CNY', '汇差', '中间价'],
        'logic': '离岸与在岸人民币高度联动，基差偏离后回归。',
    },
    {
        'id': 'gold_fx',
        'name': '黄金与离岸流动性配对',
        'leg_a': 'GOLD', 'leg_b': 'USDCNH', 'rho': 0.20,
        'hints': ['GOLD', 'FED', 'WALLSTREETCN', 'FINTWIT'],
        'keywords': ['黄金', '金价', '贵金属', '美联储', 'FOMC', '加息', '降息', '利率', '美债'],
        'logic': '黄金与离岸人民币同受美元流动性影响，相对收益偏离后做配对。',
    },
    {
        'id': 'risk_hedge',
        'name': '股金相对价值配对',
        'leg_a': 'SPX', 'leg_b': 'GOLD', 'rho': -0.10,
        'hints': ['risk_hedge'],
        'keywords': ['避险', '对冲'],
        'logic': '标普与黄金是风险资产与避险资产的经典配对，相对强弱偏离后回归。',
    },
    {
        'id': 'energy_equity',
        'name': '油价与权益配对',
        'leg_a': 'WTI', 'leg_b': 'SPX', 'rho': 0.20,
        'hints': ['energy'],
        'keywords': ['供应链', '输入性'],
        'logic': '油价冲击与权益指数的相对收益，偏离残差后做配对回归。',
    },
    {
        'id': 'hk_gold',
        'name': '港股与黄金对冲配对',
        'leg_a': 'HSI', 'leg_b': 'GOLD', 'rho': 0.15,
        'hints': ['hk_gold'],
        'keywords': ['避风港'],
        'logic': '恒指与黄金的相对收益，用于风险资产相对避险的配对回归。',
    },
    {
        'id': 'gold_oil',
        'name': '避险与能源配对',
        'leg_a': 'GOLD', 'leg_b': 'WTI', 'rho': 0.25,
        'hints': ['gold_oil'],
        'keywords': ['铜锂', '稀土', '铜铝'],
        'logic': '黄金与原油代表避险与能源两条商品链，相对收益偏离后回归。',
    },
]

_BY_ID = {s['id']: s for s in STRATEGIES}


def _esc(t):
    return html.escape(str(t if t is not None else ''), quote=False)


def _num(v):
    if v is None or v == '':
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return n


def normalize_quotes(quotes):
    """接受 market_data.json 根对象，或 quotes 字典。缺省返回空表。"""
    if not isinstance(quotes, dict):
        return {}
    if isinstance(quotes.get('quotes'), dict):
        quotes = quotes['quotes']
    out = {}
    for key, q in quotes.items():
        if not isinstance(q, dict):
            continue
        out[key] = {
            'name': q.get('name') or NAMES.get(key, key),
            'pct': _num(q.get('pct')),
            'as_of': q.get('as_of') or '',
        }
    return out


def _fmt_pct(v):
    if v is None:
        return '—'
    sign = MINUS if v < 0 else '+'
    return f'{sign}{abs(v):.2f}%'


def _fmt_pp(v):
    sign = MINUS if v < 0 else '+'
    return f'{sign}{abs(v):.2f}'


def pair_sigma(strategy):
    sa = DAILY_SIGMA[strategy['leg_a']]
    sb = DAILY_SIGMA[strategy['leg_b']]
    rho = max(-0.95, min(0.95, float(strategy['rho'])))
    var = sa * sa + sb * sb - 2.0 * rho * sa * sb
    return math.sqrt(max(var, 1e-6))


def _keyword_hits(strategy, text):
    if not text:
        return []
    low = text.lower()
    hits = []
    for kw in strategy['keywords']:
        if kw.lower() in low and kw not in hits:
            hits.append(kw)
    return hits


def _hint_from_text(text, hint):
    if hint:
        return hint
    blob = text or ''
    for name, key in NAME_TO_HINT:
        if name in blob:
            return key
    return None


def _score_strategy(strategy, text, hint):
    hits = _keyword_hits(strategy, text)
    score = KEYWORD_WEIGHT * len(hits)
    if hint and hint == strategy['id']:
        score += 12
    elif hint and (hint in strategy['hints'] or hint in (strategy['leg_a'], strategy['leg_b'])):
        score += HINT_WEIGHT
    return score, hits


def _z(strategy, quotes):
    qa = quotes.get(strategy['leg_a']) or {}
    qb = quotes.get(strategy['leg_b']) or {}
    pa, pb = qa.get('pct'), qb.get('pct')
    if pa is None or pb is None:
        return None
    return (pa - pb) / pair_sigma(strategy)


def select_strategy(text='', quotes=None, hint=None):
    """返回 (strategy, hits, reason)。reason ∈ keyword / hint / tape。"""
    quotes = normalize_quotes(quotes)
    hint = _hint_from_text(text, hint)
    if hint == 'tape':
        hint = None
        force_tape = True
    else:
        force_tape = False

    ranked = []
    for s in STRATEGIES:
        score, hits = _score_strategy(s, text, hint)
        ranked.append((score, hits, s))
    best = max(x[0] for x in ranked) if ranked else 0
    if force_tape or best <= 0:
        tradable = [s for s in STRATEGIES if _z(s, quotes) is not None]
        if tradable:
            tradable.sort(key=lambda s: (-abs(_z(s, quotes)), s['id']))
            return tradable[0], [], 'tape'
        return STRATEGIES[0], [], 'tape'

    cands = [x for x in ranked if x[0] == best]
    cands.sort(key=lambda x: (-abs(_z(x[2], quotes) or 0.0), x[2]['id']))
    score, hits, strategy = cands[0]
    reason = 'keyword' if hits else 'hint'
    return strategy, hits, reason


def _leg(quotes, key):
    q = quotes.get(key) or {}
    return {'key': key, 'name': q.get('name') or NAMES.get(key, key), 'pct': q.get('pct')}


def recommend(text='', quotes=None, hint=None):
    """为一条内容找到配对策略，给出两只标的，并按规则推荐。

    永远返回恰好两腿。行情不全时 action='no_data'，不编方向。
    """
    quotes = normalize_quotes(quotes)
    strategy, hits, reason = select_strategy(text, quotes, hint=hint)
    leg_a = _leg(quotes, strategy['leg_a'])
    leg_b = _leg(quotes, strategy['leg_b'])
    sigma = pair_sigma(strategy)
    pa, pb = leg_a['pct'], leg_b['pct']
    if pa is None or pb is None:
        spread = z = None
        action = 'no_data'
    else:
        spread = pa - pb
        z = spread / sigma
        if abs(z) < Z_ENTRY:
            action = 'wait'
        elif z <= -Z_ENTRY:
            action = 'long_a_short_b'
        else:
            action = 'short_a_long_b'

    a_name, b_name = leg_a['name'], leg_b['name']
    if action == 'no_data':
        stance = '数据不足'
        signal = f'{a_name} / {b_name} 当次涨跌幅不完整，配对价差无法计算。'
        recommendation = '不给出方向。两腿行情补齐后按同一规则复算，不回填历史点位。'
        confidence = 0.0
    elif action == 'wait':
        stance = '观望'
        signal = (f'{a_name} {_fmt_pct(pa)} · {b_name} {_fmt_pct(pb)} · '
                  f'相对价差 {_fmt_pp(spread)} 个百分点 · z={z:+.2f}。')
        recommendation = (f'价差未越过 1σ（残差阈值 {sigma:.2f} 个百分点），不建配对仓。')
        confidence = 0.38
    else:
        side = '轻仓' if abs(z) < Z_STRONG else '标准仓'
        signal = (f'{a_name} {_fmt_pct(pa)} · {b_name} {_fmt_pct(pb)} · '
                  f'相对价差 {_fmt_pp(spread)} 个百分点 · z={z:+.2f}。')
        if action == 'long_a_short_b':
            stance = f'做多{a_name} / 做空{b_name}'
            recommendation = f'{side}做多 {a_name}、做空 {b_name}。A 相对偏弱，等待价差回归。'
        else:
            stance = f'做空{a_name} / 做多{b_name}'
            recommendation = f'{side}做空 {a_name}、做多 {b_name}。A 相对偏强，等待价差回归。'
        confidence = 0.61 if abs(z) < Z_STRONG else 0.76
    if reason == 'tape':
        confidence = min(confidence, 0.50)
        why = '正文未指向特定配对，在当次两腿齐全的组合里取价差偏离最大者。'
    elif hits:
        why = f'正文命中「{"、".join(hits[:3])}」，选定本策略。'
    else:
        why = '按本条内容的主题映射选定本策略。'

    return {
        'strategy_id': strategy['id'],
        'strategy_name': strategy['name'],
        'family': '配对交易',
        'method': '相对收益均值回归',
        'logic': strategy['logic'],
        'leg_a': leg_a,
        'leg_b': leg_b,
        'pair_label': f'{a_name} / {b_name}',
        'spread': None if spread is None else round(spread, 4),
        'sigma': round(sigma, 4),
        'z': None if z is None else round(z, 2),
        'action': action,
        'stance': stance,
        'signal': signal,
        'recommendation': recommendation,
        'why': why,
        'rule': RULE,
        'confidence': round(confidence, 2),
        'hits': hits,
        'select_reason': reason,
    }


def render_web(rec, compact=False, note=''):
    """网页版。compact=True 时收成一行，仍包含策略 / 标的组合 / 推荐。"""
    if not rec:
        return ''
    note_html = f'<div class="ai-quant-meta">{_esc(note)}</div>' if note else ''
    if compact:
        return (
            '<div class="ai-quant ai-quant-compact" data-ai-quant="1">'
            '<strong>◆ AI 量化</strong> · 策略：' + _esc(rec['strategy_name'])
            + ' · 标的组合：' + _esc(rec['pair_label'])
            + ' · 推荐：' + _esc(rec['stance']) + '。' + _esc(rec['recommendation'])
            + (f' <span class="ai-quant-meta">{_esc(note)}</span>' if note else '')
            + '</div>'
        )
    conf = int(round((rec.get('confidence') or 0) * 100))
    return (
        '<div class="ai-quant" data-ai-quant="1" data-strategy="' + _esc(rec['strategy_id']) + '">\n'
        '  <div class="ai-quant-title">◆ AI 量化 · 配对交易'
        '<span>两标的组合</span></div>\n'
        '  <ul class="ai-quant-list">\n'
        f'    <li><strong>策略：</strong>{_esc(rec["strategy_name"])}'
        f'（{_esc(rec["family"])} · {_esc(rec["method"])}）</li>\n'
        f'    <li><strong>标的组合：</strong>{_esc(rec["pair_label"])}</li>\n'
        f'    <li><strong>当次信号：</strong>{_esc(rec["signal"])}</li>\n'
        f'    <li><strong>推荐：</strong>{_esc(rec["stance"])}。{_esc(rec["recommendation"])}'
        f'（置信度 {conf}%）</li>\n'
        '  </ul>\n'
        f'  <div class="ai-quant-meta">{_esc(rec["why"])} {_esc(rec["logic"])}</div>\n'
        f'  <div class="ai-quant-meta">{_esc(rec["rule"])}</div>\n'
        f'{note_html}'
        '</div>'
    )


def render_web_list(recs, note=''):
    """一条内容里有多组标的时，合成一块 AI 量化，每组一行。"""
    recs = [r for r in (recs or []) if r]
    if not recs:
        return ''
    items = []
    for r in recs:
        items.append(
            '<li><strong>策略：</strong>' + _esc(r['strategy_name'])
            + ' · <strong>标的组合：</strong>' + _esc(r['pair_label'])
            + ' · <strong>推荐：</strong>' + _esc(r['stance'])
            + '。' + _esc(r['recommendation']) + '</li>'
        )
    tail = f'<div class="ai-quant-meta">{_esc(note)}</div>' if note else ''
    return (
        '<div class="ai-quant" data-ai-quant="1">\n'
        '  <div class="ai-quant-title">◆ AI 量化 · 配对交易<span>两标的组合</span></div>\n'
        '  <ul class="ai-quant-list">\n    ' + '\n    '.join(items) + '\n  </ul>\n'
        f'  <div class="ai-quant-meta">{_esc(RULE)}</div>\n'
        f'{tail}</div>'
    )


# ---------------------------------------------------------------------------
# 微信版的样式常量
# ---------------------------------------------------------------------------
# 微信单页有 10 万字符硬上限、95,000 推送门禁。整篇推送里挂着 50 块 AI 量化，
# 重复的内联样式与逐块重复的规则说明加起来是全文最大的一笔开销（实测占约四分之一）。
# 所以微信版做了两件纯样式/排版的瘦身，**信息一条没删**：
#   ① 四行要点从四个 <div> 合成一段 <br/> 分隔的文本，省掉四组重复 style；
#   ② 规则说明不再逐块重复 —— 由 rule_note_wechat() 在推送里整篇只印一次
#      （show_rule=True 可让单独出现的块自带规则）。
# 网页版没有字符上限，保持原样逐块带规则，不受影响。
_WX_BOX = ('background:#f4f7f4;border:1px solid #007a35;border-left:3px solid #000;'
           'border-radius:6px;padding:9px 11px;margin-top:9px;font-size:11px;line-height:1.7')
_WX_COMPACT = ('background:#f4f7f4;border:1px solid #007a35;border-radius:4px;'
               'padding:6px 8px;margin-top:6px;font-size:11px;line-height:1.65')
_WX_TITLE = 'color:#000;font-weight:700;font-size:12px'
_WX_CHIP = 'background:#000;color:#39ff14;font-size:10px;padding:1px 6px;margin-left:4px'
_WX_META = 'color:#7d838b;font-size:10px;margin-top:6px'


def rule_note_wechat(label='AI 量化 · 配对交易'):
    """整篇推送只印一次的配对规则说明（各处 AI 量化块共用同一口径）。"""
    return (f'<div style="{_WX_META}">{_esc(label)}规则（全文各块共用同一口径）：{_esc(RULE)}</div>')


def render_wechat(rec, compact=False, note='', show_rule=False):
    """微信版：全内联样式，口径与网页版一致。

    show_rule 默认关闭：规则说明由 rule_note_wechat() 在整篇里印一次，
    避免同一段 100 字的规则在 20 多个块里重复（微信单页字符预算很紧）。
    """
    if not rec:
        return ''
    note_html = (f'<div style="color:#7d838b;font-size:10px;margin-top:4px;">{_esc(note)}</div>'
                 if note else '')
    if compact:
        return (
            f'<div style="{_WX_COMPACT}">'
            '<strong style="color:#007a35;">◆ AI 量化</strong> · 策略：' + _esc(rec['strategy_name'])
            + ' · 标的组合：' + _esc(rec['pair_label'])
            + ' · 推荐：' + _esc(rec['stance']) + '。' + _esc(rec['recommendation'])
            + ((' · ' + _esc(note)) if note else '')
            + '</div>'
        )
    conf = int(round((rec.get('confidence') or 0) * 100))
    return (
        f'<div style="{_WX_BOX}">'
        f'<div style="{_WX_TITLE}">◆ AI 量化 · 配对交易'
        f'<span style="{_WX_CHIP}">两标的组合</span></div>'
        f'◦ <strong>策略：</strong>{_esc(rec["strategy_name"])}'
        f'（{_esc(rec["family"])} · {_esc(rec["method"])}）<br/>'
        f'◦ <strong>标的组合：</strong>{_esc(rec["pair_label"])}<br/>'
        f'◦ <strong>当次信号：</strong>{_esc(rec["signal"])}<br/>'
        f'◦ <strong>推荐：</strong>{_esc(rec["stance"])}。{_esc(rec["recommendation"])}'
        f'（置信度 {conf}%）'
        f'<div style="{_WX_META}">{_esc(rec["why"])} {_esc(rec["logic"])}</div>'
        + (f'<div style="{_WX_META}">{_esc(rec["rule"])}</div>' if show_rule else '')
        + f'{note_html}</div>'
    )


def render_wechat_list(recs, note=''):
    recs = [r for r in (recs or []) if r]
    if not recs:
        return ''
    rows = '<br/>'.join(
        '◦ <strong>策略：</strong>' + _esc(r['strategy_name'])
        + ' · <strong>标的组合：</strong>' + _esc(r['pair_label'])
        + ' · <strong>推荐：</strong>' + _esc(r['stance'])
        + '。' + _esc(r['recommendation'])
        for r in recs
    )
    note_html = (f'<div style="color:#7d838b;font-size:10px;margin-top:4px;">{_esc(note)}</div>'
                 if note else '')
    return (
        f'<div style="{_WX_BOX}">'
        f'<div style="{_WX_TITLE}">◆ AI 量化 · 配对交易'
        f'<span style="{_WX_CHIP}">两标的组合</span></div>'
        + rows + note_html + '</div>'
    )


def _self_test():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(('  ✅ ' if cond else '  ❌ ') + msg)
        ok = ok and bool(cond)

    empty = recommend('随便一条没有主题的内容', {})
    check(empty['action'] == 'no_data', '无行情：不给方向')
    check(empty['leg_a']['key'] and empty['leg_b']['key'], '无行情：仍然给出两只标的')
    check(empty['leg_a']['key'] != empty['leg_b']['key'], '两腿不是同一只')
    check('%' not in empty['signal'], '无行情：信号里不编涨跌幅')
    check('25,440' not in json.dumps(empty, ensure_ascii=False), '无行情：不回填历史点位')

    quotes = {'quotes': {
        'HSTECH': {'name': '恒生科技指数', 'pct': 3.0},
        'HSI': {'name': '恒生指数', 'pct': 0.2},
        'WTI': {'name': 'WTI 原油', 'pct': 2.4},
        'BRENT': {'name': '布伦特原油', 'pct': 0.3},
        'GOLD': {'name': '现货黄金', 'pct': 0.4},
        'USDCNH': {'name': '美元/离岸人民币', 'pct': -0.05},
        'USDCNY': {'name': '美元/在岸人民币', 'pct': -0.04},
        'SPX': {'name': '标普 500', 'pct': 0.2},
        'NDQ': {'name': '纳斯达克', 'pct': 0.3},
        'DJI': {'name': '道琼斯', 'pct': 0.1},
        'HSCE': {'name': '恒生中国企业指数', 'pct': 0.4},
    }}
    growth = recommend('恒生科技相对恒指的成长轮动', quotes, hint='rotation')
    check(growth['strategy_id'] == 'hk_growth_value', f'成长轮动选中港股成长/价值（{growth["strategy_id"]}）')
    check(growth['action'] == 'short_a_long_b', '科技明显强于恒指 → 空A多B')
    check('做空' in growth['stance'] and '做多' in growth['stance'], '推荐同时给出多空两腿')

    flat = recommend('恒生科技与恒指', {
        'HSTECH': {'pct': 0.05}, 'HSI': {'pct': 0.04},
    }, hint='hk_growth_value')
    check(flat['action'] == 'wait', '价差在 1σ 内 → 观望')

    oil = recommend('富途社区在讨论原油、WTI 与布伦特价差', quotes, hint='FUTU')
    check(oil['strategy_id'] == 'oil_curve', f'主题词覆盖频道默认（{oil["strategy_id"]}）')
    check(oil['leg_a']['key'] == 'WTI' and oil['leg_b']['key'] == 'BRENT', '两油组合固定为两只标的')

    fed = recommend('美联储利率路径与黄金', quotes, hint='fed')
    check(fed['strategy_id'] == 'gold_fx', f'利率/黄金选中黄金流动性配对（{fed["strategy_id"]}）')

    web, wx = render_web(oil), render_wechat(oil)
    for blob in (web, wx, render_web(oil, compact=True), render_wechat(oil, compact=True)):
        check('AI 量化' in blob and '标的组合' in blob and '推荐' in blob, '渲染包含策略要素')
    check('data-ai-quant="1"' in web, '网页块可被计数')
    check(len({s['leg_a'] + '/' + s['leg_b'] for s in STRATEGIES}) == len(STRATEGIES),
          '策略目录里每条组合都不重复')
    check(all(s['leg_a'] != s['leg_b'] for s in STRATEGIES), '每条策略都是两只不同标的')
    print('\n' + ('✅ quant_pair 自检全部通过' if ok else '❌ quant_pair 自检存在失败项'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description='AI 量化 · 配对交易（为一条内容选策略并推荐）')
    ap.add_argument('--text', default='', help='内容正文，用来选策略')
    ap.add_argument('--hint', default='', help='主题 key（如 rotation / commodities / FUTU）')
    ap.add_argument('--quotes', default='', help='market_data.json 路径，缺省则只选策略不给方向')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        sys.exit(_self_test())
    quotes = {}
    if args.quotes and os.path.exists(args.quotes):
        with open(args.quotes, encoding='utf-8') as f:
            quotes = json.load(f)
    rec = recommend(args.text, quotes, hint=args.hint or None)
    print(json.dumps(rec, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
