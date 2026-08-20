#!/usr/bin/env python3
"""
Singapore Free/Low-Cost Events Scraper
=======================================
从新加坡官方活动来源抓取本周免费/低价公共活动，输出 events.json。

数据来源:
  1. Esplanade (滨海艺术中心) - 免费演出
  2. Gardens by the Bay (滨海湾花园) - 灯光秀/活动
  3. Heritage.sg / Night Festival - 夜间艺术节
  4. National Museum (国家博物馆)
  5. NParks (国家公园) - 活动/工作坊
  6. National Gallery Singapore (国家美术馆)
  7. Gillman Barracks (当代艺术区)
  8. Singapore Tourism Board / VisitSingapore

用法:
  python3 update_events.py              # 抓取并写入 events.json
  python3 update_events.py --dry-run   # 只抓取不写入
  python3 update_events.py --verbose    # 详细日志
"""

import json
import sys
import re
import os
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

# ============================================================
#  配置
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "events.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-SG,en;q=0.9,zh-CN;q=0.8",
}

SOURCES = {
    "esplanade_free": {
        "url": "https://www.esplanade.com/whats-on?IsFree=",
        "name": "Esplanade",
    },
    "esplanade_rda": {
        "url": "https://www.esplanade.com/reddotaugust",
        "name": "Esplanade",
    },
    "gardens_events": {
        "url": "https://www.gardensbythebay.org.sg/en/whats-on.html",
        "name": "Gardens by the Bay",
    },
    "night_festival": {
        "url": "https://www.heritage.sg/sgnightfest/programmes",
        "name": "Night Festival",
    },
    "national_museum": {
        "url": "https://www.nationalmuseum.nhb.gov.sg/",
        "name": "National Museum",
    },
    "national_gallery": {
        "url": "https://www.nationalgallery.sg/",
        "name": "National Gallery",
    },
    "nparks": {
        "url": "https://www.nparks.gov.sg/",
        "name": "NParks",
    },
    "gillman": {
        "url": "https://www.gillmanbarracks.com/",
        "name": "Gillman Barracks",
    },
    "objectifs": {
        "url": "https://www.objectifs.com.sg/",
        "name": "Objectifs",
    },
    "ura_gallery": {
        "url": "https://www.ura.gov.sg/",
        "name": "URA",
    },
}

# 用户偏好 (与 HTML 中的 USER_PREFS 一致)
USER_PREFS = {
    "categories": ["music", "museum", "exhibition", "art", "festival"],
    "categoryScores": {
        "music": 3, "museum": 3, "exhibition": 2.5, "art": 2,
        "festival": 2, "film": 1.5, "nature": 1.5, "community": 1, "workshop": 1.5,
    },
    "price": "free-first",
    "context": "solo",
    "maxPerDay": 5,
}

VERBOSE = False

def log(msg, level="info"):
    if level == "verbose" and not VERBOSE:
        return
    prefix = {"info": "  ", "warn": "  ⚠️ ", "error": "  ❌ ", "ok": "  ✅ ", "verbose": "    "}
    print(f"{prefix.get(level, '  ')}{msg}")


# ============================================================
#  工具函数
# ============================================================
def fetch_page(url, timeout=20):
    """获取网页内容"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        log(f"Fetch failed: {url} — {e}", "error")
        return None


def generate_week_dates():
    """生成今天起 8 天的日期"""
    days = []
    today = datetime.now()
    weekdays_cn = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    for i in range(8):
        d = today + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        label = "今天" if i == 0 else "明天" if i == 1 else weekdays_cn[d.weekday()]
        short = f"{d.month}/{d.day} {weekdays_cn[d.weekday()]}"
        days.append({"date": date_str, "label": label, "short": short})
    return days


def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")


def categorize(title, desc, source_name):
    """根据标题和描述自动分类"""
    text = (title + " " + desc).lower()
    if any(w in text for w in ["festival", "night fest", "艺术节", "夜间艺术"]):
        return "festival"
    if any(w in text for w in ["museum", "exhibition", "展览", "博物馆", "gallery", "美术馆"]):
        if any(w in text for w in ["gallery", "美术馆", "contemporary"]):
            return "art"
        return "museum" if "museum" in text or "博物馆" in text else "exhibition"
    if any(w in text for w in ["music", "concert", "performance", "音乐", "演出", "concert", "band", "歌台", "sing"]):
        return "music"
    if any(w in text for w in ["garden", "park", "nature", "tree", "灯光秀", "supertree", "rhapsody"]):
        return "nature"
    if any(w in text for w in ["film", "movie", "cinema", "电影"]):
        return "film"
    if any(w in text for w in ["workshop", "工作坊", "class"]):
        return "workshop"
    if any(w in text for w in ["art", "installation", "装置", "艺术"]):
        return "art"
    if any(w in text for w in ["community", "社区"]):
        return "community"
    return "community"


def detect_price(text):
    """检测价格类型"""
    text_lower = text.lower()
    if any(w in text_lower for w in ["free", "免费", "complimentary", "no charge"]):
        return "free", "免费"
    # 检测具体价格
    price_match = re.search(r'\$?(\d+(?:\.\d+)?)', text)
    if price_match:
        price_val = float(price_match.group(1))
        if price_val <= 15:
            return "low", f"${price_val:.0f}"
        return "paid", f"${price_val:.0f}"
    if any(w in text_lower for w in ["citizen", "pr", "公民", "pr免费"]):
        return "free", "公民/PR免费"
    return "unknown", "见官网"


# ============================================================
#  解析器 (各来源独立)
# ============================================================
def parse_esplanade(html, base_url, source_name):
    """解析 Esplanade 活动页面"""
    events = []
    soup = BeautifulSoup(html, "html.parser")

    # 尝试多种选择器
    cards = soup.select(".event-card, .programme-card, .whats-on-card, .card, article, .listing-item")
    log(f"Esplanade: found {len(cards)} potential cards", "verbose")

    for card in cards:
        try:
            title_el = card.select_one("h2, h3, h4, .title, .card-title, .programme-title, a")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title or len(title) < 3:
                continue

            link_el = card.select_one("a[href]")
            link = link_el["href"] if link_el else base_url
            if link and not link.startswith("http"):
                link = "https://www.esplanade.com" + link

            date_text = ""
            date_el = card.select_one(".date, .event-date, time, .datetime")
            if date_el:
                date_text = date_el.get_text(strip=True)

            desc_el = card.select_one(".description, .desc, .summary, p")
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""

            price_text = card.get_text(strip=True)
            price, price_label = detect_price(price_text)

            category = categorize(title, desc, source_name)

            events.append({
                "title": title,
                "category": category,
                "price": price,
                "priceText": price_label,
                "time": date_text or "见官网",
                "location": "Esplanade 滨海艺术中心",
                "desc": desc or f"Esplanade 免费演出活动：{title}",
                "link": link,
                "source": source_name,
                "date": get_today_str(),  # 需要后续处理日期
            })
        except Exception:
            continue

    return events


def parse_gardens_by_the_bay(html, base_url, source_name):
    """解析滨海湾花园活动页面"""
    events = []
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select(".event-item, .whats-on-item, .card, article, .listing, .tile")
    log(f"Gardens by the Bay: found {len(cards)} potential cards", "verbose")

    # 总是加入 Garden Rhapsody (每晚都有)
    events.append({
        "title": "Garden Rhapsody 灯光秀",
        "category": "nature",
        "price": "free",
        "priceText": "免费",
        "time": "每晚 19:45 & 20:45",
        "location": "Supertree Grove, Gardens by the Bay",
        "desc": '超级树灯光秀。每场约15分钟，适合下班后散步观看。',
        "link": "https://www.gardensbythebay.org.sg",
        "source": source_name,
        "date": get_today_str(),
        "hot": True,
    })

    for card in cards:
        try:
            title_el = card.select_one("h2, h3, h4, .title, .card-title, a")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title or len(title) < 3:
                continue

            link_el = card.select_one("a[href]")
            link = link_el["href"] if link_el else base_url
            if link and not link.startswith("http"):
                link = "https://www.gardensbythebay.org.sg" + link

            date_el = card.select_one(".date, time, .datetime, .schedule")
            time_text = date_el.get_text(strip=True) if date_el else "见官网"

            desc_el = card.select_one(".description, .desc, p, .summary")
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""

            price, price_label = detect_price(card.get_text(strip=True))
            category = categorize(title, desc, source_name)

            events.append({
                "title": title,
                "category": category,
                "price": price,
                "priceText": price_label,
                "time": time_text,
                "location": "Gardens by the Bay 滨海湾花园",
                "desc": desc or f"滨海湾花园活动：{title}",
                "link": link,
                "source": source_name,
                "date": get_today_str(),
            })
        except Exception:
            continue

    return events


def parse_night_festival(html, base_url, source_name):
    """解析夜间艺术节节目页面"""
    events = []
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select(".programme, .programme-card, .event, article, .card, .listing, a[href*='programmes']")
    log(f"Night Festival: found {len(cards)} potential cards", "verbose")

    for card in cards:
        try:
            title_el = card.select_one("h2, h3, h4, .title, .card-title, .programme-title, a")
            if not title_el:
                # 可能 card 本身就是 <a>
                if card.name == "a":
                    title = card.get_text(strip=True)
                else:
                    continue
            else:
                title = title_el.get_text(strip=True)

            if not title or len(title) < 3:
                continue

            link = card["href"] if card.name == "a" and card.get("href") else ""
            if not link:
                link_el = card.select_one("a[href]")
                link = link_el["href"] if link_el else ""
            if link and not link.startswith("http"):
                link = "https://www.heritage.sg" + link

            desc_el = card.select_one(".description, .desc, p, .summary, .blurb")
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""

            time_el = card.select_one(".time, .schedule, .date, time")
            time_text = time_el.get_text(strip=True) if time_el else "19:30-24:00"

            events.append({
                "title": title,
                "category": "festival",
                "price": "free",
                "priceText": "免费",
                "time": time_text,
                "location": "Bras Basah.Bugis 艺术文化区",
                "desc": desc or f"新加坡夜间艺术节节目：{title}",
                "link": link or "https://www.heritage.sg/sgnightfest",
                "source": source_name,
                "date": get_today_str(),
            })
        except Exception:
            continue

    return events


def parse_generic(html, base_url, source_name, default_category="museum"):
    """通用解析器：尝试从页面中提取活动信息"""
    events = []
    soup = BeautifulSoup(html, "html.parser")

    # 尝试多种选择器
    cards = soup.select(
        ".event, .exhibition, .programme, .listing, .card, "
        "article, .card-item, .content-card, .tile, "
        ".exhibition-card, .event-item"
    )
    log(f"{source_name}: found {len(cards)} potential cards", "verbose")

    for card in cards:
        try:
            title_el = card.select_one("h2, h3, h4, h5, .title, .card-title, .name, a")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title or len(title) < 3 or len(title) > 200:
                continue

            link_el = card.select_one("a[href]")
            link = link_el["href"] if link_el else base_url
            if link and not link.startswith("http"):
                from urllib.parse import urljoin
                link = urljoin(base_url, link)

            date_el = card.select_one(".date, time, .datetime, .period, .schedule")
            time_text = date_el.get_text(strip=True) if date_el else "见官网"

            desc_el = card.select_one(".description, .desc, p, .summary, .blurb, .intro")
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""

            price_text = card.get_text(strip=True)
            price, price_label = detect_price(price_text)

            category = categorize(title, desc, source_name)

            events.append({
                "title": title,
                "category": category,
                "price": price,
                "priceText": price_label,
                "time": time_text,
                "location": source_name,
                "desc": desc or f"{source_name}活动：{title}",
                "link": link,
                "source": source_name,
                "date": get_today_str(),
            })
        except Exception:
            continue

    return events


# ============================================================
#  主流程
# ============================================================
PARSERS = {
    "esplanade_free": parse_esplanade,
    "esplanade_rda": parse_esplanade,
    "gardens_events": parse_gardens_by_the_bay,
    "night_festival": parse_night_festival,
    "national_museum": lambda html, url, name: parse_generic(html, url, name, "museum"),
    "national_gallery": lambda html, url, name: parse_generic(html, url, name, "museum"),
    "nparks": lambda html, url, name: parse_generic(html, url, name, "nature"),
    "gillman": lambda html, url, name: parse_generic(html, url, name, "art"),
    "objectifs": lambda html, url, name: parse_generic(html, url, name, "exhibition"),
    "ura_gallery": lambda html, url, name: parse_generic(html, url, name, "museum"),
}


def run_scraper():
    """运行所有解析器"""
    all_events = []
    stats = {"success": [], "failed": [], "total_events": 0}

    for key, config in SOURCES.items():
        url = config["url"]
        name = config["name"]
        parser = PARSERS.get(key, lambda html, url, name: parse_generic(html, url, name))

        log(f"Fetching {name}: {url}")
        html = fetch_page(url)
        if not html:
            stats["failed"].append(key)
            continue

        try:
            events = parser(html, url, name)
            if events:
                all_events.extend(events)
                stats["success"].append(f"{key} ({len(events)} events)")
                log(f"  {name}: {len(events)} events found", "ok")
            else:
                stats["success"].append(f"{key} (0 events)")
                log(f"  {name}: no events found (page may be JS-rendered)", "warn")
        except Exception as e:
            stats["failed"].append(f"{key} (parse error: {e})")
            log(f"  {name}: parse error — {e}", "error")

    stats["total_events"] = len(all_events)
    return all_events, stats


def deduplicate(events):
    """去重"""
    seen = set()
    unique = []
    for e in events:
        key = (e.get("title", "").lower().strip(), e.get("date", ""))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def clean_events(events):
    """过滤低质量条目"""
    BAD_TITLES = {"find out more", "read more", "learn more", "more info", "click here", "",
                  "view all", "see all", "back", "home", "next", "previous"}
    cleaned = []
    for e in events:
        title = e.get("title", "").strip()
        # 跳过 URL 路径形式的标题
        if title.startswith("/") or title.startswith("http"):
            continue
        # 跳过太短的标题
        if len(title) < 4:
            continue
        # 跳过通用链接文本
        if title.lower() in BAD_TITLES:
            continue
        # 跳过看起来像 URL slug 的标题
        if re.match(r'^[a-z0-9-]+$', title) and "-" in title and len(title) > 20:
            continue
        cleaned.append(e)
    return cleaned


def build_output(events, stats):
    """构建输出 JSON"""
    return {
        "lastUpdated": datetime.now().astimezone().isoformat(),
        "generatedBy": "scraper",
        "scraperStats": {
            "successCount": len(stats["success"]),
            "failedCount": len(stats["failed"]),
            "totalEvents": stats["total_events"],
            "details": {
                "success": stats["success"],
                "failed": stats["failed"],
            },
        },
        "weekDates": generate_week_dates(),
        "events": events,
        "sources": [
            {"name": v["name"], "url": v["url"]}
            for v in SOURCES.values()
        ],
        "userPrefs": USER_PREFS,
    }


def main():
    global VERBOSE
    dry_run = "--dry-run" in sys.argv
    VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 60)
    print("  Singapore Events Scraper")
    print("  新加坡免费/低价公共活动抓取")
    print("=" * 60)
    print()

    events, stats = run_scraper()
    events = clean_events(events)
    events = deduplicate(events)

    print()
    print(f"  Total unique events: {len(events)}")
    print(f"  Sources succeeded: {len(stats['success'])}")
    print(f"  Sources failed: {len(stats['failed'])}")
    print()

    if stats["failed"]:
        print("  Failed sources:")
        for f in stats["failed"]:
            print(f"    - {f}")
        print()
        print("  ⚠️  部分来源可能需要 JS 渲染，建议用 AI 辅助补充。")
        print()

    output = build_output(events, stats)

    if dry_run:
        print("  [dry-run] Not writing to file.")
        print(f"  Would write {len(events)} events to {OUTPUT_FILE}")
        print()
        print("  Sample events:")
        for e in events[:5]:
            print(f"    - {e.get('title', '?')} ({e.get('category', '?')}, {e.get('priceText', '?')})")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  ✅ Written {len(events)} events to {OUTPUT_FILE}")
    print()


if __name__ == "__main__":
    main()
