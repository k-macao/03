#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 量化策略日报 — 动态建站 (build_site.py)

读取 market_data.json + community_data.json (+ sentiment_data.json)，把 report.html 模板中的
{{占位符}} 替换为最新抓取数据，并动态注入 14 大社区最新研判与「舆情因子接入实测」区块，
同时在每个社区卡片后追加核心量化指标（实体级情感、事件分类、相关性、新颖度），
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

量化指标注入:
  - 每条社区数据可携带 quant 字段，包含 sentiment/event/relevance/novelty
  - build_community_html 会在 AI 研判后追加 quant-metrics 区块

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

import macro_render as mr   # 宏观层渲染 + 时效护栏（与 tools/wechat_push.py 共用，口径一致）

# 行情占位符规则: key -> (中文名, 小数位组)
QUOTE_KEYS = ['HSI', 'HSTECH', 'HSCE', 'SPX', 'NDQ', 'DJI', 'GOLD', 'WTI', 'BRENT', 'USDCNH', 'USDCNY']
FX_KEYS = {'USDCNH', 'USDCNY'}

MINUS = '\u2212'  # U+2212 真正的减号

COMMUNITY_LIST_BEGIN = '<!-- COMMUNITY_LIST:BEGIN -->'
COMMUNITY_LIST_END = '<!-- COMMUNITY_LIST:END -->'
SENTIMENT_LIST_BEGIN = '<!-- SENTIMENT_LIST:BEGIN -->'
SENTIMENT_LIST_END = '<!-- SENTIMENT_LIST:END -->'
MACRO_BLOCK_BEGIN = '<!-- MACRO_BLOCK:BEGIN -->'
MACRO_BLOCK_END = '<!-- MACRO_BLOCK:END -->'
FRESHNESS_BLOCK_BEGIN = '<!-- FRESHNESS_BLOCK:BEGIN -->'
FRESHNESS_BLOCK_END = '<!-- FRESHNESS_BLOCK:END -->'
VERDICT_LIST_BEGIN = '<!-- VERDICT_LIST:BEGIN -->'
VERDICT_LIST_END = '<!-- VERDICT_LIST:END -->'

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

    # 03 节筛选标签的家数由本次抓取结果实时统计（不再写死 14/6/3/3/2）
    comms = ((community_data or {}).get('communities') or [])
    counts = {'bull': 0, 'bear': 0, 'neutral': 0, 'mixed': 0}
    for c in comms:
        vc = c.get('verdict_class')
        if vc in counts:
            counts[vc] += 1
    tokens['{{FILTER_TOTAL}}'] = str(len(comms)) if comms else '\u2014'
    for _k, _v in counts.items():
        tokens['{{FILTER_%s}}' % _k.upper()] = str(_v) if comms else '\u2014'

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


def build_quant_html(quant):
    """构建核心量化指标 HTML（网页版）—— 每条新闻/社区卡片后追加"""
    if not quant:
        return ""
    sentiment = quant.get('sentiment', {})
    event = quant.get('event', {})
    relevance = quant.get('relevance', {})
    novelty = quant.get('novelty', {})

    s_display = sentiment.get('display', '—')
    s_desc = sentiment.get('desc', '由新闻对应文本片段的情绪，排除无关主体干扰')
    e_label = event.get('label', '综合')
    e_desc = event.get('desc', '精准匹配业绩、并购、监管等场景')
    r_display = relevance.get('display', '—')
    r_desc = relevance.get('desc', '衡量新闻与标的的关联程度，过滤无效噪音')
    n_display = novelty.get('display', '—')
    n_desc = novelty.get('desc', '区分新闻首发与转载，识别信息冲击强度')

    return (
        f'  <div class="quant-metrics">\n'
        f'    <div class="quant-metrics-title">◆ 核心量化指标</div>\n'
        f'    <ul class="quant-metrics-list">\n'
        f'      <li><strong>实体级情感得分：</strong>{s_display} — {s_desc}</li>\n'
        f'      <li><strong>新闻细分事件分类：</strong>{e_label} — {e_desc}</li>\n'
        f'      <li><strong>相关性得分：</strong>{r_display} — {r_desc}</li>\n'
        f'      <li><strong>新颖度得分：</strong>{n_display} — {n_desc}</li>\n'
        f'    </ul>\n'
        f'  </div>'
    )


def build_community_html(communities):
    """根据 community_data.json 生成 14 个社区的 HTML 列表，包含核心量化指标"""
    html_parts = []
    for c in communities:
        icon = c.get('icon', '📌')
        cid = c.get('id', '01')
        name = c.get('name', '未知社区')
        label = c.get('verdict_label', '中性')
        vclass = c.get('verdict_class', 'neutral')
        quote = c.get('quote', '')
        verdict = c.get('verdict', '')
        quant = c.get('quant', {})
        meta = c.get('meta', f"综合站内 10 条讨论 · 最新读取 {c.get('fetch_date','')}")
        quant_html = build_quant_html(quant)
        article = (
            f'<article class="pub-card" data-verdict="{vclass}">\n'
            f'  <div class="pub-card-head"><span class="pub-name">{icon} {cid}. {name}</span><span class="pub-chip">{label}</span></div>\n'
            f'  <p class="pub-quote"><strong>平台深度热评：</strong>{quote}</p>\n'
            f'  <div class="pub-verdict"><strong style="color:#000;">▶ AI 深度战术研判：</strong>{verdict}</div>\n'
            f'{quant_html}\n'
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
    m = re.search(r'(<div id="communityList">)(.*?)(</div>\s*<!-- 04)', template, re.S)
    if m:
        new_block = m.group(1) + "\n" + COMMUNITY_LIST_BEGIN + "\n" + community_html + "\n" + COMMUNITY_LIST_END + "\n" + m.group(3)
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
            return (f"<li><span style=\"background:#000;color:#39ff14;font-size:10px;\""
                    f"padding:1px 6px;margin-right:6px;\">{tag}</span>{esc(x.get('title') or '')}"
                    f"<span style=\"color:#7d838b;\"> · {esc(x.get('source') or '')} "
                    f"{esc(str(x.get('published_at') or ''))[:16]} · 情感 {x.get('sentiment')} · 命中 {esc(kw)}</span></li>")
        parts.append('<div class="pub-box"><div class="pub-sub">◆ 情感样本极值（可回溯：命中词与权重）</div>'
                     '<ul class="pixel-list">' + ''.join(li(x, '负面') for x in top_neg)
                     + ''.join(li(x, '正面') for x in top_pos) + '</ul></div>')

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


def _inject_between(template, begin, end, block_html, label):
    """通用标记注入；无标记则告警并原样返回（向后兼容）。"""
    if begin in template and end in template:
        pattern = re.compile(re.escape(begin) + r'.*?' + re.escape(end), re.S)
        new_html, count = pattern.subn(lambda m: f"{begin}\n{block_html}\n{end}", template)
        if count:
            print(f'  🌍 已动态注入 {label}')
            return new_html
    print(f'  ⚠️ 未找到 {label} 标记，跳过注入', file=sys.stderr)
    return template


def inject_macro(template, block_html):
    """02 节「全球经济与财经动态」——与微信推送同源（macro_render.build_blocks）。"""
    return _inject_between(template, MACRO_BLOCK_BEGIN, MACRO_BLOCK_END, block_html, '02 宏观层')


def inject_freshness(template, block_html):
    """02 节时效核对横幅 + 逐项 as_of 表（取代"正文所有时间戳均为最新"的空口承诺）。"""
    return _inject_between(template, FRESHNESS_BLOCK_BEGIN, FRESHNESS_BLOCK_END,
                           block_html, '02 时效核对表')


def inject_verdict(template, block_html):
    """07 节「核心结论」——与微信推送共用 macro_render.verdict_items()。"""
    return _inject_between(template, VERDICT_LIST_BEGIN, VERDICT_LIST_END, block_html, '07 核心结论')


def build_macro_web(macro, market, community, sentiment, now):
    """生成网页端 02 节内容：横幅 + 数据块 + 时效表。"""
    blocks = mr.build_blocks(macro, market, today=now.date())
    rep = mr.freshness_report(macro, market, community, sentiment, today=now.date(), now=now)
    banner = ('' if rep['pushable'] else f'<div class="stale-banner">{rep["banner"]}</div>')
    body = banner + mr.render_web(blocks)
    fresh = (f'<div class="macro-block"><div class="macro-sub">◆ 数据时效核对（逐项 as_of · 核对日 {rep["today"]}）</div>'
             f'<div class="macro-body">{rep["banner"]}{mr.render_freshness_web(rep)}<br/>'
             f'<span>陈旧/缺失项已在上方正文逐条标注；本页面与微信推送由同一份 macro_render 渲染，口径一致。</span>'
             f'</div></div>')
    return body, fresh, rep


def main():
    ap = argparse.ArgumentParser(description='章鱼 AI — 动态建站（行情+社区+舆情+宏观四动态+量化指标）')
    ap.add_argument('--data', default='market_data.json', help='行情数据 JSON 路径')
    ap.add_argument('--community', default='community_data.json', help='社区数据 JSON 路径')
    ap.add_argument('--sentiment', default='sentiment_data.json',
                    help='舆情因子数据 JSON 路径（sentiment_factors.py 生成）')
    ap.add_argument('--macro', default='macro_data.json',
                    help='宏观数据 JSON 路径（macro_data.py 生成，02 节数据源）')
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

    macro_data = {}
    if os.path.exists(args.macro):
        try:
            with open(args.macro, encoding='utf-8') as f:
                macro_data = json.load(f)
        except ValueError as e:
            print(f'警告: {args.macro} 解析失败({e})，02 节宏观层将全部显示「未取到」', file=sys.stderr)
    else:
        print(f'警告: 未找到 {args.macro}，02 节宏观层将显示「未取到」而非旧数据；'
              f'请先运行 python3 macro_data.py（离线可用 --mock）', file=sys.stderr)

    now = datetime.now(timezone.utc)
    tokens = build_tokens(data, now, community_data, sentiment_data)

    if community_data and community_data.get('communities'):
        community_html = build_community_html(community_data['communities'])
        template = inject_community_list(template, community_html)
    else:
        print('  ℹ️ 社区数据为空，跳过动态注入，保留模板原有社区内容')

    template = inject_sentiment(template, build_sentiment_html(sentiment_data))

    # ---------- 02 节宏观层（网页与微信推送同源渲染） ----------
    macro_body, freshness_body, fresh_rep = build_macro_web(
        macro_data, data, community_data, sentiment_data, now)
    template = inject_freshness(template, freshness_body)
    template = inject_macro(template, macro_body)
    template = inject_verdict(template, mr.render_verdict_web(
        mr.verdict_items(macro_data, data, sentiment_data, today=now.date())))
    print(f'  📊 数据时效: {fresh_rep["banner"]}')

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
