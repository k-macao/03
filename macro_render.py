#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 量化策略日报 — 宏观层渲染与时效护栏 (macro_render.py)

为什么单独一个模块:
  02 节「全球经济与财经动态」以前是 tools/wechat_push.py 里的一段字符串字面量，
  网页端 report.html 甚至根本没有这一节 —— 于是"推送有、网页无"，且推送内容永远停在 7–8 月。
  本模块把 02 节改成 **数据驱动渲染**，并由微信推送与网页构建 **共用同一份渲染结果**，
  保证两端口径一致；同时提供统一的时效护栏（每项断言必须带 as_of，陈旧/缺失自动降级）。

三条硬规则（改代码前先读）:
  1. 没有数据就没有句子 —— status='missing' 的指标一律不渲染任何数值断言，只写「未取到」。
  2. 有数据就必须带 vintage —— 每个数值后面跟「源 · 截至 YYYY-MM-DD」，陈旧项再加 ⚠️ 标签。
  3. 不得把兜底值伪装成实时值 —— 本模块不提供任何"写死的默认行情数字"。
"""
import html as _html
import json
import os
import re
from datetime import date, datetime, timedelta, timezone


def _esc(t):
    """网页端文本转义（<>& 等），None → 空串。"""
    return _html.escape(str(t if t is not None else ''), quote=False)

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

STATUS_LABEL = {
    'live': '实时',
    'demo': '演示值',
    'mock': '离线回放',
    'manual': '人工维护',
    'stale': '⚠️ 数据陈旧',
    'missing': '❌ 未取到',
}


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def _load_json(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_macro(path=None):
    return _load_json(path or os.environ.get(
        'MACRO_DATA', os.path.join(REPO_ROOT, 'macro_data.json')))


def load_market(path=None):
    return _load_json(path or os.environ.get(
        'MARKET_DATA', os.path.join(REPO_ROOT, 'market_data.json')))


def load_community(path=None):
    return _load_json(path or os.environ.get(
        'COMMUNITY_DATA', os.path.join(REPO_ROOT, 'community_data.json')))


def load_sentiment(path=None):
    return _load_json(path or os.environ.get(
        'SENTIMENT_DATA', os.path.join(REPO_ROOT, 'sentiment_data.json')))


# ---------------------------------------------------------------------------
# 取值 / 断言渲染
# ---------------------------------------------------------------------------
def indicator(macro, key):
    return (macro.get('indicators') or {}).get(key) or {}


def manual_item(macro, key):
    return (macro.get('manual') or {}).get(key) or {}


def quote(market, key):
    return (market.get('quotes') or {}).get(key) or {}


def num(market, key):
    """行情数值格式化；缺失返回 None（调用方据此决定不渲染该断言）。"""
    q = quote(market, key)
    v = q.get('last')
    if v is None:
        return None
    nd = int(q.get('decimals') or 2)
    if q.get('name') == '现货黄金' and float(v) >= 1000:
        nd = 0
    return f'{float(v):,.{nd}f}'


def pct(market, key):
    q = quote(market, key)
    v = q.get('pct')
    if v is None:
        return None
    v = float(v)
    return f'{"−" if v < 0 else "+"}{abs(v):,.2f}%'


def signed(v, digits=2, suffix=''):
    if v is None:
        return None
    v = float(v)
    return f'{"−" if v < 0 else "+"}{abs(v):,.{digits}f}{suffix}'


def vintage(rec, with_source=True):
    """「（源 · 截至 YYYY-MM-DD）」——所有断言都必须带。"""
    if not rec:
        return ''
    as_of = rec.get('as_of') or '—'
    src = rec.get('source') or ''
    if not with_source or not src:
        return f'（截至 {as_of}）'
    return f'（{src} · 截至 {as_of}）'


def status_tag(rec):
    st = rec.get('status')
    if st in (None, 'live'):
        return ''
    label = STATUS_LABEL.get(st, st)
    if st == 'stale':
        return f'　<strong>{label} · 截至 {rec.get("as_of") or "—"}（{rec.get("age_days")} 天前，' \
               f'上限 {rec.get("max_age_days")} 天）</strong>'
    if st == 'missing':
        return f'　<strong>{label}</strong>'
    return f'　<span>[{label}]</span>'


def claim(rec, value_text=None):
    """把一条指标渲染成「数值（源 · 截至 X）」；缺失返回 None（= 不作断言）。"""
    if not rec or rec.get('status') == 'missing' or rec.get('value') is None:
        return None
    text = value_text or rec.get('display') or str(rec.get('value'))
    return f'{text}{vintage(rec)}{status_tag(rec)}'


# ---------------------------------------------------------------------------
# 事件日历（"下一观察点"永远指向未来）
# ---------------------------------------------------------------------------
def next_events(macro, limit=4):
    return ((macro.get('events') or {}).get('upcoming') or [])[:limit]


def events_line(macro):
    evs = next_events(macro)
    cal = macro.get('events') or {}
    if not evs:
        return ('<strong>⚠️ 事件日历已无未来观察点</strong>（日历 vintage '
                f'{cal.get("calendar_vintage", "—")}）—— 请更新 macro_data.py 的 EVENT_CALENDAR，'
                '本节不再给出任何"下一观察点"断言。')
    parts = []
    for e in evs:
        d = e.get('days_until')
        when = '今日' if d == 0 else (f'{d} 天后' if d is not None else '')
        parts.append(f'{e.get("date")} {e.get("name")}' + (f'（{when}）' if when else ''))
    tail = ''
    if cal.get('needs_update'):
        tail = ('　<strong>⚠️ 日历剩余观察点不足 30 天，需更新</strong>'
                f'（vintage {cal.get("calendar_vintage", "—")}）')
    return '下一观察点：' + '；'.join(parts) + \
        f'　<span>[{cal.get("calendar_source", "官方日程")}]</span>' + tail


# ---------------------------------------------------------------------------
# 02 节内容块（微信与网页共用）
# ---------------------------------------------------------------------------
def _cn_month(as_of):
    m = re.match(r'(20\d{2})-(\d{2})', str(as_of or ''))
    return f'{int(m.group(1))} 年 {int(m.group(2))} 月' if m else None


def build_blocks(macro, market, today=None):
    """返回 [{'title','body','status'}]，body 为最小标记（<strong>/<br/>/<span>），两端通用。"""
    today = today or datetime.now(timezone.utc).date()
    blocks = []

    # ---- 1. 全球增长 ----
    imf = manual_item(macro, 'imf_weo')
    wb = indicator(macro, 'world_growth')
    geo = manual_item(macro, 'geopolitics_note')
    lines = []
    if imf and imf.get('status') != 'missing':
        extra = imf.get('extra') or {}
        seg = f'IMF《世界经济展望》全球增速预测 <strong>{imf.get("display")}</strong>'
        if extra.get('prev_forecast') is not None:
            seg += f'（{extra.get("prev_forecast_vintage", "上一期")} 预测 {extra["prev_forecast"]}%）'
        seg += vintage(imf) + status_tag(imf)
        lines.append(seg)
    else:
        lines.append('IMF《世界经济展望》预测：<strong>❌ 人工项缺失，不作断言</strong>'
                     '（请在 macro_manual_inputs.json 补 value/as_of）')
    if wb.get('value') is not None:
        det = wb.get('detail') or {}
        lines.append(f'世界银行口径全球实际 GDP 增速 <strong>{wb.get("display")}</strong>'
                     f'（{det.get("year")} 年'
                     + (f'，前一年 {det["prev_value"]}%' if det.get('prev_value') is not None else '')
                     + f'）{vintage(wb)}{status_tag(wb)}')
    if geo and geo.get('status') != 'missing':
        lines.append(f'地缘与能源溢价：{geo.get("value")}{vintage(geo)}{status_tag(geo)}')
    blocks.append({'title': '◆ 全球增长 — IMF / 世界银行', 'body': '<br/>'.join(lines),
                   'status': _worst([imf, wb, geo])})

    # ---- 2. 美联储 ----
    fed = indicator(macro, 'fed_rate')
    cpi = indicator(macro, 'us_cpi')
    core = indicator(macro, 'us_core_cpi')
    nfp = indicator(macro, 'us_nfp')
    us10y = indicator(macro, 'us10y')
    lines = []
    if fed.get('value') is not None:
        det = fed.get('detail') or {}
        seg = f'联邦基金目标区间 <strong>{fed.get("display")}</strong>'
        if det.get('unchanged_since'):
            seg += (f'，自 {det["unchanged_since"]} 起未调整'
                    f'（{det.get("unchanged_days")} 天）')
        lines.append(seg + vintage(fed) + status_tag(fed))
    else:
        lines.append('联邦基金目标区间：<strong>❌ 未取到，不作断言</strong>')
    infl = []
    if cpi.get('value') is not None:
        det = cpi.get('detail') or {}
        s = f'CPI 同比 <strong>{cpi.get("display")}</strong>'
        if det.get('prev_value') is not None:
            s += f'（前值 {det["prev_value"]:.1f}%）'
        s += f'，观测期 {_cn_month(cpi.get("as_of"))}'
        infl.append(s + vintage(cpi) + status_tag(cpi))
    if core.get('value') is not None:
        det = core.get('detail') or {}
        s = f'核心 CPI 同比 <strong>{core.get("display")}</strong>'
        if det.get('prev_value') is not None:
            s += f'（前值 {det["prev_value"]:.1f}%）'
        infl.append(s + vintage(core) + status_tag(core))
    if nfp.get('value') is not None:
        det = nfp.get('detail') or {}
        s = f'非农新增 <strong>{nfp.get("display")}</strong>'
        if det.get('prev_chg') is not None:
            s += f'（前月 {signed(det["prev_chg"], 0, " 千人")}）'
        s += f'，观测期 {_cn_month(nfp.get("as_of"))}'
        infl.append(s + vintage(nfp) + status_tag(nfp))
    lines.append('；'.join(infl) if infl else '美国通胀与就业：<strong>❌ 未取到，不作断言</strong>')
    if us10y.get('value') is not None:
        lines.append(f'美债 10 年期收益率 <strong>{us10y.get("display")}</strong>'
                     f'{vintage(us10y)}{status_tag(us10y)}')
    nxt = cpi.get('next_period_hint') or core.get('next_period_hint')
    lines.append(events_line(macro) +
                 (f'<br/>美国月度数据下一期覆盖 {nxt}（具体公布日以 BLS / BEA 官方日程为准，本模块不猜测日期）'
                  if nxt else ''))
    blocks.append({'title': '◆ 美联储利率路径与离岸流动性', 'body': '<br/>'.join(lines),
                   'status': _worst([fed, cpi, core, nfp, us10y])})

    # ---- 3. 中国物价 ----
    cn = indicator(macro, 'cn_cpi')
    if cn.get('value') is not None:
        det = cn.get('detail') or {}
        body = (f'全国居民消费价格同比 <strong>{cn.get("display")}</strong>'
                f'（{det.get("period", _cn_month(cn.get("as_of")))}'
                + (f'，环比 {signed(det.get("mom_pct"), 1, "%")}' if det.get('mom_pct') is not None else '')
                + (f'；前值 {det["prev_value"]:.1f}%（{det.get("prev_period", "")}）'
                   if det.get('prev_value') is not None else '')
                + f'）{vintage(cn)}{status_tag(cn)}')
        if cn.get('next_period_hint'):
            body += f'<br/>下一期覆盖 {cn["next_period_hint"]}（以国家统计局日程为准）'
    else:
        body = '中国 CPI：<strong>❌ 未取到，不作断言</strong>'
    blocks.append({'title': '◆ 中国物价', 'body': body, 'status': _worst([cn])})

    # ---- 4. 港股市场（行情 + 动态技术面 + 港股通） ----
    hsi, hstech = quote(market, 'HSI'), quote(market, 'HSTECH')
    tech = hsi.get('tech') or {}
    hkc = indicator(macro, 'hk_connect')
    lines = []
    if hsi.get('last') is not None:
        seg = (f'恒生指数收报 <strong>{num(market, "HSI")}</strong> 点'
               f'（{pct(market, "HSI")}，{hsi.get("as_of")}）')
        if hstech.get('last') is not None:
            seg += f'，恒生科技指数 <strong>{num(market, "HSTECH")}</strong>（{pct(market, "HSTECH")}）'
        seg += f'　<span>[{hsi.get("source") or "—"}]</span>'
        lines.append(seg)
    else:
        lines.append('<strong>❌ 恒指行情未取到</strong> —— 本节不给出任何指数点位、涨跌幅或箱体断言'
                     '（点位类断言只在本次抓取成功时渲染，不引用未经核实的数字）')
    if tech:
        lines.append(
            f'动态技术面（{tech.get("points")} 根日线，截至 {tech.get("as_of")}）：'
            f'EMA9 <strong>{tech.get("ema9")}</strong> / EMA21 <strong>{tech.get("ema21")}</strong>'
            f'（{tech.get("ema_state") or "—"}）· MA50 {tech.get("ma50") or "—"} · '
            f'RSI14 <strong>{tech.get("rsi14")}</strong>（{tech.get("rsi_state") or "—"}）<br/>'
            f'近 20 日箱体 <strong>{tech.get("box_low_20d")}–{tech.get("box_high_20d")}</strong>'
            f'（6 个月高低 {tech.get("low_6mo")} / {tech.get("high_6mo")}）· '
            f'涨跌 5 日 {signed(tech.get("chg_5d_pct"), 2, "%") or "—"} / '
            f'1 月 {signed(tech.get("chg_1m_pct"), 2, "%") or "—"} / '
            f'3 月 {signed(tech.get("chg_3m_pct"), 2, "%") or "—"}'
            '<br/><span>技术位由 market_data.py 每次构建按日线实时计算，不再写死</span>')
    else:
        lines.append('动态技术面：<strong>❌ 历史 K 线未取到</strong> —— 不给出 EMA / RSI / '
                     '箱体 / 止损位断言（技术位只在取到日线时按当次数据计算）')
    if hkc.get('value') is not None:
        det = hkc.get('detail') or {}
        seg = (f'港股通（沪+深）成交额 <strong>{hkc.get("display")}</strong>'
               f'（{det.get("channels", "—")} 个通道，{hkc.get("as_of")}）')
        if det.get('hold_market_cap'):
            # 接口 HOLD_MARKET_CAP 单位为百万元 → /100 得亿元（万亿级再折算显示）
            yi = det['hold_market_cap'] / 100.0
            seg += (f'，持股市值约 {yi / 10000:,.2f} 万亿元' if yi >= 10000
                    else f'，持股市值约 {yi:,.0f} 亿元')
        seg += vintage(hkc, with_source=False) + status_tag(hkc)
        if not det.get('net_deal_published'):
            seg += ('<br/><span>交易所自 2024-08 起停止公布港股通单日净买入额（接口返回 null），'
                    '故本报告不再引用"南向净买入 XXX 亿"这类无法核实的数字</span>')
        lines.append(seg)
    else:
        lines.append('港股通资金：<strong>❌ 未取到，不作断言</strong>')
    blocks.append({'title': '◆ 港股市场 — 行情、动态技术面与港股通',
                   'body': '<br/>'.join(lines), 'status': _worst([hkc])})

    # ---- 5. 大宗商品 ----
    gold, wti, brent = num(market, 'GOLD'), num(market, 'WTI'), num(market, 'BRENT')
    cu = indicator(macro, 'copper')
    li = manual_item(macro, 'lithium_carbonate')
    lines = []
    if gold or wti or brent:
        seg = []
        if gold:
            seg.append(f'黄金 <strong>{gold}</strong> 美元/盎司（{pct(market, "GOLD") or "—"}）')
        if wti:
            seg.append(f'WTI <strong>{wti}</strong> 美元/桶')
        if brent:
            seg.append(f'布伦特 <strong>{brent}</strong> 美元/桶')
        as_of = quote(market, 'GOLD').get('as_of') or quote(market, 'WTI').get('as_of') or '—'
        lines.append('·'.join(seg) + f'（market_data.py · 截至 {as_of}）')
    else:
        lines.append('能源与贵金属：<strong>❌ 行情未取到，不作断言</strong>')
    if cu.get('value') is not None:
        det = cu.get('detail') or {}
        s = f'铜 <strong>{cu.get("display")}</strong>'
        if det.get('usd_per_lb'):
            s += f'（约 {det["usd_per_lb"]} 美元/磅'
            s += f'，同比 {signed(det.get("yoy_pct"), 1, "%")}' if det.get('yoy_pct') is not None else ''
            s += '）'
        lines.append(s + vintage(cu) + status_tag(cu))
    else:
        lines.append('铜：<strong>❌ 未取到，不作断言</strong>')
    if li and li.get('status') != 'missing':
        lines.append(f'碳酸锂 <strong>{li.get("display")}</strong>{vintage(li)}{status_tag(li)}')
    else:
        lines.append('碳酸锂：<strong>❌ 人工项缺失/过期，不作断言</strong>')
    blocks.append({'title': '◆ 大宗商品与供应链风险矩阵', 'body': '<br/>'.join(lines),
                   'status': _worst([cu, li])})

    # ---- 6. 大行目标价（人工项，必带 vintage） ----
    bt = manual_item(macro, 'bank_targets')
    if bt and bt.get('status') != 'missing' and bt.get('targets'):
        rows = [f'• <strong>{t.get("bank")}</strong>：基准 {t.get("base") or "—"}'
                + (f'；乐观 {t["bull"]}' if t.get('bull') else '')
                + (f'；悲观底线 {t["bear"]}' if t.get('bear') else '')
                + (f'（{t["note"]}）' if t.get('note') else '')
                for t in bt['targets']]
        body = '<br/>'.join(rows) + vintage(bt) + status_tag(bt) + \
            '<br/><span>目标价为机构预测，人工维护于 macro_manual_inputs.json，' \
            f'超过 {bt.get("max_age_days")} 天未复核会自动判陈旧</span>'
    else:
        body = ('大行目标价：<strong>❌ 人工项缺失或已过期</strong> —— '
                '不再渲染任何未经复核的目标价（原写死的 31,000 / 30,000 / 28,000–29,000 已移入带日期的维护文件）')
    blocks.append({'title': '◆ 主要国际与中资大行恒指目标价', 'body': body,
                   'status': _worst([bt])})

    return blocks


# ---------------------------------------------------------------------------
# 07 节「核心结论」——网页与微信推送共用同一份推导逻辑（不再各写一套）
# ---------------------------------------------------------------------------
VERDICT_MACRO_KEYS = (
    ('imf_weo', 'IMF 全球增速'), ('world_growth', '世行全球增速'),
    ('fed_rate', '联邦基金区间'), ('us_cpi', '美国 CPI 同比'),
    ('us_core_cpi', '核心 CPI'), ('us_nfp', '非农新增'),
    ('us10y', '美债 10 年'), ('cn_cpi', '中国 CPI 同比'),
)

VERDICT_NOTE = ('本节全部结论由 macro_data.json / market_data.json / sentiment_data.json 动态推导；'
                '缺失项显式标注「未取到」，不含任何写死的点位、日期或资金流数字。')


def _chg_desc(q):
    """恒指涨跌描述；缺失返回 None（调用方据此不渲染断言）。"""
    if not q or q.get('chg') is None:
        return None
    v = float(q['chg'])
    return f'{"跌" if v < 0 else "涨"} {abs(v):,.2f} 点'


def verdict_items(macro, market, sentiment=None, today=None):
    """07 节核心结论条目：[{'label','text','kind'}]，全部由数据推导。

    与 02 节同一套纪律：取不到 → 写「❌ 未取到，不作断言」，绝不用旧值兜底。
    """
    items = []

    # 1) 全球宏观面
    pts = []
    for key, lead in VERDICT_MACRO_KEYS:
        rec = indicator(macro, key) or manual_item(macro, key)
        c = claim(rec)
        pts.append(f'{lead} {c}' if c else f'{lead} <strong>❌ 未取到</strong>')
    items.append({'label': '全球宏观面', 'text': '；'.join(pts) + '。', 'kind': 'item'})

    # 2) 港股市场面
    hsi = quote(market, 'HSI') or {}
    hsi_n, hsi_p = num(market, 'HSI'), pct(market, 'HSI')
    if hsi_n:
        seg = f'恒指 {hsi_n}（{hsi_p or "—"}，截至 {hsi.get("as_of") or "—"}）'
        cd = _chg_desc(hsi)
        if cd:
            seg += f'，{cd}'
        if num(market, 'HSTECH'):
            seg += f'；恒生科技 {num(market, "HSTECH")}（{pct(market, "HSTECH")}）'
        hkc = indicator(macro, 'hk_connect')
        if hkc.get('value') is not None:
            seg += f'；港股通成交额 {hkc.get("display")}（{hkc.get("as_of")}）'
        items.append({'label': '港股市场面', 'text': seg + '。', 'kind': 'item'})
    else:
        items.append({'label': '港股市场面',
                      'text': '❌ 行情未取到，不给出点位/资金面断言。', 'kind': 'missing'})

    # 3) 技术位与战术（动态计算）
    tech = hsi.get('tech') or {}
    if tech:
        t = []
        rsi = tech.get('rsi14')
        if rsi is not None:
            t.append(f'RSI14 {rsi}' + ('（超买：不追高，等回踩均线带）' if rsi >= 70
                                       else '（超卖：关注反弹但需右侧确认）' if rsi <= 30
                                       else '（中性区间）'))
        if tech.get('ema_state'):
            t.append(tech['ema_state'] + ('，回踩 EMA21 附近分批' if tech['ema_state'] == '多头排列'
                                          else '，等 EMA9 上穿 EMA21 金叉再进场'))
        if tech.get('box_low_20d') and tech.get('box_high_20d'):
            t.append(f'支撑 {tech["box_low_20d"]} / 压力 {tech["box_high_20d"]}'
                     f'（近 20 日实际高低点，截至 {tech.get("as_of")}）')
        if tech.get('ma50'):
            t.append(f'MA50 {tech["ma50"]}')
        items.append({'label': '技术位与战术（动态计算）', 'text': '；'.join(t) + '。', 'kind': 'item'})
    else:
        items.append({'label': '技术位与战术',
                      'text': '❌ 历史 K 线未取到，不给出支撑/压力/止损位'
                              '（技术位只在取到日线时按当次数据计算）。', 'kind': 'missing'})

    # 4) 对冲底仓（只列有数据的品种）
    hedge = []
    if num(market, 'GOLD'):
        hedge.append(f'黄金 {num(market, "GOLD")} 美元/盎司（{pct(market, "GOLD") or "—"}）')
    cu = indicator(macro, 'copper')
    if cu.get('value') is not None:
        hedge.append(f'铜 {cu.get("display")}')
    li = manual_item(macro, 'lithium_carbonate')
    if li.get('status') not in (None, 'missing'):
        hedge.append(f'碳酸锂 {li.get("display")}' + ('（⚠️ 陈旧）' if li.get('status') == 'stale' else ''))
    items.append({'label': '对冲底仓（仅列有数据的品种）',
                  'text': ('、'.join(hedge) if hedge else '❌ 未取到，不作断言') + '。',
                  'kind': 'item' if hedge else 'missing'})

    # 5) 情绪指标
    smk = (sentiment or {}).get('market') or {}
    if smk:
        items.append({'label': '情绪指标',
                      'text': f'舆情温度计 {smk.get("sent_temp", "—")}（{smk.get("label", "—")}）· '
                              f'净情感 {smk.get("net_senti", "—")} · '
                              f'负面占比 {smk.get("neg_share", "—")}% · 热度 {smk.get("heat_z", "—")}σ'
                              f'（sentiment_factors.py，数据日期 {(sentiment or {}).get("fetch_date", "—")}）。',
                      'kind': 'item'})
    else:
        items.append({'label': '情绪指标', 'text': '❌ 舆情因子未取到，不作断言。', 'kind': 'missing'})

    # 6) 下一观察点（事件日历动态推导）
    evs = next_events(macro, 3)
    if evs:
        items.append({'label': '下一观察点（事件日历动态推导）',
                      'text': '；'.join(f'{e["date"]} {e["name"]}' for e in evs) + '。', 'kind': 'item'})
    else:
        items.append({'label': '下一观察点',
                      'text': '❌ 事件日历已无未来观察点，请更新 macro_data.py 的 EVENT_CALENDAR。',
                      'kind': 'missing'})

    items.append({'label': None, 'text': VERDICT_NOTE, 'kind': 'note'})
    return items


def render_verdict_wechat(items):
    out = []
    for it in items:
        if it['kind'] == 'note':
            out.append(f'<span style="color:#7d838b;font-size:10px;">{it["text"]}</span>')
        else:
            out.append(f'• <strong>{it["label"]}</strong>：{it["text"]}<br/>')
    return ''.join(out)


def render_verdict_web(items):
    """网页 07 节：<ul class="pixel-list"> 里的 <li> 列表。"""
    out = []
    for it in items:
        if it['kind'] == 'note':
            out.append(f'<li class="verdict-note"><span>{it["text"]}</span></li>')
        else:
            cls = ' class="is-missing"' if it['kind'] == 'missing' else ''
            out.append(f'<li{cls}><strong>{it["label"]}</strong>：{it["text"]}</li>')
    return '\n'.join(out)


def _worst(recs):
    order = {'missing': 2, 'stale': 1, 'manual': 0, 'mock': 0, 'demo': 0, 'live': 0, None: 0}
    recs = [r for r in recs if isinstance(r, dict)]
    if not recs:
        return 'missing'
    return max((r.get('status') for r in recs), key=lambda s: order.get(s, 0)) or 'live'


# ---------------------------------------------------------------------------
# 两端渲染
# ---------------------------------------------------------------------------
def render_wechat(blocks, sub=None, box=None, key=None):
    """微信（内联样式）渲染：由调用方注入样式函数，保持既有电子墨水风格。"""
    out = []
    for b in blocks:
        body = b['body']
        if b.get('status') in ('stale', 'missing'):
            body = f'<strong>⚠️ 本段含非当日/缺失数据，已逐项标注</strong><br/>' + body
        out.append((sub or (lambda t: t))(b['title']) + body)
    joined = '<br/><br/>'.join(out)
    return (box or (lambda t: t))(joined)


def render_web(blocks):
    """网页渲染：复用 report.html 的 .macro-* 样式类。"""
    parts = []
    for b in blocks:
        cls = 'macro-block'
        if b.get('status') == 'stale':
            cls += ' is-stale'
        elif b.get('status') == 'missing':
            cls += ' is-missing'
        parts.append(f'<div class="{cls}"><div class="macro-sub">{b["title"]}</div>'
                     f'<div class="macro-body">{b["body"]}</div></div>')
    return '\n'.join(parts)


WEB_CSS = """
    /* 02 节宏观层（macro_render.py 动态注入，与微信推送同源同口径） */
    .macro-block{background:#f8f9fa;border:1px solid #d9dce0;border-left:3px solid #007a35;
      border-radius:6px;padding:12px 14px;margin:10px 0;font-size:12.5px;line-height:1.9;color:#141414;}
    .macro-block.is-stale{border-left-color:#b26a00;background:#fffaf2;}
    .macro-block.is-missing{border-left-color:#141414;background:#f4f4f4;}
    .macro-sub{color:#007a35;font-weight:700;font-size:13px;margin-bottom:6px;}
    .macro-body span{color:#7d838b;font-size:11px;}
    .fresh-table{width:100%;border-collapse:collapse;font-size:11.5px;margin-top:6px;}
    .fresh-table th{color:#7d838b;text-align:left;padding:4px 8px;border-bottom:1px solid #d9dce0;font-weight:400;}
    .fresh-table td{padding:4px 8px;border-bottom:1px dashed #d9dce0;}
    .fresh-table tr.stale td{background:#fffaf2;}
    .fresh-table tr.missing td{background:#f4f4f4;}
    .stale-banner{background:#000;color:#39ff14;border-radius:6px;padding:10px 14px;margin:12px 0;
      font-size:12px;line-height:1.8;font-weight:700;}
"""


# ---------------------------------------------------------------------------
# 时效护栏（取代过去"先把日期改写成今天、再校验是否为今天"的恒真检查）
# ---------------------------------------------------------------------------
def freshness_report(macro, market, community, sentiment, today=None, now=None):
    """汇总所有数据层的时效状态 → {items, stale, missing, layers_stale, banner}。"""
    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    items = []

    def add(layer, name, as_of, status, age=None, limit=None, note=''):
        items.append({'layer': layer, 'name': name, 'as_of': as_of, 'status': status,
                      'age_days': age, 'max_age_days': limit, 'note': note})

    # 数据层抓取日
    for layer, data, label in (('行情', market, 'market_data.json'),
                               ('社区', community, 'community_data.json'),
                               ('宏观', macro, 'macro_data.json'),
                               ('舆情', sentiment, 'sentiment_data.json')):
        fd = data.get('fetch_date')
        if not fd:
            add(layer, label, None, 'missing', note='文件缺失或未生成')
            continue
        try:
            d = datetime.strptime(fd, '%Y-%m-%d').date()
        except ValueError:
            add(layer, label, fd, 'missing', note='fetch_date 无法解析')
            continue
        age = (today - d).days
        mode = data.get('mode')
        if age > 1:
            add(layer, label, fd, 'stale', age, 1, f'抓取日非当天（mode={mode}）')
        elif mode in ('demo', 'mock', 'offline'):
            add(layer, label, fd, 'stale', age, 1, f'数据为 {mode} 回放/演示，非实时抓取')
        else:
            add(layer, label, fd, 'live', age, 1, f'mode={mode}')

    # 宏观指标
    for key, rec in (macro.get('indicators') or {}).items():
        add('宏观指标', rec.get('name') or key, rec.get('as_of'), rec.get('status') or 'missing',
            rec.get('age_days'), rec.get('max_age_days'), rec.get('error') or '')
    # 人工项
    for key, rec in (macro.get('manual') or {}).items():
        add('人工维护项', rec.get('name') or key, rec.get('as_of'), rec.get('status') or 'missing',
            rec.get('age_days'), rec.get('max_age_days'), rec.get('note') or '')
    # 行情
    for key, q in (market.get('quotes') or {}).items():
        if q.get('last') is None:
            add('行情', q.get('name') or key, q.get('as_of'), 'missing', None, None, '抓取失败降级')
        else:
            age = None
            if q.get('as_of'):
                try:
                    age = (today - datetime.strptime(q['as_of'], '%Y-%m-%d').date()).days
                except ValueError:
                    age = None
            st = 'live' if (age is not None and age <= 7) else 'stale'
            add('行情', q.get('name') or key, q.get('as_of'), st, age, 7, q.get('source') or '')
            if q.get('tech') is None and st == 'live':
                add('技术面', f'{q.get("name") or key} 历史K线', q.get('as_of'), 'missing',
                    None, None, '无历史数据 → 不渲染技术位断言')
    # 事件日历
    cal = macro.get('events') or {}
    if cal.get('needs_update'):
        add('事件日历', 'EVENT_CALENDAR 未来观察点', cal.get('calendar_vintage'), 'stale',
            cal.get('calendar_age_days'), None, '剩余观察点不足 30 天或已用尽')

    stale = [i for i in items if i['status'] == 'stale']
    missing = [i for i in items if i['status'] == 'missing']
    return {
        'today': today.isoformat(),
        'items': items,
        'stale': stale,
        'missing': missing,
        'ok': len(items) - len(stale) - len(missing),
        'total': len(items),
        'pushable': not stale and not missing,
        'banner': (f'⚠️ 数据时效告警：{len(stale)} 项陈旧 / {len(missing)} 项缺失'
                   f'（共 {len(items)} 项）—— 已在正文逐项标注 as_of，未标注为"当日最新"'
                   if (stale or missing) else
                   f'✅ 全部 {len(items)} 项数据均在时效内（核对日 {today.isoformat()}）'),
    }


def render_freshness_wechat(rep):
    rows = ['<table style="width:100%;border-collapse:collapse;font-size:11px;">'
            '<tr><th style="text-align:left;color:#7d838b;padding:3px 6px;border-bottom:1px solid #d9dce0;">层</th>'
            '<th style="text-align:left;color:#7d838b;padding:3px 6px;border-bottom:1px solid #d9dce0;">项目</th>'
            '<th style="text-align:left;color:#7d838b;padding:3px 6px;border-bottom:1px solid #d9dce0;">数据日期</th>'
            '<th style="text-align:left;color:#7d838b;padding:3px 6px;border-bottom:1px solid #d9dce0;">龄</th>'
            '<th style="text-align:left;color:#7d838b;padding:3px 6px;border-bottom:1px solid #d9dce0;">状态</th></tr>']
    for i in rep['items']:
        color = '#141414' if i['status'] in ('stale', 'missing') else '#333'
        age = '—' if i.get('age_days') is None else f"{i['age_days']}d/上限{i.get('max_age_days', '—')}"
        rows.append(
            f'<tr><td style="padding:3px 6px;border-bottom:1px dashed #d9dce0;color:{color};">{i["layer"]}</td>'
            f'<td style="padding:3px 6px;border-bottom:1px dashed #d9dce0;color:{color};">{i["name"]}</td>'
            f'<td style="padding:3px 6px;border-bottom:1px dashed #d9dce0;color:{color};">{i["as_of"] or "—"}</td>'
            f'<td style="padding:3px 6px;border-bottom:1px dashed #d9dce0;color:{color};">{age}</td>'
            f'<td style="padding:3px 6px;border-bottom:1px dashed #d9dce0;color:{color};">'
            f'<strong>{STATUS_LABEL.get(i["status"], i["status"])}</strong></td></tr>')
    rows.append('</table>')
    return ''.join(rows)


def render_freshness_web(rep):
    rows = ['<table class="fresh-table"><tr><th>层</th><th>项目</th><th>数据日期</th>'
            '<th>龄/上限</th><th>状态</th><th>判定依据 / 来源</th></tr>']
    for i in rep['items']:
        cls = ' class="stale"' if i['status'] == 'stale' else \
              (' class="missing"' if i['status'] == 'missing' else '')
        age = '—' if i.get('age_days') is None else f"{i['age_days']}d / {i.get('max_age_days', '—')}"
        note = _esc(i.get('note') or '—')
        rows.append(f'<tr{cls}><td>{_esc(i["layer"])}</td><td>{_esc(i["name"])}</td>'
                    f'<td>{_esc(i["as_of"] or "—")}</td><td>{age}</td>'
                    f'<td><strong>{STATUS_LABEL.get(i["status"], i["status"])}</strong></td>'
                    f'<td>{note}</td></tr>')
    rows.append('</table>')
    return ''.join(rows)


# 正文里所有形如「X 月 Y 日」的绝对日期，若早于今天 N 天即视为"叙事陈旧"
NARRATIVE_DATE_RE = re.compile(r'(?<!\d)(\d{1,2}) 月 (\d{1,2}) 日')


def scan_narrative_dates(html, today=None, year=None, ignore_days=45):
    """扫描渲染后正文中的中文绝对日期，返回过期引用列表（防止再次固化）。"""
    today = today or datetime.now(timezone.utc).date()
    year = year or today.year
    found = []
    for m in NARRATIVE_DATE_RE.finditer(re.sub(r'<[^>]+>', '', html)):
        mo, dy = int(m.group(1)), int(m.group(2))
        try:
            d = date(year, mo, dy)
        except ValueError:
            continue
        if d > today + timedelta(days=1):
            d = date(year - 1, mo, dy)      # 跨年引用
        age = (today - d).days
        if age > ignore_days:
            found.append({'text': m.group(0), 'date': d.isoformat(), 'age_days': age})
    return found
