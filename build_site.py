#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 量化策略日报 — 动态建站 (build_site.py)

读取 market_data.json + community_data.json (+ sentiment_data.json)，把 report.html 模板中的
{{占位符}} 替换为最新抓取数据，并动态注入 14 大社区最新研判与「舆情因子接入实测」区块，
生成最终 report.html（页面源文件，供 GitHub Pages 部署与 wechat_push.py 内嵌）。

占位符规则:
  {{TS_FULL}}             构建时间戳（秒级 UTC）
  {{QUOTE_DATE_CN}}       恒指最新行情日期，如 "8 月 28 日"
  {{HSI_LAST}} {{HSI_CHG}} {{HSI_PCT}} {{HSI_ASOF}}   各行情标的（见 market_data.py）
  {{GOLD_LAST}} {{WTI_LAST}} {{BRENT_LAST}} …         同上，全量标的
  {{CD_01}} .. {{CD_14}}  14 大社区「最新读取」日期（取抓取日，即当天）
  {{FETCH_STATUS}}        数据源同步状态文案
  {{COMMUNITY_FETCH_STATUS}}  社区抓取状态文案

社区动态注入:
  - 若存在 community_data.json，则解析其中 14 条社区数据，生成最新社区 HTML 列表，
    替换模板中 <!-- COMMUNITY_LIST:BEGIN --> ... <!-- COMMUNITY_LIST:END --> 之间的内容
  - 若不存在，则保留模板原有静态社区内容（仅日期占位符会被刷新），保证向后兼容

用法:
  python3 market_data.py && python3 community_data.py && python3 build_site.py   # 常规构建（行情+社区动态）
  python3 build_site.py --check                        # 只校验占位符是否齐全，不写文件
  python3 build_site.py --data market_data.json --community community_data.json --out report.html

注意: 仓库中 report.html 始终保持「模板版本」（含 {{占位符}}）；构建产物不提交。
      若本地误提交了构建产物，构建会明确报错，恢复: git checkout -- report.html
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

# 行情占位符规则: key -> (中文名, 小数位组)
QUOTE_KEYS = ['HSI', 'HSTECH', 'HSCE', 'SPX', 'NDQ', 'DJI', 'GOLD', 'WTI', 'BRENT', 'USDCNH', 'USDCNY']
FX_KEYS = {'USDCNH', 'USDCNY'}

MINUS = '\u2212'  # U+2212 真正的减号

COMMUNITY_LIST_BEGIN = '<!-- COMMUNITY_LIST:BEGIN -->'
COMMUNITY_LIST_END = '<!-- COMMUNITY_LIST:END -->'
SENTIMENT_LIST_BEGIN = '<!-- SENTIMENT_LIST:BEGIN -->'
SENTIMENT_LIST_END = '<!-- SENTIMENT_LIST:END -->'

def fmt_last(q, nd=None):
    """最新价 → "25,440.17"；缺失 → "—"。GOLD 且 >=1000 时取整数。"""
    if not q or q.get('last') is None:
        return '\u2014'
    v = float(q['last'])
    if nd is None:
        nd = q.get('decimals') or 2
    if q.get('name') == '现货黄金' and v >= 1000:
        nd = 0
    return f'{v:,.{nd}f}'


def fmt_chg(q):
    """涨跌额 → "+212.65" / "−212.65"；缺失 → "—"。"""
    if not q or q.get('chg') is None:
        return '\u2014'
    v = float(q['chg'])
    sign = MINUS if v < 0 else '+'
    nd = q.get('decimals') or 2
    return f'{sign}{abs(v):,.{nd}f}'


def fmt_pct(q):
    """涨跌幅 → "+0.25%" / "−0.83%"；缺失 → "—"。"""
    if not q or q.get('pct') is None:
        return '\u2014'
    v = float(q['pct'])
    sign = MINUS if v < 0 else '+'
    return f'{sign}{abs(v):,.2f}%'


def fmt_asof(q):
    """行情日期 → "2026-08-28"；缺失 → "—"。"""
    return (q.get('as_of') or '\u2014') if q else '\u2014'


def quote_date_cn(q):
    """恒指行情日期 → "8 月 28 日"；缺失 → "最新交易日"。"""
    a = (q or {}).get('as_of') or ''
    m = re.match(r'20\d{2}-(\d{2})-(\d{2})', a)
    if not m:
        return '最新交易日'
    return f'{int(m.group(1))} 月 {int(m.group(2))} 日'


def build_tokens(data, now, community_data=None, sentiment_data=None):
    quotes = (data or {}).get('quotes') or {}
    tokens = {}
    for k in QUOTE_KEYS:
        q = quotes.get(k)
        tokens[f'{{{{{k}_LAST}}}}'] = fmt_last(q)
        tokens[f'{{{{{k}_CHG}}}}'] = fmt_chg(q)
        tokens[f'{{{{{k}_PCT}}}}'] = fmt_pct(q)
        tokens[f'{{{{{k}_ASOF}}}}'] = fmt_asof(q)

    tokens['{{TS_FULL}}'] = now.strftime('%Y-%m-%d %H:%M:%S UTC')
    tokens['{{FETCH_DATE}}'] = data.get('fetch_date', now.strftime('%Y-%m-%d'))
    tokens['{{QUOTE_DATE_CN}}'] = quote_date_cn(quotes.get('HSI'))
    tokens['{{HSI_CHG_DESC}}'] = _chg_desc(quotes.get('HSI'))

    # 14 大社区「最新读取」日期 = 社区抓取日（若有社区数据则取社区的 fetch_date，否则取行情的 fetch_date）
    if community_data and community_data.get('fetch_date'):
        cd = community_data.get('fetch_date')
    else:
        cd = tokens['{{FETCH_DATE}}']
    for i in range(1, 15):
        tokens[f'{{{{CD_{i:02d}}}}}'] = cd

    tokens['{{FETCH_STATUS}}'] = _fetch_status(data)
    tokens['{{COMMUNITY_FETCH_STATUS}}'] = _community_fetch_status(community_data)
    tokens.update(_sentiment_tokens(sentiment_data, tokens['{{FETCH_DATE}}']))
    return tokens


def _sentiment_tokens(s, fallback_date):
    """03B 节舆情因子占位符（数据缺失一律降级为 "—"，不阻断构建）。"""
    m = (s or {}).get('market') or {}
    sm = (s or {}).get('summary') or {}

    def num(v, nd=2, suffix=''):
        try:
            return f'{float(v):,.{nd}f}{suffix}'
        except (TypeError, ValueError):
            return '\u2014'

    def signed(v, nd=3, suffix=''):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return '\u2014'
        return f'{MINUS if v < 0 else "+"}{abs(v):,.{nd}f}{suffix}'

    return {
        '{{SENT_TEMP}}': num(m.get('sent_temp'), 1),
        '{{SENT_LABEL}}': m.get('label') or '\u2014',
        '{{SENT_NET}}': signed(m.get('net_senti')),
        '{{SENT_NEG}}': num(m.get('neg_share'), 1, '%'),
        '{{SENT_NEWS}}': num(m.get('news_count'), 0),
        '{{SENT_HEATZ}}': signed(m.get('heat_z'), 2, 'σ'),
        '{{SENT_RISK}}': num(m.get('risk_score'), 0),
        '{{SENT_DATE}}': (s or {}).get('fetch_date') or fallback_date,
        '{{SENT_MODE}}': {'live': '联网实测', 'mock': '离线回放（fixtures）',
                          'off': '断网兜底', 'offline': '断网兜底'}.get((s or {}).get('mode'), '未生成'),
        '{{SENT_NATIVE}}': num(m.get('platform_native'), 0),
        '{{SENT_SOURCE_STATUS}}': (f"{sm.get('ok')}/{sm.get('total')} 个平台接口可用"
                                   if sm.get('total') else '舆情因子数据未生成'),
        '{{SENT_STATUS}}': _sentiment_status(s),
    }


def _sentiment_status(s):
    if not s:
        return ('未找到 sentiment_data.json —— 运行 <code>python3 sentiment_factors.py --live</code>'
                '（境内出口 + 凭据）或 <code>--mock</code>（离线回放）后重建即可注入本节点')
    sm = s.get('summary') or {}
    ok, total, failed = sm.get('ok'), sm.get('total'), sm.get('failed') or []
    gen = s.get('generated_at') or ''
    txt = f'舆情/新闻因子接口 {ok}/{total} 可用 · 生成于 {gen}'
    if failed:
        txt += f' · 降级源：{"、".join(failed)}'
    if (s.get('market') or {}).get('degraded'):
        txt += ' · 本次为降级结果（因子数值未刷新，已标注）'
    return txt


def _chg_desc(q):
    """恒指涨跌描述 → "跌 212.65 点" / "涨 15.20 点"；缺失 → "涨跌数据暂缺"。"""
    if not q or q.get('chg') is None:
        return '涨跌数据暂缺'
    v = float(q['chg'])
    verb = '跌' if v < 0 else '涨'
    nd = q.get('decimals') or 2
    return f'{verb} {abs(v):,.{nd}f} 点'


def _fetch_status(data):
    summary = (data or {}).get('summary') or {}
    ok, total, failed = summary.get('ok'), summary.get('total'), summary.get('failed') or []
    gen = (data or {}).get('generated_at') or ''
    if ok is None:
        return f'未找到 market_data.json，请先运行 python3 market_data.py（抓取于 {gen}）'
    if total == ok:
        return f'{ok}/{total} 项行情源全部同步成功 · 抓取于 {gen}'
    names = '、'.join(failed)
    return f'{ok}/{total} 项同步成功，{names} 暂缺（源不可达，已降级显示 —）· 抓取于 {gen}'


def _community_fetch_status(cdata):
    if not cdata:
        return '未找到 community_data.json，请先运行 python3 community_data.py（社区数据将基于模板回退）'
    summary = cdata.get('summary') or {}
    ok, total, failed = summary.get('ok'), summary.get('total'), summary.get('failed') or []
    gen = cdata.get('generated_at') or ''
    fetch_date = cdata.get('fetch_date') or ''
    if ok is None:
        return f'社区数据已生成 · 抓取于 {gen} · 抓取日期 {fetch_date}'
    if total == ok:
        return f'{ok}/{total} 个社区源全部同步成功 · 抓取于 {gen} · 抓取日期 {fetch_date}'
    names = '、'.join(failed)
    return f'{ok}/{total} 个社区同步成功，{names} 降级为动态模板 · 抓取于 {gen} · 抓取日期 {fetch_date}'


def substitute(template, tokens):
    out = template
    for token, value in tokens.items():
        out = out.replace(token, value)
    return out


def find_leftovers(html):
    return sorted(set(re.findall(r'\{\{\s*[A-Za-z0-9_]+\s*\}\}', html)))


def build_community_html(communities):
    """根据 community_data.json 生成 14 个社区的 HTML 列表"""
    html_parts = []
    for c in communities:
        # 防御：确保必要字段存在
        icon = c.get('icon', '📌')
        cid = c.get('id', '01')
        name = c.get('name', '未知社区')
        label = c.get('verdict_label', '中性')
        vclass = c.get('verdict_class', 'neutral')
        quote = c.get('quote', '')
        verdict = c.get('verdict', '')
        meta = c.get('meta', f"综合站内 10 条讨论 · 最新读取 {c.get('fetch_date','')}")
        # 转义？内容已是纯文本，保留 HTML 安全
        # 构造 article
        article = (
            f'<article class="pub-card" data-verdict="{vclass}">\n'
            f'  <div class="pub-card-head"><span class="pub-name">{icon} {cid}. {name}</span><span class="pub-chip">{label}</span></div>\n'
            f'  <p class="pub-quote"><strong>平台深度热评：</strong>{quote}</p>\n'
            f'  <div class="pub-verdict"><strong style="color:#000;">▶ AI 深度战术研判：</strong>{verdict}</div>\n'
            f'  <div class="pub-meta">{meta}</div>\n'
            f'</article>'
        )
        html_parts.append(article)
    return "\n".join(html_parts)


def inject_community_list(template, community_html):
    """将社区 HTML 注入到模板的 COMMUNITY_LIST 标记之间"""
    if COMMUNITY_LIST_BEGIN in template and COMMUNITY_LIST_END in template:
        pattern = re.compile(re.escape(COMMUNITY_LIST_BEGIN) + r'.*?' + re.escape(COMMUNITY_LIST_END), re.S)
        replacement = f"{COMMUNITY_LIST_BEGIN}\n{community_html}\n{COMMUNITY_LIST_END}"
        new_html, count = pattern.subn(replacement, template)
        if count:
            print(f'  🧩 已动态注入 {community_html.count("<article")} 个社区卡片（标记替换）')
            return new_html
    # 兼容旧模板：尝试替换 <div id="communityList">...</div> 的内容
    # 使用非贪婪匹配到下一个 <!-- 04 -->
    m = re.search(r'(<div id="communityList">)(.*?)(</div>\s*<!-- 04)', template, re.S)
    if m:
        new_block = m.group(1) + "\n" + COMMUNITY_LIST_BEGIN + "\n" + community_html + "\n" + COMMUNITY_LIST_END + "\n" + m.group(3)
        # 只替换第一次
        new_html = template[:m.start()] + new_block + template[m.end():]
        print(f'  🧩 已动态注入 {community_html.count("<article")} 个社区卡片（兼容旧模板）')
        return new_html
    print('  ⚠️ 未找到社区列表标记，跳过动态注入（将保留模板原有社区内容）', file=sys.stderr)
    return template


def build_sentiment_html(s):
    """03B / 舆情因子接入实测节点（温度计 + 平台评测矩阵 + 个股热度 + 风险事件 + 取数明细）。"""
    esc = _esc
    if not s:
        return ('<div class="pub-box"><div class="pub-sub">◆ 舆情 / 新闻因子接口尚未接入</div>'
                '本节点由 <code>sentiment_factors.py</code> 动态注入：'
                '<code>python3 sentiment_factors.py --live</code>（境内出口 + 凭据）实测取数，'
                '或 <code>python3 sentiment_factors.py --mock</code> 用录制报文离线回放。'
                '<div class="pub-meta">接入评测与打分由 <code>tools/probe_sentiment_apis.py</code> 生成，'
                '结论详见 <code>docs/sentiment-api-eval.md</code>。</div></div>')

    m = s.get('market') or {}
    sm = s.get('summary') or {}
    parts = []

    # 1) 因子卡片
    def card(title, val, desc):
        return (f'<div class="stat-card"><div class="stat-title">{esc(title)}</div>'
                f'<div class="stat-val">{val}</div><div class="stat-desc">{desc}</div></div>')

    cards = [
        card('市场舆情温度计 SENT_TEMP', f"{m.get('sent_temp', '—')} <span style=\"font-size:12px\">{esc(m.get('label') or '')}</span>",
             '净情感 ±35 分 · 热度异动 ±12 分 · 负面占比最多扣 18 分；&gt;65 亢奋、&lt;35 恐慌'),
        card('净情感强度 NET_SENTI', _f2(m.get('net_senti'), '+.3f'),
             f"负面占比 {_f2(m.get('neg_share'), '.1f')}% · 正面 {_f2(m.get('pos_share'), '.1f')}%"),
        card('新闻热度 Z 值 NEWS_HEAT_Z', _f2(m.get('heat_z'), '+.2f') + ' σ',
             f"本次关联新闻 {m.get('news_count', 0)} 条（对比近 20 日均值）"),
        card('突发事件风险分 EVENT_RISK', _f2(m.get('risk_score'), '.0f'),
             '监管/诉讼/违约/退市/减持等高风险词加权命中，单日取最大值'),
        card('接口可用性', f"{sm.get('ok', '—')}/{sm.get('total', '—')}",
             f"模式：{esc(s.get('mode_note') or '')[:44]}"),
        card('平台现成因子占比', f"{m.get('platform_native', 0)} / {m.get('news_count', 0)}",
             '带 sentiment 字段者直接采用平台口径（米筐/优矿），其余由自建词库打分'),
    ]
    parts.append('<div class="stat-grid">' + ''.join(cards) + '</div>')

    # 2) 平台接口评测矩阵
    ev = s.get('api_eval') or {}
    if ev.get('ranking'):
        rows = []
        for r in ev['ranking']:
            rows.append(f"<tr><td>{esc(r.get('platform', ''))}</td>"
                        f"<td><code>{esc(r.get('id', ''))}</code> "
                        f"{esc(r.get('name') or '')}</td>"
                        f"<td>{esc(r.get('verdict_label', ''))}</td>"
                        f"<td class=\"q-pct\">{r.get('score')}</td></tr>")
        parts.append(
            '<div class="pub-box"><div class="pub-sub">◆ 量化平台现成舆情 / 新闻因子接入评测</div>'
            f'<div style="font-size:11.5px;color:#333;margin-bottom:6px;">评测生成于 '
            f'{esc(ev.get("generated_at") or "—")} · 模式 '
            f'{esc("联网实测" if ev.get("mode") == "live" else "文档基线（离线回放，未实测连通性与权限）")}'
            ' · 9 阶段：依赖 → 网络 → 鉴权 → 取数 → 字段 → 时效 → 覆盖 → 延迟 → 额度</div>'
            '<table class="quote-table"><tr><th>平台</th><th>接口</th><th>判定</th><th>评分</th></tr>'
            + ''.join(rows) + '</table>'
            + ('<ul class="pixel-list">' + ''.join(
                f'<li>{esc(line)}</li>' for line in (ev.get('conclusion') or [])[:6]) + '</ul>')
            + '<div class="pub-meta">完整能力矩阵、阶段明细与上线方案见 <code>docs/sentiment-api-eval.md</code>'
              '（由 <code>tools/probe_sentiment_apis.py</code> 生成）。</div></div>')

    # 3) 个股舆情热度榜
    stocks = (s.get('stocks') or [])[:8]
    if stocks:
        rows = []
        for st in stocks:
            heat = st.get('heat')
            rows.append(f"<tr><td>{esc(st.get('symbol', ''))} {esc(st.get('name') or '')}</td>"
                        f"<td>{'—' if heat is None else format(float(heat), ',.0f')}</td>"
                        f"<td class=\"q-pct\">{st.get('heat_z')}</td>"
                        f"<td>{st.get('net_senti')}</td>"
                        f"<td>{st.get('news_count')}</td>"
                        f"<td>{st.get('risk_score')}</td></tr>")
        parts.append(
            '<div class="pub-box"><div class="pub-sub">◆ 个股舆情热度与情感（关注度因子 + 情感因子）</div>'
            '<table class="quote-table"><tr><th>标的</th><th>关注指数</th><th>热度 Z</th>'
            '<th>净情感</th><th>新闻数</th><th>风险分</th></tr>' + ''.join(rows) + '</table>'
            '<div class="pub-meta">关注指数来自东财千股千评（小时/日频热度类因子，无极性）；'
            '净情感来自平台原生字段或自建词库打分。</div></div>')

    # 4) 突发风险事件 + 高信噪情感样本
    events = (m.get('events') or [])[:5]
    if events:
        lis = ''.join(
            f"<li><strong>{esc(e.get('title') or '')[:60]}</strong> — 命中 "
            f"{esc('、'.join(e.get('terms') or []))} · 风险分 {e.get('risk_score')}"
            f"{' · ' + esc(str(e.get('published_at'))[:16]) if e.get('published_at') else ''}</li>"
            for e in events)
        parts.append('<div class="pub-box"><div class="pub-sub">◆ 舆情风险事件（EVENT_RISK 命中明细）</div>'
                     f'<ul class="pixel-list">{lis}</ul></div>')
    top_neg = (m.get('top_negative') or [])[:2]
    top_pos = (m.get('top_positive') or [])[:2]
    if top_neg or top_pos:
        def li(x, tag):
            hits = (x.get('hits') or {})
            kw = '、'.join((hits.get('neg') or [])[:3] + (hits.get('pos') or [])[:3])
            return (f"<li><span style=\"background:#000;color:#39ff14;font-size:10px;"
                    f"padding:1px 6px;margin-right:6px;\">{tag}</span>{esc(x.get('title') or '')}"
                    f"<span style=\"color:#7d838b;\"> · {esc(x.get('source') or '')} "
                    f"{esc(str(x.get('published_at') or ''))[:16]} · 情感 {x.get('sentiment')} · 命中 {esc(kw)}</span></li>")
        parts.append('<div class="pub-box"><div class="pub-sub">◆ 情感样本极值（可回溯：命中词与权重）</div>'
                     '<ul class="pixel-list">' + ''.join(li(x, '负面') for x in top_neg)
                     + ''.join(li(x, '正面') for x in top_pos) + '</ul></div>')

    # 5) 各源取数明细
    srcs = s.get('sources') or []
    if srcs:
        rows = []
        for r in srcs:
            ok = '✅' if r.get('ok') else '⚠️'
            rows.append(f"<tr><td><code>{esc(r.get('id', ''))}</code></td>"
                        f"<td>{esc(r.get('platform', ''))}</td>"
                        f"<td>{ok} {esc(reg_verdict_hint(r))}</td>"
                        f"<td>{r.get('news', 0)} / {r.get('series', 0)}</td>"
                        f"<td>{esc(r.get('latest_date') or '—')}</td>"
                        f"<td class=\"q-off\">{esc((r.get('error') or r.get('note') or '')[:60])}</td></tr>")
        parts.append(
            '<div class="pub-box"><div class="pub-sub">◆ 逐源取数明细（本次构建）</div>'
            '<table class="quote-table"><tr><th>接口</th><th>平台</th><th>状态</th>'
            '<th>新闻/序列</th><th>最新日期</th><th>说明</th></tr>' + ''.join(rows) + '</table>'
            '<div class="pub-meta">单源失败自动降级、不阻断构建与推送；失败原因如实标注在此表。</div></div>')

    # 6) 日频情绪指数序列（末 10 期）
    series = (s.get('series') or [])[-10:]
    if series:
        lis = ''.join(
            f"<li>{esc(r.get('date'))} · {esc(r.get('name'))}"
            f"（{esc(r.get('platform') or r.get('source') or '—')}）"
            f" <strong>{r.get('value')}</strong>"
            f' <span class="pub-meta">{esc(r.get("note") or "")}</span></li>'
            for r in reversed(series))
        parts.append('<div class="pub-box"><div class="pub-sub">◆ 市场级新闻情绪指数序列（平台现成因子 · 日频 · 末 10 期）</div>'
                     f'<ul class="pixel-list">{lis}</ul>'
                     '<div class="pub-meta">各平台指数口径不同（数库基期 = 1.0；优矿 sentimentIndex ∈ [-1,1]），'
                     '跨源不可直接比较；关注度类序列（东财关注指数、金十微博人气）见上表个股热度。</div></div>')
    return '\n'.join(parts)


def reg_verdict_hint(r):
    """把逐源状态压成一句短语（页面表格用）。"""
    if r.get('ok'):
        native = r.get('native_sentiment') or 0
        return f"取数成功（原生情感 {native} 条）" if native else '取数成功（文本→自建打分）'
    return '降级'


def _f2(v, fmt='.2f'):
    try:
        return format(float(v), fmt)
    except (TypeError, ValueError):
        return '\u2014'


def _esc(t):
    import html
    return html.escape(str(t if t is not None else ''), quote=False)


def inject_sentiment(template, block_html):
    """把舆情节点注入模板 SENTIMENT_LIST 标记之间（无标记则跳过，保证向后兼容）。"""
    if SENTIMENT_LIST_BEGIN in template and SENTIMENT_LIST_END in template:
        pattern = re.compile(re.escape(SENTIMENT_LIST_BEGIN) + r'.*?' + re.escape(SENTIMENT_LIST_END), re.S)
        new_html, count = pattern.subn(f"{SENTIMENT_LIST_BEGIN}\n{block_html}\n{SENTIMENT_LIST_END}", template)
        if count:
            print('  🗞️  已动态注入 03B 舆情因子节点')
            return new_html
    print('  ⚠️ 未找到 SENTIMENT_LIST 标记，跳过舆情节点注入', file=sys.stderr)
    return template


def main():
    ap = argparse.ArgumentParser(description='章鱼 AI — 动态建站（行情+社区+舆情三动态）')
    ap.add_argument('--data', default='market_data.json', help='行情数据 JSON 路径')
    ap.add_argument('--community', default='community_data.json', help='社区数据 JSON 路径')
    ap.add_argument('--sentiment', default='sentiment_data.json',
                    help='舆情因子数据 JSON 路径（sentiment_factors.py 生成）')
    ap.add_argument('--template', default='report.html', help='模板文件路径')
    ap.add_argument('--out', default='report.html', help='输出文件路径')
    ap.add_argument('--check', action='store_true', help='只校验占位符，不写文件')
    args = ap.parse_args()

    if not os.path.exists(args.template):
        print(f'错误: 找不到模板 {args.template}', file=sys.stderr)
        sys.exit(1)

    with open(args.template, encoding='utf-8') as f:
        template = f.read()

    leftovers = find_leftovers(template)
    # 允许模板没有占位符的情况？但为了防止误提交构建产物，仍需检查
    # 如果模板包含 COMMUNITY_LIST 标记但没有 {{}}，也认为是模板版本，允许
    if not leftovers and COMMUNITY_LIST_BEGIN not in template and SENTIMENT_LIST_BEGIN not in template:
        print(f'错误: {args.template} 中没有 {{占位符}}，疑似已构建过的产物。\n'
              f'仓库中的 report.html 应保持模板版本；恢复: git checkout -- report.html',
              file=sys.stderr)
        sys.exit(2)

    data = {}
    if os.path.exists(args.data):
        try:
            with open(args.data, encoding='utf-8') as f:
                data = json.load(f)
        except ValueError as e:
            print(f'警告: {args.data} 解析失败({e})，将全部按缺失处理', file=sys.stderr)
    else:
        print(f'警告: 未找到 {args.data}，行情将全部显示 "—"；请先运行 python3 market_data.py',
              file=sys.stderr)

    community_data = {}
    if os.path.exists(args.community):
        try:
            with open(args.community, encoding='utf-8') as f:
                community_data = json.load(f)
        except ValueError as e:
            print(f'警告: {args.community} 解析失败({e})，社区将回退到模板静态内容', file=sys.stderr)
    else:
        print(f'警告: 未找到 {args.community}，社区将回退到模板静态内容；请先运行 python3 community_data.py',
              file=sys.stderr)

    sentiment_data = {}
    if os.path.exists(args.sentiment):
        try:
            with open(args.sentiment, encoding='utf-8') as f:
                sentiment_data = json.load(f)
        except ValueError as e:
            print(f'警告: {args.sentiment} 解析失败({e})，舆情因子节点显示降级说明', file=sys.stderr)
    else:
        print('提示: 未找到 sentiment_data.json，03B 舆情因子节点显示降级说明；'
              '可先运行 python3 sentiment_factors.py --mock 生成', file=sys.stderr)

    now = datetime.now(timezone.utc)
    tokens = build_tokens(data, now, community_data, sentiment_data)

    # 先处理占位符替换
    # 但如果模板中包含社区列表标记，我们先注入社区 HTML，再替换占位符（社区 HTML 中可能也包含 {{}}？不会，但为了安全先注入后替换）
    if community_data and community_data.get('communities'):
        community_html = build_community_html(community_data['communities'])
        template = inject_community_list(template, community_html)
    else:
        print('  ℹ️ 社区数据为空，跳过动态注入，保留模板原有社区内容')

    # 03B 舆情因子节点：无论有无数据都注入（缺数据时注入降级说明，避免旧内容残留）
    template = inject_sentiment(template, build_sentiment_html(sentiment_data))

    missing = sorted(set(find_leftovers(template)) - set(tokens))
    if missing:
        missing_str = ", ".join(missing)
        print(f'错误: 模板中存在未定义的占位符: {missing_str}', file=sys.stderr)
        sys.exit(3)

    built = substitute(template, tokens)
    leftover_after = find_leftovers(built)
    if leftover_after:
        leftover_str = ", ".join(leftover_after)
        print(f'错误: 替换后仍有残留占位符: {leftover_str}', file=sys.stderr)
        sys.exit(4)

    if args.check:
        print(f'✔ 校验通过: {len(tokens)} 个占位符均可解析，无残留。')
        if community_data:
            comm_count = len(community_data.get("communities", []))
            print(f'  社区: {comm_count} 个源已加载')
        return

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(built)
    replaced = sum(template.count(t) for t in tokens)
    ts_full_token = tokens["{{TS_FULL}}"]
    fetch_status_token = tokens["{{FETCH_STATUS}}"]
    community_status_token = tokens["{{COMMUNITY_FETCH_STATUS}}"]
    print(f'🏗️  已构建: {args.template} → {args.out} '
          f'(替换 {replaced} 处占位符 · {ts_full_token})')
    print(f'   行情状态: {fetch_status_token}')
    print(f'   社区状态: {community_status_token}')
    print(f"   舆情状态: {tokens.get('{{SENT_SOURCE_STATUS}}')} · 温度计 {tokens.get('{{SENT_TEMP}}')}"
          f"（{tokens.get('{{SENT_LABEL}}')}）· {tokens.get('{{SENT_MODE}}')}")


if __name__ == '__main__':
    main()
