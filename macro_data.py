#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 量化策略日报 — 动态宏观抓取 (macro_data.py)

存在理由（务必阅读）:
  02 节「全球经济与财经动态 (Global Macro & HK Battlefield)」过去是 **纯字符串字面量**，
  IMF / FOMC / CPI / 非农 / 南向 / 铜锂 / 大行目标价全部写死在 tools/wechat_push.py 里，
  只有 11 个行情报价会刷新 —— 于是每天推送都在重复 7–8 月的旧叙事（「下一观察点：8 月 19 日
  纪要、8 月 27–28 日杰克逊霍尔」这种早已过去的日程也被当成"未来"发出去）。
  本模块把宏观层变成 **和行情层同级的动态数据源**：每项指标都带
  `value / as_of / source / age_days / status`，取不到就是 missing，绝不编造、绝不冒充当天。

指标与来源（全部免密钥、纯标准库 urllib）:
  fed_rate        联邦基金目标区间     FRED DFEDTARL / DFEDTARU   （日频，含"自 X 日起未调整"）
  us_cpi          美国 CPI 同比        FRED CPIAUCSL              （月频，最新月 + 前值）
  us_core_cpi     美国核心 CPI 同比    FRED CPILFESL              （月频）
  us_nfp          美国非农新增         FRED PAYEMS                （月频，环比千人）
  us10y           美债 10 年期收益率   FRED DGS10                 （日频）
  copper          铜价（世行口径）     FRED PCOPPUSDM             （月频，美元/吨 + 同比）
  cn_cpi          中国 CPI 同比        东方财富数据中心 RPT_ECONOMY_CPI        （月频）
  hk_connect      港股通成交/持股      东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY （日频）
  world_growth    全球实际 GDP 增速    世界银行 API (WLD, NY.GDP.MKTP.KD.ZG)   （年频）
  events          事件日历             EVENT_CALENDAR 静态表 + 按当日动态推导"下一观察点"

人工维护项（无免费公开接口，但 **必须带 vintage 日期**，超期自动告警，不再冒充实时）:
  macro_manual_inputs.json → imf_weo / lithium_carbonate / bank_targets

诚实性约定:
  • 交易所自 2024-08 起不再公布港股通单日净买入额（NET_DEAL_AMT 返回 null），
    本模块只报成交额与持股市值，并在 notes 中明确说明，不再引用"南向净买入 XXX 亿"。
  • 任何取不到的指标 status='missing'，正文对应句子直接不渲染（宁缺勿假）。

用法:
  python3 macro_data.py                     # 联网抓取 → macro_data.json
  python3 macro_data.py --mock              # 离线回放 tests/fixtures/MACRO_*（CI 兜底）
  python3 macro_data.py --demo              # 写入一组演示值（本地联调，明确标记 demo）
  python3 macro_data.py --offline           # 断网兜底：读旧 JSON 只刷时间戳
  python3 macro_data.py --timeout 8 --json out.json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
MANUAL_INPUTS_FILE = os.path.join(REPO_ROOT, 'macro_manual_inputs.json')
FIXTURE_DIR = os.path.join(REPO_ROOT, 'tests', 'fixtures')

FRED_CSV = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={cosd}'
EM_DATACENTER = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
WB_GDP = ('https://api.worldbank.org/v2/country/WLD/indicator/'
          'NY.GDP.MKTP.KD.ZG?format=json&per_page=8&date={d1}:{d2}')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

# 时效上限（天）：超过即判 stale，正文自动打「⚠️ 数据陈旧」标签，绝不冒充当天
MAX_AGE_DAYS = {
    'daily': 7,       # 日频（利率、收益率、港股通）—— 含周末/假日容差
    'monthly': 45,    # 月频（CPI、非农、铜）—— 官方公布本身滞后约 2–4 周
    'annual': 400,    # 年频（世行全球增速）
    'event': 0,       # 事件日历：只允许"未来"，过去的日程一律不得作为"下一观察点"
}

# ---------------------------------------------------------------------------
# 事件日历（官方公布的日程属于"日历"而非"行情"，静态表 + 动态推导下一观察点）
# vintage: 2026 年 FOMC 日程（federalreserve.gov 公布，8 次会议）
# 表内没有未来事件时，next_events() 会返回 empty 并由护栏告警"日历需更新"
# ---------------------------------------------------------------------------
EVENT_CALENDAR = {
    'vintage': '2026-01-01',
    'source': 'Federal Reserve 官方 FOMC 日程（2026 年 8 次例会）',
    'events': [
        {'date': '2026-01-28', 'name': 'FOMC 利率决议（1 月 27–28 日）', 'kind': 'fomc', 'sep': False},
        {'date': '2026-03-18', 'name': 'FOMC 利率决议 + SEP 点阵图（3 月 17–18 日）', 'kind': 'fomc', 'sep': True},
        {'date': '2026-04-29', 'name': 'FOMC 利率决议（4 月 28–29 日）', 'kind': 'fomc', 'sep': False},
        {'date': '2026-06-17', 'name': 'FOMC 利率决议 + SEP 点阵图（6 月 16–17 日）', 'kind': 'fomc', 'sep': True},
        {'date': '2026-07-29', 'name': 'FOMC 利率决议（7 月 28–29 日）', 'kind': 'fomc', 'sep': False},
        {'date': '2026-09-16', 'name': 'FOMC 利率决议 + SEP 点阵图（9 月 15–16 日）', 'kind': 'fomc', 'sep': True},
        {'date': '2026-10-28', 'name': 'FOMC 利率决议（10 月 27–28 日）', 'kind': 'fomc', 'sep': False},
        {'date': '2026-12-09', 'name': 'FOMC 利率决议 + SEP 点阵图（12 月 8–9 日）', 'kind': 'fomc', 'sep': True},
    ],
}

# ---------------------------------------------------------------------------
# HTTP（可注入 getter，便于离线单测）
# ---------------------------------------------------------------------------
def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


FIXTURE_MAP = [
    (r'id=DFEDTARU', 'MACRO_FRED_DFEDTARU.csv'),
    (r'id=DFEDTARL', 'MACRO_FRED_DFEDTARL.csv'),
    (r'id=CPIAUCSL', 'MACRO_FRED_CPIAUCSL.csv'),
    (r'id=CPILFESL', 'MACRO_FRED_CPILFESL.csv'),
    (r'id=PAYEMS', 'MACRO_FRED_PAYEMS.csv'),
    (r'id=DGS10', 'MACRO_FRED_DGS10.csv'),
    (r'id=PCOPPUSDM', 'MACRO_FRED_PCOPPUSDM.csv'),
    (r'reportName=RPT_ECONOMY_CPI', 'MACRO_EM_CPI.json'),
    (r'reportName=RPT_MUTUAL_DEAL_HISTORY', 'MACRO_EM_HKCONNECT.json'),
    (r'api\.worldbank\.org', 'MACRO_WB.json'),
]


def mock_get(url, timeout=10):
    """离线回放：按 URL 特征匹配 tests/fixtures/MACRO_*。"""
    for pattern, fname in FIXTURE_MAP:
        if re.search(pattern, url):
            path = os.path.join(FIXTURE_DIR, fname)
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    return f.read()
            raise OSError(f'缺少 fixture: {fname}')
    raise OSError(f'mock 模式未覆盖该 URL: {url}')


# ---------------------------------------------------------------------------
# 解析工具
# ---------------------------------------------------------------------------
def _today(now=None):
    return (now or datetime.now(timezone.utc)).date()


def _age_days(as_of, today, freq=None):
    """as_of('YYYY-MM-DD' 或 date) 距今天数；解析失败返回 None。

    月频/年频数据的 as_of 是"观测期起点"（如 2026-08-01 代表整个 8 月），
    直接按起点算天数会把正常公布节奏误判为陈旧，因此对 monthly 按 **观测期最后一天** 计算，
    annual 按年末计算。日频不变。
    """
    if not as_of:
        return None
    if isinstance(as_of, date):
        d = as_of
    else:
        m = re.match(r'(20\d{2})-(\d{2})-(\d{2})', str(as_of))
        if not m:
            return None
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if freq == 'monthly':
        d = _month_end(d)
    return (today - d).days


def _month_end(d):
    """返回该月最后一天（月度观测期的实际覆盖终点）。"""
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _next_month_label(as_of):
    """月频观测的下一期覆盖月份，如 '2026-08-01' → '2026 年 9 月'。"""
    m = re.match(r'(20\d{2})-(\d{2})', str(as_of))
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2)) + 1
    if mo > 12:
        y, mo = y + 1, 1
    return f'{y} 年 {mo} 月'


def parse_fred_csv(text, sid):
    """FRED CSV → [(date, float)]，自动跳过空值/'.'。"""
    out = []
    for ln in text.strip().splitlines():
        ln = ln.strip().replace('\\_', '_')
        if not ln or ln.lower().startswith('observation_date'):
            continue
        parts = ln.split(',')
        if len(parts) < 2:
            continue
        d, v = parts[0].strip(), parts[1].strip()
        if not re.match(r'20\d{2}-\d{2}-\d{2}', d) or v in ('', '.', 'NA'):
            continue
        try:
            out.append((d, float(v)))
        except ValueError:
            continue
    return out


def yoy(series, idx=-1):
    """月度序列同比：返回 (value_pct, as_of, prev_value_pct, prev_as_of) 或 None。"""
    if len(series) < 2:
        return None
    pairs = []
    for i in range(len(series) - 1, -1, -1):
        d, v = series[i]
        target_year = int(d[:4]) - 1
        base = [x for x in series if x[0][:4] == str(target_year) and x[0][5:7] == d[5:7]]
        if base:
            pct = (v / base[0][1] - 1) * 100
            pairs.append((round(pct, 3), d))
        if len(pairs) == 2:
            break
    if not pairs:
        return None
    latest = pairs[0]
    prev = pairs[1] if len(pairs) > 1 else None
    return {
        'value': latest[0], 'as_of': latest[1],
        'prev_value': prev[0] if prev else None,
        'prev_as_of': prev[1] if prev else None,
    }


# ---------------------------------------------------------------------------
# 各指标抓取器：返回 {'value','as_of','source','display','detail'} 或抛异常
# ---------------------------------------------------------------------------
def fetch_fed_rate(getter, timeout, today):
    cosd = (today - timedelta(days=500)).isoformat()
    up = parse_fred_csv(getter(FRED_CSV.format(sid='DFEDTARU', cosd=cosd), timeout), 'DFEDTARU')
    lo = parse_fred_csv(getter(FRED_CSV.format(sid='DFEDTARL', cosd=cosd), timeout), 'DFEDTARL')
    if not up or not lo:
        raise ValueError('FRED 联邦基金目标区间无有效观测')
    last_d, last_up = up[-1]
    lo_map = dict(lo)
    last_lo = lo_map.get(last_d)
    if last_lo is None:
        last_d2, last_lo = lo[-1]
    # 最近一次调整日：上限或下限发生变化的第一个观测日
    changed = None
    prev = None
    up_map = dict(up)
    for d in sorted(set(list(up_map) + list(lo_map))):
        cur = (up_map.get(d), lo_map.get(d))
        if None in cur:
            continue
        if prev is not None and cur != prev:
            changed = d
        prev = cur
    rng = f'{last_lo:.2f}% – {last_up:.2f}%'
    return {
        'value': last_up, 'as_of': last_d, 'source': 'FRED DFEDTARL/DFEDTARU',
        'display': rng,
        'detail': {
            'upper': last_up, 'lower': last_lo,
            'unchanged_since': changed,
            'unchanged_days': _age_days(changed, today) if changed else None,
        },
    }


def fetch_us_cpi(getter, timeout, today):
    cosd = (today - timedelta(days=500)).isoformat()
    s = parse_fred_csv(getter(FRED_CSV.format(sid='CPIAUCSL', cosd=cosd), timeout), 'CPIAUCSL')
    r = yoy(s)
    if not r:
        raise ValueError('FRED CPIAUCSL 不足以计算同比')
    return {
        'value': r['value'], 'as_of': r['as_of'],
        'source': 'FRED CPIAUCSL（同比自算）', 'display': f"{r['value']:.1f}%",
        'detail': {'prev_value': r.get('prev_value'), 'prev_as_of': r.get('prev_as_of')},
    }


def fetch_us_core_cpi(getter, timeout, today):
    cosd = (today - timedelta(days=500)).isoformat()
    s = parse_fred_csv(getter(FRED_CSV.format(sid='CPILFESL', cosd=cosd), timeout), 'CPILFESL')
    r = yoy(s)
    if not r:
        raise ValueError('FRED CPILFESL 不足以计算同比')
    return {
        'value': r['value'], 'as_of': r['as_of'],
        'source': 'FRED CPILFESL（同比自算）', 'display': f"{r['value']:.1f}%",
        'detail': {'prev_value': r.get('prev_value'), 'prev_as_of': r.get('prev_as_of')},
    }


def fetch_us_nfp(getter, timeout, today):
    cosd = (today - timedelta(days=400)).isoformat()
    s = parse_fred_csv(getter(FRED_CSV.format(sid='PAYEMS', cosd=cosd), timeout), 'PAYEMS')
    if len(s) < 2:
        raise ValueError('FRED PAYEMS 观测不足')
    d, v = s[-1]
    pd_, pv = s[-2]
    chg = round(v - pv, 1)          # 千人
    return {
        'value': chg, 'as_of': d, 'source': 'FRED PAYEMS（环比自算，千人）',
        'display': f'{"+" if chg >= 0 else "−"}{abs(chg):,.0f} 千人',
        'detail': {'prev_chg': round(pv - s[-3][1], 1) if len(s) > 2 else None,
                   'prev_as_of': pd_, 'level': v},
    }


def fetch_us10y(getter, timeout, today):
    cosd = (today - timedelta(days=30)).isoformat()
    s = parse_fred_csv(getter(FRED_CSV.format(sid='DGS10', cosd=cosd), timeout), 'DGS10')
    if not s:
        raise ValueError('FRED DGS10 无观测')
    d, v = s[-1]
    return {'value': v, 'as_of': d, 'source': 'FRED DGS10', 'display': f'{v:.2f}%'}


def fetch_copper(getter, timeout, today):
    cosd = (today - timedelta(days=500)).isoformat()
    s = parse_fred_csv(getter(FRED_CSV.format(sid='PCOPPUSDM', cosd=cosd), timeout), 'PCOPPUSDM')
    if not s:
        raise ValueError('FRED PCOPPUSDM 无观测')
    d, v = s[-1]
    yoy_v = None
    base = [x for x in s if x[0][:4] == str(int(d[:4]) - 1) and x[0][5:7] == d[5:7]]
    if base:
        yoy_v = round((v / base[0][1] - 1) * 100, 1)
    return {
        'value': v, 'as_of': d, 'source': '世界银行 GEM 铜价（FRED PCOPPUSDM，美元/吨·月均）',
        'display': f'{v:,.0f} 美元/吨',
        'detail': {'yoy_pct': yoy_v, 'usd_per_lb': round(v / 2204.62, 2)},
    }


def fetch_cn_cpi(getter, timeout, today):
    q = urllib.parse.urlencode({
        'reportName': 'RPT_ECONOMY_CPI', 'columns': 'ALL', 'pageNumber': 1, 'pageSize': 3,
        'sortColumns': 'REPORT_DATE', 'sortTypes': -1, 'source': 'WEB', 'client': 'WEB',
    })
    data = json.loads(getter(f'{EM_DATACENTER}?{q}', timeout))
    rows = ((data.get('result') or {}).get('data')) or []
    if not rows:
        raise ValueError('东财中国 CPI 返回空')
    r0, r1 = rows[0], (rows[1] if len(rows) > 1 else {})
    as_of = str(r0.get('REPORT_DATE', ''))[:10]
    return {
        'value': r0.get('NATIONAL_SAME'), 'as_of': as_of,
        'source': '东方财富数据中心 RPT_ECONOMY_CPI（国家统计局口径）',
        'display': f"{float(r0['NATIONAL_SAME']):.1f}%",
        'detail': {
            'period': r0.get('TIME'), 'mom_pct': r0.get('NATIONAL_SEQUENTIAL'),
            'prev_value': r1.get('NATIONAL_SAME'), 'prev_period': r1.get('TIME'),
            'prev_as_of': str(r1.get('REPORT_DATE', ''))[:10] or None,
        },
    }


def fetch_hk_connect(getter, timeout, today):
    """港股通（沪 003 / 深 004）成交额与持股市值。

    注意：NET_DEAL_AMT 自 2024-08 起交易所停止公布（接口返回 null），
    因此本指标只给成交额，正文不得再写"南向净买入 XXX 亿"。
    """
    rows = []
    for mt in ('003', '004'):
        q = urllib.parse.urlencode({
            'reportName': 'RPT_MUTUAL_DEAL_HISTORY', 'columns': 'ALL', 'pageNumber': 1,
            'pageSize': 5, 'sortColumns': 'TRADE_DATE', 'sortTypes': -1,
            'source': 'WEB', 'client': 'WEB', 'filter': f'(MUTUAL_TYPE="{mt}")',
        })
        data = json.loads(getter(f'{EM_DATACENTER}?{q}', timeout))
        rows.extend(((data.get('result') or {}).get('data')) or [])
    if not rows:
        raise ValueError('东财港股通历史返回空')
    # 按 (通道, 交易日) 去重，避免重复计入
    uniq = {}
    for r in rows:
        uniq[(str(r.get('MUTUAL_TYPE')), str(r.get('TRADE_DATE', ''))[:10])] = r
    rows = list(uniq.values())
    latest = max(d for _mt, d in uniq)
    day_rows = [r for r in rows if str(r.get('TRADE_DATE', ''))[:10] == latest]
    # DEAL_AMT 单位：百元人民币 → 亿元
    turnover_yi = sum(float(r.get('DEAL_AMT') or 0) for r in day_rows) / 100.0
    hold_cap = sum(float(r.get('HOLD_MARKET_CAP') or 0) for r in day_rows)
    net_available = any(r.get('NET_DEAL_AMT') is not None for r in day_rows)
    idx = next((r.get('INDEX_CLOSE_PRICE') for r in day_rows if r.get('INDEX_CLOSE_PRICE')), None)
    idx_pct = next((r.get('INDEX_CHANGE_RATE') for r in day_rows
                    if r.get('INDEX_CHANGE_RATE') is not None), None)
    return {
        'value': round(turnover_yi, 2), 'as_of': latest,
        'source': '东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY（港股通沪 003 + 深 004）',
        'display': f'{turnover_yi:,.2f} 亿元',
        'detail': {
            'channels': len(day_rows),
            'hold_market_cap': hold_cap or None,
            'net_deal_published': net_available,
            'index_close': idx, 'index_change_pct': idx_pct,
        },
    }


def fetch_world_growth(getter, timeout, today):
    d2 = today.year + 1
    url = WB_GDP.format(d1=today.year - 4, d2=d2)
    payload = json.loads(getter(url, timeout))
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError('世界银行 API 返回异常')
    meta, rows = payload[0], payload[1] or []
    obs = [r for r in rows if r.get('value') is not None]
    if not obs:
        raise ValueError('世界银行无有效观测')
    obs.sort(key=lambda r: r['date'])
    latest = obs[-1]
    prev = obs[-2] if len(obs) > 1 else None
    return {
        'value': round(float(latest['value']), 2), 'as_of': f"{latest['date']}-12-31",
        'source': f"世界银行 WLD GDP growth（数据库更新于 {meta.get('lastupdated', '—')}）",
        'display': f"{float(latest['value']):.1f}%",
        'detail': {'year': latest['date'], 'prev_value': round(float(prev['value']), 2) if prev else None,
                   'prev_year': prev['date'] if prev else None,
                   'lastupdated': meta.get('lastupdated')},
    }


# ---------------------------------------------------------------------------
# 人工维护项 + 事件日历
# ---------------------------------------------------------------------------
def load_manual_inputs(today):
    """读取 macro_manual_inputs.json；每项必须带 as_of，超 max_age_days 判 stale。"""
    out = {}
    if not os.path.exists(MANUAL_INPUTS_FILE):
        return out, ['缺少 macro_manual_inputs.json（人工维护项全部 missing）']
    with open(MANUAL_INPUTS_FILE, encoding='utf-8') as f:
        raw = json.load(f)
    problems = []
    for k, item in (raw.get('inputs') or {}).items():
        as_of = item.get('as_of')
        age = _age_days(as_of, today, freq=item.get('age_freq'))
        limit = int(item.get('max_age_days') or 60)
        if age is None:
            status = 'missing'
            problems.append(f'人工项 {k} 缺少可解析的 as_of')
        elif age > limit:
            status = 'stale'
            problems.append(f'人工项 {k} 已 {age} 天未更新（上限 {limit} 天，as_of {as_of}）')
        else:
            status = 'manual'
        out[k] = dict(item)
        out[k].update({'key': k, 'age_days': age, 'max_age_days': limit,
                       'status': status, 'freq': 'manual'})
    return out, problems


def next_events(today, horizon_days=120):
    """从 EVENT_CALENDAR 动态推导"下一观察点"——只返回今天及以后的事件。"""
    upcoming = []
    for ev in EVENT_CALENDAR['events']:
        d = ev['date']
        age = _age_days(d, today)          # 负数 = 未来
        if age is not None and age <= 0 and -age <= horizon_days:
            upcoming.append(dict(ev, days_until=-age))
    upcoming.sort(key=lambda e: e['date'])
    return upcoming


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
INDICATORS = [
    ('fed_rate',     '联邦基金目标区间',   'daily',   fetch_fed_rate),
    ('us_cpi',       '美国 CPI 同比',      'monthly', fetch_us_cpi),
    ('us_core_cpi',  '美国核心 CPI 同比',  'monthly', fetch_us_core_cpi),
    ('us_nfp',       '美国非农新增',       'monthly', fetch_us_nfp),
    ('us10y',        '美债 10 年期',       'daily',   fetch_us10y),
    ('copper',       '铜价（世行月均）',   'monthly', fetch_copper),
    ('cn_cpi',       '中国 CPI 同比',      'monthly', fetch_cn_cpi),
    ('hk_connect',   '港股通成交额',       'daily',   fetch_hk_connect),
    ('world_growth', '全球实际 GDP 增速',  'annual',  fetch_world_growth),
]

DEMO_VALUES = {
    'fed_rate':     {'value': 3.75, 'as_of': '2026-09-15', 'display': '3.50% – 3.75%',
                     'source': 'demo', 'detail': {'upper': 3.75, 'lower': 3.5,
                                                  'unchanged_since': '2026-06-17'}},
    'us_cpi':       {'value': 3.4, 'as_of': '2026-08-01', 'display': '3.4%', 'source': 'demo',
                     'detail': {'prev_value': 3.5, 'prev_as_of': '2026-07-01'}},
    'us_core_cpi':  {'value': 2.4, 'as_of': '2026-08-01', 'display': '2.4%', 'source': 'demo',
                     'detail': {'prev_value': 2.5, 'prev_as_of': '2026-07-01'}},
    'us_nfp':       {'value': 162.0, 'as_of': '2026-08-01', 'display': '+162 千人',
                     'source': 'demo', 'detail': {'prev_chg': 21.0, 'prev_as_of': '2026-07-01'}},
    'us10y':        {'value': 4.35, 'as_of': '2026-09-15', 'display': '4.35%', 'source': 'demo'},
    'copper':       {'value': 9800.0, 'as_of': '2026-08-01', 'display': '9,800 美元/吨',
                     'source': 'demo', 'detail': {'yoy_pct': 12.0, 'usd_per_lb': 4.45}},
    'cn_cpi':       {'value': 0.8, 'as_of': '2026-08-01', 'display': '0.8%', 'source': 'demo',
                     'detail': {'period': '2026年08月份', 'prev_value': 0.5}},
    'hk_connect':   {'value': 512.3, 'as_of': '2026-09-15', 'display': '512.30 亿元',
                     'source': 'demo', 'detail': {'channels': 2, 'net_deal_published': False}},
    'world_growth': {'value': 2.9, 'as_of': '2025-12-31', 'display': '2.9%', 'source': 'demo',
                     'detail': {'year': '2025'}},
}


def build(now=None, mode='live', timeout=10, getter=None):
    today = _today(now)
    getter = getter or (mock_get if mode == 'mock' else http_get)
    indicators = {}
    failed, stale = [], []

    for key, name, freq, fn in INDICATORS:
        limit = MAX_AGE_DAYS[freq]
        rec = {'key': key, 'name': name, 'freq': freq, 'max_age_days': limit,
               'value': None, 'as_of': None, 'display': '—', 'source': None,
               'age_days': None, 'status': 'missing', 'detail': {}, 'error': None}
        try:
            if mode == 'demo':
                got = dict(DEMO_VALUES[key])
            else:
                got = fn(getter, timeout, today)
            rec.update({k: v for k, v in got.items() if k in
                        ('value', 'as_of', 'display', 'source', 'detail')})
            if mode == 'demo':
                rec['source'] = 'demo（演示值，非实时）'
            rec['age_days'] = _age_days(rec['as_of'], today, freq=freq)
            if rec['value'] is None:
                rec['status'] = 'missing'
                rec['error'] = '抓取成功但无有效数值'
                failed.append(name)
            elif rec['age_days'] is None or rec['age_days'] > limit:
                rec['status'] = 'stale'
                stale.append(f"{name}(as_of {rec['as_of']}, {rec['age_days']} 天)")
            else:
                rec['status'] = 'demo' if mode == 'demo' else 'live'
        except Exception as e:  # noqa: BLE001 - 单项失败不阻断
            rec['status'] = 'missing'
            rec['error'] = f'{type(e).__name__}: {e}'
            failed.append(name)
            print(f'  ⚠️ {name}: 抓取失败({e}) → status=missing（正文不渲染该断言）',
                  file=sys.stderr)
        if rec['status'] not in ('missing',) and freq == 'monthly' and rec.get('as_of'):
            rec['next_period_hint'] = _next_month_label(rec['as_of'])
        indicators[key] = rec
        if mode not in ('demo',):
            time.sleep(0.15)

    manual, manual_problems = load_manual_inputs(today)
    for m in manual.values():
        if m['status'] == 'stale':
            stale.append(f"{m.get('name', m['key'])}(人工项 as_of {m.get('as_of')}, {m['age_days']} 天)")
        elif m['status'] == 'missing':
            failed.append(m.get('name', m['key']))

    events = next_events(today)
    cal_age = _age_days(EVENT_CALENDAR['vintage'], today)
    events_meta = {
        'upcoming': events,
        'calendar_vintage': EVENT_CALENDAR['vintage'],
        'calendar_source': EVENT_CALENDAR['source'],
        'calendar_age_days': cal_age,
        'runway_days': (events[-1]['days_until'] if events else None),
        'needs_update': (not events) or (events[-1]['days_until'] < 30),
    }
    if events_meta['needs_update']:
        stale.append('事件日历剩余观察点不足 30 天，需更新 EVENT_CALENDAR')

    ok = sum(1 for r in indicators.values() if r['status'] in ('live', 'demo'))
    return {
        'generated_at': (now or datetime.now(timezone.utc)).strftime('%Y-%m-%d %H:%M:%S UTC'),
        'fetch_date': today.isoformat(),
        'mode': mode,
        'indicators': indicators,
        'manual': manual,
        'events': events_meta,
        'summary': {
            'ok': ok,
            'total': len(INDICATORS),
            'manual_ok': sum(1 for m in manual.values() if m['status'] == 'manual'),
            'manual_total': len(manual),
            'failed': failed,
            'stale': stale,
            'problems': manual_problems,
        },
        'notes': [
            '由 macro_data.py 每次构建/推送前抓取；每项指标均带 as_of 与 status，缺失即 missing，不编造',
            '港股通单日净买入额自 2024-08 起停止公布（接口 NET_DEAL_AMT=null），正文只引用成交额',
            '人工维护项（IMF WEO / 碳酸锂 / 大行目标价）必须带 vintage 日期，超期自动判 stale',
            '事件日历为官方日程静态表，"下一观察点"按当日动态推导，只会出现未来事件',
        ],
    }


def main():
    ap = argparse.ArgumentParser(description='章鱼 AI — 动态宏观抓取（02 节去固化）')
    ap.add_argument('--json', default=os.path.join(REPO_ROOT, 'macro_data.json'))
    ap.add_argument('--timeout', type=int, default=10)
    ap.add_argument('--mock', action='store_true', help='离线回放 tests/fixtures/MACRO_*')
    ap.add_argument('--demo', action='store_true', help='写入演示值（明确标记 demo）')
    ap.add_argument('--offline', action='store_true', help='读旧 JSON 只刷时间戳')
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    if args.offline:
        try:
            with open(args.json, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {'indicators': {}, 'manual': {}}
        data.update({'generated_at': now.strftime('%Y-%m-%d %H:%M:%S UTC'),
                     'fetch_date': now.strftime('%Y-%m-%d'), 'mode': 'offline'})
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'🌐 离线模式: 已基于旧宏观数据刷新时间戳 → {args.json}')
        return

    mode = 'demo' if args.demo else ('mock' if args.mock else 'live')
    data = build(now=now, mode=mode, timeout=args.timeout)
    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    s = data['summary']
    print(f'📦 宏观数据已写入 {args.json} '
          f'({s["ok"]}/{s["total"]} 项实时 · 人工项 {s["manual_ok"]}/{s["manual_total"]} 在期'
          + (f' · 失败: {"、".join(s["failed"])}' if s['failed'] else '')
          + (f' · 陈旧: {"、".join(s["stale"])}' if s['stale'] else '')
          + f' · 抓取日期 {data["fetch_date"]} · mode={mode})')
    if data['events']['upcoming']:
        nxt = data['events']['upcoming'][0]
        print(f'📅 下一观察点: {nxt["date"]} {nxt["name"]}（{nxt["days_until"]} 天后）')
    else:
        print('📅 事件日历已无未来观察点 —— 请更新 macro_data.py 的 EVENT_CALENDAR')
    if mode != 'live' and s['ok'] == 0:
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
