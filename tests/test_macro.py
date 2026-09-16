# -*- coding: utf-8 -*-
"""宏观层（02 节去固化）测试：macro_data → macro_render → build_site / wechat_push。

运行：python3 -m unittest discover -s tests -v      （或 python3 tests/test_macro.py）
全部离线：只用 tests/fixtures 里的录制报文（FRED CSV / 东方财富 JSON / 世界银行 JSON）。

覆盖的四条硬约束（对应用户提出的"02 节是否固化没更新"）：
  1. 数据必须来自抓取层，缺失就写"未取到"，绝不用旧值兜底；
  2. 每项断言必须带 as_of（数据所属日期）+ 来源，陈旧必须显式打"⚠️ 数据陈旧 · 截至 X"；
  3. 推送前的时效核对必须是**真**核对（旧版恒真校验已删），有问题就拦下手动推送；
  4. 网页（report.html 02 节）与微信推送由同一份 macro_render 渲染，口径一致。
"""
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import community_data as cd        # noqa: E402
import macro_data as md            # noqa: E402
import macro_render as mr          # noqa: E402

FIXTURES = os.path.join(ROOT, 'tests', 'fixtures')

# 曾经在 02/03/07 节里写死、如今必须由抓取层产出的数字/断言。
OLD_HARDCODED = [
    '628.69', '25,440.17', '25440.17', '25,124', '25,200', '25,400',
    '25,978', '25,471', '25,800', '26,000', '26,200', '26,299',
    '28,200', '31,000', '28,000–29,000', '49:51', 'RSI 72.58', '4.67%',
    '中际旭创', '南向净买入 6', '27,044', '26,500', '25,530', '4,820',
]


def read_file(relpath):
    with open(os.path.join(ROOT, relpath), encoding='utf-8') as f:
        return f.read()


def read_abs(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def read_template():
    return read_file('report.html')


def sourced_blob(macro):
    """数据源文本：渲染结果里出现这些数字是合法的（来自抓取或人工维护项）。"""
    blobs = [json.dumps(macro, ensure_ascii=False)]
    if os.path.exists(os.path.join(ROOT, 'macro_manual_inputs.json')):
        blobs.append(read_file('macro_manual_inputs.json'))
    return '\n'.join(blobs)


def forbidden_literals(macro):
    """旧写死值里凡数据源查无出处的 → 渲染结果里绝不允许出现。"""
    blob = sourced_blob(macro)
    return [lit for lit in OLD_HARDCODED if lit not in blob]


def _load_module(name, relpath):
    """按路径加载 tools/ 下的脚本模块（tools 不是包）。"""
    path = os.path.join(ROOT, relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class capture_stdout:
    """静音管线 print。"""

    def __enter__(self):
        self._buf = io.StringIO()
        self._old = sys.stdout
        sys.stdout = self._buf
        return self._buf

    def __exit__(self, *exc):
        sys.stdout = self._old


class capture_stderr:
    def __enter__(self):
        self._buf = io.StringIO()
        self._old = sys.stderr
        sys.stderr = self._buf
        return self._buf

    def __exit__(self, *exc):
        sys.stderr = self._old


def mock_macro(today=None):
    """用 fixtures 离线回放出一份宏观数据（9 项指标 + 4 项人工维护项）。"""
    now = datetime.combine(today or date.today(), datetime.min.time(), tzinfo=timezone.utc)
    with capture_stdout():
        return md.build(now=now, mode='mock')


def market_with(quotes=None, fetch_date=None, mode='live'):
    return {'fetch_date': fetch_date or date.today().isoformat(), 'mode': mode,
            'quotes': quotes or {}}


# =====================================================================
# 1. 抓取层：fixtures 能解析出真实指标，且每项自带 as_of / status / source
# =====================================================================
class TestMacroFetch(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.macro = mock_macro()

    def test_all_indicators_present_and_live(self):
        ind = self.macro['indicators']
        self.assertEqual(len(ind), 9, sorted(ind))
        for key, rec in ind.items():
            self.assertIsNotNone(rec.get('value'), f'{key} 取不到值')
            self.assertTrue(rec.get('as_of'), f'{key} 缺 as_of')
            self.assertTrue(rec.get('source'), f'{key} 缺来源')
            self.assertEqual(rec.get('status'), 'live', f'{key} 应为 live: {rec.get("error")}')
            self.assertIn(rec.get('max_age_days'), (7, 45, 400), f'{key} 频率上限异常')

    def test_key_indicators_values_are_from_fixtures(self):
        ind = self.macro['indicators']
        # FRED DFEDTARU 快照 → 3.75；DGS10 → 4.36%；东财 CPI → 0.8%
        self.assertAlmostEqual(ind['fed_rate']['detail']['upper'], 3.75, places=2)
        self.assertAlmostEqual(ind['us10y']['value'], 4.36, places=2)
        self.assertAlmostEqual(ind['cn_cpi']['value'], 0.8, places=2)

    def test_fed_rate_carries_hold_days_and_vintage(self):
        rec = self.macro['indicators']['fed_rate']
        det = rec.get('detail') or {}
        self.assertRegex(str(det.get('unchanged_since') or ''), r'^\d{4}-\d{2}-\d{2}$',
                         '必须给出"自何日起未调整"')
        self.assertGreaterEqual(det.get('unchanged_days'), 0)
        blocks = mr.build_blocks(self.macro, market_with(), today=date.today())
        body = '\n'.join(b['body'] for b in blocks)
        self.assertIn(det['unchanged_since'], body, '渲染文案应带上未调整起始日')
        self.assertIn('未调整', body)

    def test_hk_connect_never_fabricates_net_buy(self):
        """官方自 2024-08 停止公布单日净买入 → 只能报成交额，且必须标记不可用。"""
        rec = self.macro['indicators']['hk_connect']
        det = rec.get('detail') or {}
        self.assertFalse(det.get('net_deal_published'), '接口已停发净买入，不应声称可用')
        self.assertNotIn('净买入', rec.get('display') or '')
        self.assertGreater(rec['value'], 0, '成交额应取到')

    def test_hk_connect_hold_cap_unit_is_yi_not_wan(self):
        """回归：HOLD_MARKET_CAP 单位是百万元 → 亿元要 /100（旧代码 /10000 少 100 倍）。"""
        det = self.macro['indicators']['hk_connect']['detail']
        raw = det.get('hold_market_cap')
        self.assertTrue(raw, '快照应含持股市值')
        blocks = mr.build_blocks(self.macro, market_with(), today=date.today())
        body = '\n'.join(b['body'] for b in blocks)
        yi = raw / 100.0
        if yi >= 10000:
            self.assertIn(f'{yi / 10000:,.2f} 万亿', body)
        else:
            self.assertIn(f'{yi:,.0f} 亿', body)
        self.assertNotIn(f'{raw / 10000:,.0f} 亿', body, '仍在用错误的 /10000 折算')

    def test_world_growth_uses_worldbank_actuals(self):
        rec = self.macro['indicators']['world_growth']
        self.assertIn('世界银行', rec['source'])
        self.assertAlmostEqual(rec['value'], 2.9, places=1)
        det = rec.get('detail') or {}
        self.assertTrue(det.get('history') or det.get('prior') is not None or det,
                        '应保留可核对的历史序列/前值')

    def test_manual_items_all_have_as_of_and_status(self):
        man = self.macro['manual']
        self.assertEqual(len(man), 4, sorted(man))
        for key, rec in man.items():
            self.assertTrue(rec.get('as_of'), f'人工项 {key} 缺 as_of')
            self.assertIn(rec.get('status'), ('manual', 'stale', 'missing'), key)
            self.assertTrue(rec.get('max_age_days'), f'人工项 {key} 缺时效上限')

    def test_manual_inputs_no_conflicting_prior_year_actual(self):
        """IMF 人工项不再自带"上一年实际增速"——实际值统一由世界银行给出，避免两个互相矛盾的数字。"""
        raw = json.loads(read_file('macro_manual_inputs.json'))
        extra = raw['inputs']['imf_weo'].get('extra') or {}
        self.assertNotIn('prior_year_actual', extra)
        self.assertNotIn('prior_year', extra)

    def test_bank_targets_carry_vintage(self):
        rec = self.macro['manual']['bank_targets']
        self.assertTrue(rec.get('targets'), '目标价列表不应为空')
        self.assertRegex(rec['as_of'], r'^\d{4}-\d{2}-\d{2}$')

    def test_events_calendar_has_future_items_and_vintage(self):
        ev = self.macro['events']
        self.assertTrue(ev.get('calendar_vintage'), '日历必须标 vintage')
        upcoming = [e for e in (ev.get('upcoming') or []) if e.get('date')]
        self.assertTrue(upcoming, '应给出未来观察点')
        today = date.today().isoformat()
        self.assertTrue(all(e['date'] >= today for e in upcoming), '不应把已过去的会议当"下一观察点"')

    def test_stale_manual_items_are_reported_not_hidden(self):
        """碳酸锂 14 天上限 / 地缘判断 7 天上限：超期必须进 summary.stale 列表。"""
        stale = self.macro.get('summary', {}).get('stale') or []
        names = ' '.join(stale)
        # fixtures 的人工项 as_of 是固定的，随时间推移必然超期 → 必须被点名
        for rec in self.macro['manual'].values():
            if rec['status'] == 'stale':
                self.assertIn(rec['name'], names, f'{rec["name"]} 陈旧却未被 summary 点名')

    def test_missing_indicator_marked_missing_not_backfilled(self):
        """任一源取不到 → status=missing + error，绝不塞旧值。"""
        def broken_getter(url, timeout=10):
            raise OSError('simulated network failure')

        with capture_stdout():
            now = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
            out = md.build(now=now, mode='live', getter=broken_getter)
        for key, rec in out['indicators'].items():
            self.assertEqual(rec['status'], 'missing', f'{key} 源挂了却仍有值：{rec.get("value")}')
            self.assertIsNone(rec['value'], key)
            self.assertTrue(rec.get('error'), f'{key} 应记录失败原因')


# =====================================================================
# 2. 时效计算：月频按观测期末算，人工项按各自上限算
# =====================================================================
class TestAgeMath(unittest.TestCase):

    def test_daily_age_is_plain_delta(self):
        today = date(2026, 9, 16)
        self.assertEqual(md._age_days('2026-09-15', today), 1)
        self.assertEqual(md._age_days('2026-08-17', today), 30)

    def test_monthly_age_measured_from_period_end(self):
        """8 月 CPI 在 9 月中旬公布是正常的，不该按 8-01 算成 46 天陈旧。"""
        today = date(2026, 9, 16)
        self.assertEqual(md._age_days('2026-08-01', today, freq='monthly'), 16)
        self.assertEqual(md._age_days('2026-02-01', today, freq='monthly'),
                         (today - date(2026, 2, 28)).days)

    def test_unparsable_as_of_returns_none(self):
        self.assertIsNone(md._age_days('', date(2026, 9, 16)))
        self.assertIsNone(md._age_days('上个月', date(2026, 9, 16)))

    def test_manual_status_thresholds(self):
        today = date(2026, 9, 16)
        fresh, problems = md.load_manual_inputs(today)
        self.assertEqual(len(fresh), 4)
        for key, rec in fresh.items():
            limit = rec['max_age_days']
            if rec['age_days'] > limit:
                self.assertEqual(rec['status'], 'stale', key)
                self.assertTrue(any(key in p for p in problems), f'{key} 陈旧但未记录问题')
            else:
                self.assertEqual(rec['status'], 'manual', key)


# =====================================================================
# 3. 渲染层：缺数据就写"未取到"，陈旧就打标签，且不含任何写死数字
# =====================================================================
class TestRender(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.macro = mock_macro()
        cls.blocks = mr.build_blocks(cls.macro, market_with(), today=date.today())
        cls.web = mr.render_web(cls.blocks)
        with capture_stdout():
            cls.wechat = mr.render_wechat(cls.blocks)

    def test_blocks_cover_all_sections(self):
        titles = [b['title'] for b in self.blocks]
        self.assertGreaterEqual(len(titles), 5, titles)
        joined = ' '.join(titles)
        for kw in ('增长', '美联储', '中国物价', '港股', '大宗'):
            self.assertIn(kw, joined, f'缺少板块：{kw}（现有 {titles}）')

    def test_no_hardcoded_stale_literals(self):
        forbidden = forbidden_literals(self.macro)
        self.assertTrue(forbidden, '应至少有一批旧写死值被纳入回归清单')
        for lit in forbidden:
            self.assertNotIn(lit, self.web, f'网页渲染仍含无出处的写死值 {lit}')
            self.assertNotIn(lit, self.wechat, f'微信渲染仍含无出处的写死值 {lit}')

    def test_bank_targets_are_data_driven_with_vintage(self):
        """目标价可以出现，但必须来自 macro_manual_inputs.json 且带 vintage。"""
        rec = self.macro['manual']['bank_targets']
        bases = [t['base'] for t in rec['targets'] if t.get('base')]
        self.assertTrue(bases)
        for base in bases:
            self.assertIn(base, self.web, f'人工维护的目标价 {base} 未被渲染')
        self.assertIn(rec['as_of'], self.web)

    def test_missing_quote_renders_explicit_not_a_number(self):
        """行情层空 → 不得出现任何指数点位断言。"""
        self.assertIn('恒指行情未取到', self.web)
        self.assertNotRegex(re.sub(r'<[^>]+>', '', self.web), r'恒生指数[^。]*\d{2},\d{3}')

    def test_missing_tech_renders_explicit(self):
        self.assertIn('历史 K 线未取到', self.web)
        self.assertNotIn('EMA9', self.web, '没有日线却给出 EMA 断言')

    def test_every_claim_carries_as_of(self):
        """有值的指标行必须带"截至 YYYY-MM-DD"或"观测期"。"""
        text = re.sub(r'<[^>]+>', '', self.web)
        for rec in self.macro['indicators'].values():
            if rec.get('value') is None:
                continue
            self.assertTrue(re.search(r'截至 \d{4}-\d{2}-\d{2}|观测期', text),
                            f'{rec["name"]} 的断言缺 as_of')
            self.assertIn(rec['as_of'], self.web, f'{rec["name"]} 未标注数据日期')

    def test_stale_items_are_labeled(self):
        for rec in list(self.macro['manual'].values()) + list(self.macro['indicators'].values()):
            if rec.get('status') != 'stale':
                continue
            self.assertIn('⚠️ 数据陈旧', self.web, f'{rec["name"]} 陈旧但未打标签')
            self.assertIn(rec['as_of'], self.web)
            self.assertIn(f'上限 {rec["max_age_days"]} 天', self.web)

    def test_stale_block_gets_stale_css_class(self):
        stale_blocks = [b for b in self.blocks if b.get('status') == 'stale']
        self.assertTrue(stale_blocks, 'fixtures 里存在超期人工项，应有 stale 块')
        self.assertIn('macro-block is-stale', self.web)

    def test_web_and_wechat_share_the_same_facts(self):
        """网页与推送同源：关键数值必须同时出现在两个渲染结果里。"""
        plain_web = re.sub(r'<[^>]+>', '', self.web)
        plain_wc = re.sub(r'<[^>]+>', '', self.wechat)
        for rec in self.macro['indicators'].values():
            if rec.get('value') is None or not rec.get('display'):
                continue
            disp = rec['display']
            if disp in plain_web:
                self.assertIn(disp, plain_wc, f'{rec["name"]} 在网页有、推送没有（口径不一致）')

    def test_hk_connect_net_buy_disclaimer_present(self):
        self.assertIn('停止公布', self.web, '必须说明净买入额已停发，避免读者误以为漏抓')


# =====================================================================
# 4. 时效护栏：真核对（取代旧版恒真校验）
# =====================================================================
class TestFreshnessGuard(unittest.TestCase):

    def setUp(self):
        self.macro = mock_macro()
        self.today = date.today()

    def test_all_layers_and_items_are_enumerated(self):
        rep = mr.freshness_report(self.macro, market_with(), {'fetch_date': self.today.isoformat()},
                                  {}, today=self.today)
        layers = {i['layer'] for i in rep['items']}
        for want in ('行情', '社区', '宏观', '舆情', '宏观指标', '人工维护项'):
            self.assertIn(want, layers, f'时效表缺少层：{want}')
        self.assertEqual(rep['total'], len(rep['items']))
        self.assertEqual(rep['ok'] + len(rep['stale']) + len(rep['missing']), rep['total'])

    def test_missing_layer_is_flagged(self):
        rep = mr.freshness_report(self.macro, {}, {}, {}, today=self.today)
        names = [i['name'] for i in rep['missing']]
        self.assertIn('market_data.json', names)
        self.assertIn('sentiment_data.json', names)
        self.assertFalse(rep['pushable'])

    def test_mock_mode_layer_is_never_called_live(self):
        """离线回放必须被标为陈旧，不能冒充实时抓取。"""
        rep = mr.freshness_report(self.macro, {}, {}, {}, today=self.today)
        macro_layer = [i for i in rep['items'] if i['name'] == 'macro_data.json'][0]
        self.assertEqual(macro_layer['status'], 'stale')
        self.assertIn('mock', macro_layer['note'])

    def test_yesterday_fetch_is_stale(self):
        yday = (self.today - timedelta(days=2)).isoformat()
        rep = mr.freshness_report(self.macro, market_with(fetch_date=yday), {}, {}, today=self.today)
        row = [i for i in rep['items'] if i['name'] == 'market_data.json'][0]
        self.assertEqual(row['status'], 'stale')
        self.assertFalse(rep['pushable'])

    def test_clean_data_is_pushable_and_banner_is_positive(self):
        macro = {'fetch_date': self.today.isoformat(), 'mode': 'live', 'indicators': {}, 'manual': {}}
        rep = mr.freshness_report(macro, market_with(), {'fetch_date': self.today.isoformat()},
                                  {'fetch_date': self.today.isoformat()}, today=self.today)
        self.assertTrue(rep['pushable'], rep['banner'])
        self.assertTrue(rep['banner'].startswith('✅'), rep['banner'])

    def test_banner_counts_match_items(self):
        rep = mr.freshness_report(self.macro, market_with(), {}, {}, today=self.today)
        m = re.search(r'(\d+) 项陈旧 / (\d+) 项缺失', rep['banner'])
        self.assertTrue(m, rep['banner'])
        self.assertEqual(int(m.group(1)), len(rep['stale']))
        self.assertEqual(int(m.group(2)), len(rep['missing']))

    def test_freshness_web_table_has_reason_column_and_escapes(self):
        rep = mr.freshness_report(self.macro, market_with(), {}, {}, today=self.today)
        html = mr.render_freshness_web(rep)
        self.assertIn('判定依据', html, '网页时效表必须说明"为什么判陈旧"')
        self.assertIn('fresh-table', html)
        self.assertIn('class="stale"', html)
        self.assertIn('class="missing"', html)

    def test_freshness_wechat_renders_rows(self):
        rep = mr.freshness_report(self.macro, market_with(), {}, {}, today=self.today)
        txt = mr.render_freshness_wechat(rep)
        self.assertIn('macro_data.json', txt)
        self.assertIn('陈旧', txt)

    def test_narrative_date_scan_catches_old_absolute_dates(self):
        """防复发：写死的"8 月 20 日阿里业绩"这类过期叙事必须被扫出来。"""
        today = date(2026, 9, 16)
        old = '<p>6 月 20 日阿里业绩超预期，恒指站上压力位。</p>'
        found = mr.scan_narrative_dates(old, today=today)
        self.assertTrue(found, '过期绝对日期未被扫出')
        self.assertIn('6 月 20 日', found[0]['text'])
        self.assertGreater(found[0]['age_days'], 45)

    def test_narrative_date_scan_tolerates_recent_window(self):
        """45 天内的引用属正常叙事，不应误报。"""
        today = date(2026, 9, 16)
        recent = '<p>8 月 20 日恒指回踩箱体下沿。</p>'
        self.assertEqual(mr.scan_narrative_dates(recent, today=today), [])

    def test_narrative_date_scan_ignores_recent_dates(self):
        today = date(2026, 9, 16)
        fresh = f'<p>{today.month} 月 {today.day} 日恒指收报。</p>'
        self.assertEqual(mr.scan_narrative_dates(fresh, today=today), [])


# =====================================================================
# 5. 推送层：陈旧即拦下手动推送（旧版恒真校验已删）
# =====================================================================
class TestPushGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.wp = _load_module('wechat_push_under_test', os.path.join('tools', 'wechat_push.py'))

    def _fresh(self, stale=True):
        macro = mock_macro()
        return mr.freshness_report(macro, market_with(), {}, {}, today=date.today())

    def test_no_tautological_date_check_left(self):
        """旧版 assert_fetch_dates_are_today 恒真（比较同一份数据的日期）→ 必须已改成真核对。"""
        src = read_file(os.path.join('tools', 'wechat_push.py'))
        self.assertIn('assert_content_freshness', src)
        self.assertNotRegex(src, r'def assert_fetch_dates_are_today\([^)]*\):\n\s*return True')

    def test_strict_push_is_blocked_when_stale(self):
        rep = self._fresh()
        self.assertFalse(rep['pushable'], '前置条件：fixtures 应产出陈旧/缺失项')
        with capture_stdout(), capture_stderr() as err:
            with self.assertRaises(SystemExit) as ctx:
                self.wp.assert_content_freshness([('t', '正文')], rep,
                                                 datetime.now(timezone.utc), strict=True)
        self.assertEqual(ctx.exception.code, 6)
        self.assertIn('陈旧', err.getvalue())

    def test_allow_stale_passes_but_keeps_warning(self):
        rep = self._fresh()
        with capture_stdout() as out, capture_stderr():
            ok = self.wp.assert_content_freshness([('t', '正文')], rep,
                                                  datetime.now(timezone.utc),
                                                  strict=True, allow_stale=True)
        self.assertFalse(ok, '返回值表示"数据不干净"；放行只体现在不抛 SystemExit')
        self.assertIn('⚠️', out.getvalue(), '知情放行仍须打印问题清单')
        self.assertIn('放行模式', out.getvalue())

    def test_scheduled_push_only_warns(self):
        rep = self._fresh()
        with capture_stdout() as out, capture_stderr():
            ok = self.wp.assert_content_freshness([('t', '正文')], rep,
                                                  datetime.now(timezone.utc), strict=False)
        self.assertFalse(ok, '定时模式同样返回"不干净"，只是不中断 09:00 任务')
        self.assertIn('警告', out.getvalue())

    def test_old_narrative_date_in_body_blocks_push(self):
        """正文里残留过期绝对日期 → 即使数据层新鲜也要拦下。"""
        clean = {'stale': [], 'missing': [], 'ok': 1, 'total': 1, 'pushable': True,
                 'banner': '✅', 'items': [], 'today': date.today().isoformat()}
        body = '<p>6 月 20 日阿里业绩超预期。</p>'
        with capture_stdout(), capture_stderr():
            with self.assertRaises(SystemExit):
                self.wp.assert_content_freshness([('t', body)], clean,
                                                 datetime.now(timezone.utc), strict=True)

    def test_push_fallback_delegates_to_community_data(self):
        """community_data.json 缺失时，推送必须复用同一套模板，不能有第二份写死文案。"""
        src = read_file(os.path.join('tools', 'wechat_push.py'))
        self.assertIn('generate_dynamic_quote', src)
        self.assertIn('generate_verdict', src)
        for lit in forbidden_literals(mock_macro()):
            self.assertNotIn(lit, src, f'推送脚本仍内嵌无出处的写死值 {lit}')


# =====================================================================
# 6. 社区层：模板事实全部动态，缺失不伪造
# =====================================================================
class TestCommunityFacts(unittest.TestCase):

    def test_fmt_hsi_without_data_fabricates_nothing(self):
        f = cd.fmt_hsi({}, {})
        self.assertIsNone(f['raw_last'], '旧版会伪造 25440.17 兜底')
        self.assertFalse(f['has_quote'])
        self.assertFalse(f['has_tech'])
        self.assertIsNone(f['sup'])
        self.assertIsNone(f['res'])
        self.assertEqual(f['last'], '—')

    def test_fmt_hsi_uses_tech_layer_for_levels(self):
        market = {'quotes': {'HSI': {'last': 26123.45, 'pct': 0.42, 'chg': 109.2,
                                     'as_of': '2026-09-15',
                                     'tech': {'box_low_20d': 25800.0, 'box_high_20d': 26400.0,
                                              'ema9': 26050.0, 'ema21': 25980.0,
                                              'ema_state': '多头排列', 'rsi14': 58.1,
                                              'rsi_state': '中性偏强', 'ma50': 25600.0,
                                              'chg_1m_pct': 3.2, 'points': 120}}}}
        f = cd.fmt_hsi(market, {})
        self.assertTrue(f['has_tech'])
        self.assertEqual(f['sup'], '25,800')
        self.assertEqual(f['res'], '26,400')
        self.assertIn('RSI14 58.1', f['rsi_txt'])
        self.assertIn('EMA9 26,050', f['ema_txt'])

    def test_fmt_hsi_pulls_macro_facts_with_dates(self):
        macro = mock_macro()
        f = cd.fmt_hsi({}, macro)
        self.assertIn('4.36', f['us10y_txt'])
        self.assertIn('截至', f['us10y_txt'])
        self.assertIn('港股通成交额', f['hkc_txt'])
        self.assertIn('0.8', f['cn_cpi_txt'])
        self.assertIn('大行基准目标价', f['targets_txt'])
        self.assertIn('截至', f['targets_txt'])

    def test_generated_quotes_contain_no_stale_literals(self):
        macro = mock_macro()
        fetch_date = date.today().isoformat()
        for c in cd.COMMUNITIES:
            f = cd.fmt_hsi({}, macro)
            quote = cd.generate_dynamic_quote(c, f, fetch_date, f'{fetch_date} 中文', '', mode='mock')
            verdict = cd.generate_verdict(c, f, '9 月 16 日')
            for lit in forbidden_literals(macro):
                self.assertNotIn(lit, quote, f'{c.get("key")} 动态引语含写死值 {lit}')
                self.assertNotIn(lit, verdict, f'{c.get("key")} 研判含写死值 {lit}')
            self.assertIn('未取到', quote + verdict,
                          f'{c.get("key")} 行情缺失时应显式写"未取到"')


# =====================================================================
# 7. 网页注入：report.html 02 节由构建注入，模板本身不被写死内容污染
# =====================================================================
class TestWebInjection(unittest.TestCase):

    def test_template_has_macro_markers_and_css(self):
        tpl = read_template()
        self.assertIn('<!-- MACRO_BLOCK:BEGIN -->', tpl)
        self.assertIn('<!-- MACRO_BLOCK:END -->', tpl)
        self.assertIn('<!-- FRESHNESS_BLOCK:BEGIN -->', tpl)
        self.assertIn('<!-- FRESHNESS_BLOCK:END -->', tpl)
        self.assertIn('02 / 全球经济与财经动态', tpl)
        for cls in ('.macro-block', '.macro-sub', '.fresh-table', '.stale-banner'):
            self.assertIn(cls, tpl, f'缺少样式 {cls}')

    def test_template_has_no_hardcoded_macro_numbers(self):
        tpl = read_template()
        for lit in OLD_HARDCODED:
            self.assertNotIn(lit, tpl, f'模板正文仍写死 {lit}')

    def test_build_site_injects_macro_and_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'built.html')
            with tempfile.TemporaryDirectory() as mtmp:
                macro_path = os.path.join(mtmp, 'macro_data.json')
                with open(macro_path, 'w', encoding='utf-8') as f:
                    json.dump(mock_macro(), f, ensure_ascii=False)
                proc = subprocess.run(
                    [sys.executable, 'build_site.py', '--template', 'report.html',
                     '--out', out, '--macro', macro_path],
                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = read_abs(out)
            self.assertIn('已动态注入 02 宏观层', proc.stdout)
            self.assertIn('已动态注入 02 时效核对表', proc.stdout)
            body = html.split('<!-- MACRO_BLOCK:BEGIN -->')[1].split('<!-- MACRO_BLOCK:END -->')[0]
            self.assertIn('macro-block', body)
            self.assertNotIn('宏观层未构建', body, '占位降级文案未被替换')
            fresh = html.split('<!-- FRESHNESS_BLOCK:BEGIN -->')[1].split('<!-- FRESHNESS_BLOCK:END -->')[0]
            self.assertIn('fresh-table', fresh)
            self.assertIn('判定依据', fresh)
            self.assertIn('数据时效', proc.stdout)
            for lit in forbidden_literals(mock_macro()):
                self.assertNotIn(lit, body, f'注入后的 02 节含无出处的写死值 {lit}')

    def test_build_survives_missing_macro_file(self):
        """宏观数据缺失时页面仍要能构建，但 02 节必须显式说明未取到。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'built.html')
            proc = subprocess.run(
                [sys.executable, 'build_site.py', '--template', 'report.html', '--out', out,
                 '--macro', os.path.join(tmp, 'nope.json')],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('未找到', proc.stderr)
            html = read_abs(out)
            self.assertIn('未取到', html)

    def test_verdict_section_is_injected_not_hardcoded(self):
        """07 节核心结论过去写死箱体/止损/RSI，现由 verdict_items() 与推送共用一份推导。"""
        tpl = read_template()
        self.assertIn('<!-- VERDICT_LIST:BEGIN -->', tpl)
        self.assertIn('<!-- VERDICT_LIST:END -->', tpl)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'built.html')
            with tempfile.TemporaryDirectory() as mtmp:
                macro_path = os.path.join(mtmp, 'macro_data.json')
                with open(macro_path, 'w', encoding='utf-8') as f:
                    json.dump(mock_macro(), f, ensure_ascii=False)
                proc = subprocess.run(
                    [sys.executable, 'build_site.py', '--template', 'report.html',
                     '--out', out, '--macro', macro_path],
                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('已动态注入 07 核心结论', proc.stdout)
            html = read_abs(out)
            body = html.split('<!-- VERDICT_LIST:BEGIN -->')[1].split('<!-- VERDICT_LIST:END -->')[0]
            self.assertIn('全球宏观面', body)
            self.assertNotIn('核心结论未构建', body, '占位降级文案未被替换')
            for lit in forbidden_literals(mock_macro()):
                self.assertNotIn(lit, body, f'07 节仍含无出处的写死值 {lit}')

    def test_web_and_push_verdict_share_one_generator(self):
        """网页 07 节与微信 07 节必须来自同一个 verdict_items()，数值口径一致。"""
        macro = mock_macro()
        items = mr.verdict_items(macro, market_with(), {})
        web = mr.render_verdict_web(items)
        wc = mr.render_verdict_wechat(items)
        self.assertIn('<li', web)
        self.assertIn('•', wc)
        plain_web = re.sub(r'<[^>]+>', '', web)
        plain_wc = re.sub(r'<[^>]+>', '', wc)
        for rec in macro['indicators'].values():
            if rec.get('display') and rec['display'] in plain_wc:
                self.assertIn(rec['display'], plain_web,
                              f'{rec["name"]} 在推送有、网页没有（07 节口径不一致）')
        # 条目数一致（网页 <li> 与推送 • 一一对应）
        self.assertEqual(web.count('<li'), len(items))
        self.assertEqual(wc.count('• <strong>'), len([i for i in items if i['kind'] != 'note']))

    def test_filter_tab_counts_are_tokens_not_literals(self):
        """03 节筛选标签的"偏多(6)/偏空(3)"等家数过去写死，现按抓取结果统计。"""
        tpl = read_template()
        for token in ('{{FILTER_TOTAL}}', '{{FILTER_BULL}}', '{{FILTER_BEAR}}',
                      '{{FILTER_NEUTRAL}}', '{{FILTER_MIXED}}'):
            self.assertIn(token, tpl, f'缺少占位符 {token}')
        self.assertNotIn('偏多 (6)', tpl)
        self.assertNotIn('全部 14 平台', tpl)

    def test_template_carries_no_stale_embedded_push_payload(self):
        """仓库模板不得内嵌旧推送快照（会把过期正文当成最新内容推给群组）。"""
        tpl = read_template()
        payload = tpl.split('<!-- WECHAT-EMBED:BEGIN -->')[1].split('<!-- WECHAT-EMBED:END -->')[0]
        self.assertLess(len(payload), 6000, f'内嵌负载过大（{len(payload)}），疑似又提交了构建快照')
        self.assertIn('推送负载未构建', payload)
        for lit in OLD_HARDCODED:
            self.assertNotIn(lit, payload, f'内嵌负载仍含旧快照内容 {lit}')

    def test_template_is_not_clobbered_by_build(self):
        """report.html 在仓库里必须保持模板形态（含 {{占位符}}），构建产物不入库。"""
        tpl = read_template()
        self.assertIn('{{', tpl, '模板占位符被写死内容覆盖了')


if __name__ == '__main__':
    unittest.main(verbosity=2)
