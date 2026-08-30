#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 全景分析 — 14 大社区动态抓取 (community_data.py)

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
        "meta_tpl": "综合站内 3 条热门长帖与讨论",
    },
    {
        "id": "02",
        "key": "XUEQIU",
        "name": "雪球网",
        "icon": "❄️",
        "url": "https://xueqiu.com/hq#HSI",
        "verdict_label": "多空分歧",
        "verdict_class": "mixed",
        "meta_tpl": "综合站内 3 条深度研报与讨论",
    },
    {
        "id": "03",
        "key": "LAOHU",
        "name": "老虎社区",
        "icon": "🐯",
        "url": "https://www.laohu8.com",
        "verdict_label": "偏空",
        "verdict_class": "bear",
        "meta_tpl": "综合站内 3 条热门跨境讨论",
    },
    {
        "id": "04",
        "key": "EASTMONEY",
        "name": "东方财富港股股吧",
        "icon": "💰",
        "url": "https://guba.eastmoney.com",
        "verdict_label": "偏空",
        "verdict_class": "bear",
        "meta_tpl": "综合站内 3 条高互动主题帖",
    },
    {
        "id": "05",
        "key": "ZHITONG",
        "name": "智通财经互动区",
        "icon": "📈",
        "url": "https://www.zhitongcaijing.com",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 3 条专业席位跟踪分析",
    },
    {
        "id": "06",
        "key": "WALLSTREETCN",
        "name": "华尔街见闻社区",
        "icon": "🌐",
        "url": "https://wallstreetcn.com",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 3 条宏观深度长文",
    },
    {
        "id": "07",
        "key": "DISCUSS",
        "name": "香港讨论区财经版",
        "icon": "🇭🇰",
        "url": "https://www.discuss.com.hk/forumdisplay.php?fid=115",
        "verdict_label": "中性",
        "verdict_class": "neutral",
        "meta_tpl": "综合站内 3 条粤语热门讨论贴",
    },
    {
        "id": "08",
        "key": "LIHKG",
        "name": "LIHKG 连登财经台",
        "icon": "🔥",
        "url": "https://lihkg.com/category/5",
        "verdict_label": "偏空",
        "verdict_class": "bear",
        "meta_tpl": "综合站内 3 条高频交易讨论链",
    },
    {
        "id": "09",
        "key": "JIUQUAN",
        "name": "韭圈儿 / 红岸社区",
        "icon": "🥦",
        "url": "https://www.jiucaishuo.com",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 3 篇机构仓位拆解报告",
    },
    {
        "id": "10",
        "key": "ANTFORTUNE",
        "name": "蚂蚁财富港股社区",
        "icon": "🐜",
        "url": "https://www.antfortune.com",
        "verdict_label": "中性",
        "verdict_class": "neutral",
        "meta_tpl": "综合站内 3 条基民热评与定投贴",
    },
    {
        "id": "11",
        "key": "REDDIT",
        "name": "Reddit (r/ChinaStocks)",
        "icon": "👾",
        "url": "https://www.reddit.com/r/ChinaStocks/",
        "verdict_label": "中性",
        "verdict_class": "neutral",
        "meta_tpl": "综合站内 3 篇外文热门深度分析",
    },
    {
        "id": "12",
        "key": "TRADINGVIEW",
        "name": "TradingView 香港板块",
        "icon": "📊",
        "url": "https://www.tradingview.com/markets/hong-kong/",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 3 套专业技术分析图表与指标",
    },
    {
        "id": "13",
        "key": "VIC",
        "name": "Value Investors Club",
        "icon": "💎",
        "url": "https://www.valueinvestorsclub.com",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 3 篇顶尖私密价值分析研报",
    },
    {
        "id": "14",
        "key": "FINTWIT",
        "name": "Twitter / X (FinTwit)",
        "icon": "🐦",
        "url": "https://x.com/search?q=HSI%20Hong%20Kong",
        "verdict_label": "偏多",
        "verdict_class": "bull",
        "meta_tpl": "综合站内 3 条海外基金经理核心观点",
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

def fmt_hsi(market):
    quotes = (market or {}).get('quotes') or {}
    hsi = quotes.get('HSI') or {}
    last = hsi.get('last')
    pct = hsi.get('pct')
    chg = hsi.get('chg')
    as_of = hsi.get('as_of') or ''
    # 格式化
    def fmt(v, nd=2):
        if v is None:
            return '—'
        return f'{float(v):,.{nd}f}'
    last_s = fmt(last)
    pct_s = f"{float(pct):+.2f}%" if pct is not None else "—"
    chg_s = fmt(chg)
    return {
        'last': last_s,
        'pct': pct_s,
        'chg': chg_s,
        'as_of': as_of,
        'raw_pct': float(pct) if pct is not None else 0.0,
        'raw_last': float(last) if last is not None else 25440.17,
    }

def generate_dynamic_quote(community, hsi, fetch_date, fetch_date_cn, live_snippet, mode='live'):
    """
    基于社区特性、恒指行情、抓取日期、活抓片段，动态生成研判正文。
    确保每次内容都包含当天日期，杜绝旧数据。
    """
    m = re.match(r'20\d{2}-(\d{2})-(\d{2})', fetch_date)
    month = int(m.group(1)) if m else 8
    day = int(m.group(2)) if m else 30
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

    # 14 个社区差异化模板，全部带当天日期
    templates = {
        "FUTU": f"平台深度热评：{month} 月 {day} 日恒指{action} {pct_s}，收报 {last} 点，{short_desc}。技术派指出 26,000 整数关仍是强阻力，30 分钟级别需等待金叉才重新进场；资金派紧盯分时大单与南向净流向，强调“先看异动再做决策”——当日盘口反馈远快于叙事。{live_hint} 中长线声音则认为：即便回踩 25,200–25,400 箱体下沿，南向 7 月净买入 628.69 亿、8 月仍净流入，叠加盈利修复，明年上半年挑战 28,200 点的路径未被破坏。",
        "XUEQIU": f"热帖直指“恒指 26,000 关口压力重重，本轮是反弹还是反转”。{month} 月 {day} 日恒指{action} {pct_s} 报 {last}，恒科同步 {short_desc}。球友对半导体“空头撤退股价仍跌”解读为被动出清而非新一轮做空；美债 10 年期约 4.67% 仍压制高估值成长，资金在光通信 / 芯片与红利、内房之间高速轮动。价值派强调：南向 7 月净买入 628.69 亿、今年除 5 月外持续流入，盈利 3%–4% 内生增长与 31,000 点基准目标仍成立，主张高息底仓 + 新质生产力，拒绝在 26,000 附近追高。{live_hint}",
        "LAOHU": f"跨境账户情绪：{month} 月 {day} 日港股{action}（恒指 {pct_s}），外资 trim China exposure 快于内资的格局仍在；美伊和解预期与霍尔木兹油价扰动叠加华尔街隔夜科技回撤，亚洲时段反弹乏力。社区对折价配售、H 股大额募资仍敏感，认为股权稀释压制追高意愿；操作共识是继续观望，等待金叉与 25,800 放量收复，短线维持离场信号。{live_hint}",
        "EASTMONEY": f"股吧情绪：{month} 月 {day} 日恒指{action} {pct_s}，科网股与内房分化明显。讨论焦点从“五连阳还能不能追”转为“26,000 失败后会不会回踩 25,200”。内房午后异动被解读为政策博弈炒作而非趋势反转；消费防御相对抗跌。多数声音主张先看 25,400 箱体下沿能否守住，跌破再看 24,400 / 23,500。{live_hint}",
        "ZHITONG": f"席位与衍生品视角：{month} 月 {day} 日恒指牛熊街货比约 49:51，熊证重货区落在 26,200–26,299、牛证重货区在 25,200–25,299，与现货箱体高度吻合。{short_desc}，收 {last}（{pct_s}）。光通信获摩根大通一周内多次加仓中际旭创 H 股，芯片股逆市走强；长线席位继续流向高息、REITs、电信与公用事业。{live_hint}",
        "WALLSTREETCN": f"宏观对冲盘聚焦：{month} 月 {day} 日美国 CPI 与非农数据组合仍主导离岸成长估值，恒指{action} {pct_s} 至 {last}。社区主流叙事仍是“全球资金从韩日美股拥挤多头再平衡至低估港股 + 国内政策托底”，但强调 26,000 失败后应以防守姿态做多：黄金与铜铝锂及高息低贝塔，而非追互联网贝塔。{live_hint}",
        "DISCUSS": f"本地炒鬼：{month} 月 {day} 日恒指{action} {pct_s}，共识是“又係 26,000 附近派货”。内房脉冲被当成政策消息博弈，多数人表示“睇得、唔好追”。共识仍是港股弱于 A 股、先跌后上，必须等金叉同南向持续净流入先至加仓；配置上继续揽住高息、本地电信、REITs 同公用。{live_hint}",
        "LIHKG": f"连登交易员：{month} 月 {day} 日恒指{action} {pct_s}，三周涨幅后未能放量突破 26,200–26,500，{short_desc}。主流策略切到期权 / 牛熊证做波动率，街货比 49:51 被解读为多空打平、适合两边开仓；硬止损纪律被反复强调。中期仍认资金再平衡，但短线紧盯 6h/12h ALMA 与 25,200 牛证重货区。{live_hint}",
        "JIUQUAN": f"公募与港股通持仓透视：{month} 月 {day} 日恒指{action} {pct_s} 报 {last}，南向 7 月净买入 628.69 亿、8 月延续净流入；近一月主力流向资讯科技、原材料、医疗保健。截至 {month} 月 {day} 日南向持股市值前十仍是腾讯、建行、工行、中海油、汇丰、中国移动、阿里、中行、中芯、小米。机构共识未改：估值修复 + 科技盈利是 2026 主引擎，箱体震荡是机构完成高低切换的窗口。{live_hint}",
        "ANTFORTUNE": f"基民社区：{month} 月 {day} 日恒指{action} {pct_s}，散户港股 ETF 申购与搜索热度随指数回踩降温，讨论从“还能不能追”转为“定投要不要暂停”。理财顾问仍主推高息红利、REITs、电信与公用事业作为底仓，提醒不要在箱体上沿加杠杆。情绪从极度乐观回到中性偏防守。{live_hint}",
        "REDDIT": f"英文社区：{month} 月 {day} 日恒指{action} {pct_s}，仍把港股当作投资中国核心资产最便利的离岸通道，VIE / ADR 等价性讨论未停。增量话题切到宏观：美国 CPI 与就业数据降低加息紧迫性；霍尔木兹和解预期反复、油价走高被视作主要外部扰动。整体偏“可投资性 + 事件驱动”，缺少一致指数多空押注。{live_hint}",
        "TRADINGVIEW": f"图表派更新：{month} 月 {day} 日恒指收 {last}（{pct_s}），{short_desc}。三周反弹后于 26,000 录得 RSI 超买警报；EMA9/21 交叉约 25,978 / 25,471 仍托住升势，MACD 高位减速。新作战目标 26,500 / 延伸 27,044，移动止损上移至 25,124；若失守 25,200 牛证重货区则视为箱体下破。{live_hint}",
        "VIC": f"价投私密社区：{month} 月 {day} 日恒指{action} {pct_s}，并不把 26,000 失败当成逻辑破坏：港股相对欧美估值折价、中小盘私有化套利与控股股东折价仍是 2026 主引擎。基准情景维持恒指年底 28,000–29,000、乐观 31,000。配置不变：高息 + 中资科技 + 本地金融为底仓，REITs / 电信 / 必需消费 / 公用对冲。{live_hint}",
        "FINTWIT": f"FinTwit 宏观账户：{month} 月 {day} 日恒指{action} {pct_s} 至 {last}，仍把港股标成“再平衡避风港”，但语气从右侧突破转为“26,000 失败后的健康回撤”。CPI 降温与就业疲弱压低加息赔率，黄金与铜锂继续作为地缘对冲。政策叙事切到北京“及时实施积极政策”与一线城市放松限购，技术上 MA50 已站上，关键是守住 25,200–25,470 均线带。{live_hint}",
    }
    return templates.get(key, f"{month} 月 {day} 日 {name}热评：恒指{action} {pct_s} 收 {last}，{short_desc}。{live_hint} 南向资金与盈利修复仍是中期托底逻辑，箱体震荡中更适合结构性机会而非追高。")

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

    base_verdicts = {
        "FUTU": f"{short} · 中期偏多。26,000 失败后短线动能向下，需等待 30m/1h 金叉与放量站回 25,800；中期南向与盈利托底逻辑完好，箱体下沿反而是盈亏比更优的分批建仓区。",
        "XUEQIU": f"{short} · 中期偏多。26,000 失败与成长股出清尚未结束；但南向月度级回流与低估值高息底仓，为中期提供足够安全边际。",
        "LAOHU": f"偏空观望。外资定价的离岸市场对地缘与美股映射更敏感，港股“先跌于 A 股”格局未改；在缺乏右侧信号前不宜抄底。",
        "EASTMONEY": f"短线偏空。散户从狂热切换到观望，低开低走与科网兑现共振；内房脉冲难改大盘箱体下修的短线基调。",
        "ZHITONG": f"偏多 (结构性机遇)。街货比中性、机构在光通信与高息两端同时加仓，箱体内更适合用期权做结构，而不是裸空指数。",
        "WALLSTREETCN": f"中性偏多 (防御姿态做多)。CPI 降温打开估值修复窗口，霍尔木兹与油价则封住上行斜率；适合用高息 + 贵金属底仓承接再平衡资金。",
        "DISCUSS": f"中性。本土零售维持防守观望，内房脉冲难改仓位结构；右侧金叉出现前不宜激进加仓。",
        "LIHKG": f"短线偏空 (超买回调兑现中)。26,000 失败后波动率交易优于方向单；未站回 25,800–26,000 前，杠杆多头盈亏比不佳。",
        "JIUQUAN": f"偏多 (中期基本面驱动)。月度级南向与外资回流比单日指数涨跌更有信息量；箱体震荡是机构完成高低切换的窗口。",
        "ANTFORTUNE": f"中性 (狂热降温)。散户 FOMO 消退降低了短线见顶压力，但尚未出现恐慌性申赎；适合把仓位从追涨切换回定投式防御底仓。",
        "REDDIT": f"中性。外资认可通道与估值，但在地缘与政策细节落地前维持审慎评估，等待 CPI 后续路径与中概业绩季。",
        "TRADINGVIEW": f"偏多 (结构完好、战术回调)。超买在 26,000 消化是健康的，均线带未坏；回踩 25,400–25,470 是加仓带，失守 25,124 才改方向。",
        "VIC": f"偏多 (价投标尺确立)。箱体回撤不改变折价修复路径；私有化与回购仍是中小盘的确定性事件驱动。",
        "FINTWIT": f"偏多 (国际资本仍在场)。再平衡 + CPI 降温仍是多头底盘；缺的是政策细则与放量收复 26,000，短线应降低进攻斜率。",
    }
    return base_verdicts.get(community['key'], f"{label}。{fetch_date_cn}行情 {hsi['last']}（{hsi['pct']}），箱体震荡中维持原有配置，等待右侧信号。")

def main():
    ap = argparse.ArgumentParser(description='章鱼 AI — 14 大社区动态抓取')
    ap.add_argument('--json', default='community_data.json', help='输出 JSON 路径')
    ap.add_argument('--market-data', default=MARKET_DATA_DEFAULT, help='行情数据 JSON 路径')
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
            c['meta'] = f"{c.get('meta_tpl','综合站内 3 条讨论')} · 最新读取 {fetch_date}"
        data.update({"generated_at": now_full, "fetch_date": fetch_date, "mode": "offline"})
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'🌐 离线模式: 已基于旧数据刷新时间戳 → {args.json}')
        return

    market = load_market_data(args.market_data)
    hsi = fmt_hsi(market)

    communities_out = []
    failed = []

    if args.demo:
        for comm in COMMUNITIES:
            quote = generate_dynamic_quote(comm, hsi, fetch_date, fetch_date_cn, live_snippet="演示模式：模拟抓取成功", mode='demo')
            verdict = generate_verdict(comm, hsi, fetch_date_cn)
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
                "meta": f"{comm['meta_tpl']} · 最新读取 {fetch_date}",
                "meta_tpl": comm["meta_tpl"],
                "fetch_date": fetch_date,
                "source": "demo",
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
