import csv
import json
import time
import re
import calendar
import hashlib
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup


# ==========================================
# 1. 日志配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ==========================================
# 2. RSS 源配置
# ==========================================
RSS_FEEDS_BY_CATEGORY = {
    # =====================================
    # 1. 硬核科技与 AI
    # =====================================
    "tech_ai": [
        "https://www.technologyreview.com/feed/",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://deepmind.google/blog/rss.xml",
        "https://blog.google/technology/ai/rss/",
    ],

    # =====================================
    # 2. 前沿科技公司
    # =====================================
    "frontier_companies": [
        "https://www.apple.com/newsroom/rss-feed.rss",
        "https://nvidianews.nvidia.com/rss",
        "https://news.google.com/rss/search?q=OpenAI+OR+Tesla+OR+Apple+OR+Google+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=NVIDIA+OR+TSMC+OR+ASML+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=SpaceX+OR+CATL+OR+BYD+OR+Boston+Dynamics+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=Microsoft+OR+Meta+Llama+when:1d&hl=en-US&gl=US&ceid=US:en",
    ],

    # =====================================
    # 3. 金融与宏观商业
    # =====================================
    "finance_business": [
        "http://feeds.marketwatch.com/marketwatch/topstories/",
        "https://www.economist.com/finance-and-economics/rss.xml",
        "https://quanwenrss.com/bloomberg",
    ],

    # =====================================
    # 4. 国际政治与全球局势
    # =====================================
    "global_affairs": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://plink.anyfeeder.com/zaobao/realtime/world",
        "https://plink.anyfeeder.com/zaobao/realtime/china",
    ],
}


# 每个类别最多保留多少条新闻
MAX_ARTICLES_PER_CATEGORY = {
    "tech_ai": 25,
    "frontier_companies": 40,
    "finance_business": 20,
    "global_affairs": 20,
}

# 全局最大新闻数，防止极端情况下抓太多
MAX_TOTAL_ARTICLES = 105


# ==========================================
# 3. 统一新闻数据结构
# ==========================================
@dataclass
class Article:
    category: str
    title: str
    url: str
    source: str
    summary: str
    published_at: Optional[str]
    published_timestamp: Optional[int]
    feed_url: str
    article_id: str


# ==========================================
# 4. 工具函数
# ==========================================
def clean_html(raw_text: str) -> str:
    """
    清理 RSS summary 中常见的 HTML 标签、换行和多余空格。

    这里先判断内容是否真的像 HTML。
    如果不是 HTML，就不交给 BeautifulSoup，避免 MarkupResemblesLocatorWarning。
    """
    if not raw_text:
        return ""

    raw_text = str(raw_text).strip()

    if not raw_text:
        return ""

    # 只有包含形如 <p>...</p> / <a href=...> 的内容时才用 BeautifulSoup
    looks_like_html = bool(re.search(r"<[^>]+>", raw_text))

    if not looks_like_html:
        return " ".join(raw_text.split())

    soup = BeautifulSoup(raw_text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return " ".join(text.split())


def truncate_text(text: str, max_chars: int = 800) -> str:
    """
    限制摘要长度，防止部分 RSS 源塞入超长全文，浪费 token。
    """
    if not text:
        return ""

    text = text.strip()

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "..."


def get_source_name(feed, feed_url: str) -> str:
    """
    优先使用 RSS 自带标题，否则从域名提取来源名称。
    """
    feed_title = feed.feed.get("title") if hasattr(feed, "feed") else None

    if feed_title:
        return clean_html(feed_title)

    domain = urlparse(feed_url).netloc
    return domain.replace("www.", "")


def get_entry_timestamp(entry) -> Optional[int]:
    """
    从 RSS entry 中提取发布时间戳。
    优先 published_parsed，其次 updated_parsed。
    """
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return calendar.timegm(entry.published_parsed)

    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return calendar.timegm(entry.updated_parsed)

    return None


def timestamp_to_iso(timestamp: Optional[int]) -> Optional[str]:
    """
    时间戳转 ISO 字符串。
    """
    if timestamp is None:
        return None

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def make_article_id(title: str, url: str) -> str:
    """
    生成稳定 ID，用于去重和排查。
    """
    raw = f"{title}|{url}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def fetch_feed_content(url: str, timeout: int = 15, retries: int = 2) -> Optional[str]:
    """
    用 requests 获取 RSS 内容。
    相比 feedparser.parse(url)，这样可以设置 timeout、headers 和重试。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AI-Daily-Tech-Pulse/1.0; "
            "+https://github.com/)"
        )
    }

    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text

        except requests.RequestException as e:
            logger.warning(
                "RSS 请求失败：%s | 第 %s/%s 次 | 错误：%s",
                url,
                attempt + 1,
                retries + 1,
                e
            )

            if attempt < retries:
                time.sleep(2 ** attempt)

    return None


def get_entry_summary(entry) -> str:
    """
    尽量从 RSS entry 中取出摘要。
    """
    if entry.get("summary"):
        return entry.get("summary")

    if entry.get("description"):
        return entry.get("description")

    content = entry.get("content")
    if content and isinstance(content, list) and len(content) > 0:
        return content[0].get("value", "")

    return ""


# ==========================================
# 5. 核心爬取逻辑
# ==========================================
def fetch_articles_from_feed(
    feed_url: str,
    category: str,
    time_window_seconds: int = 86400,
    fallback_limit: int = 3
) -> List[Article]:
    """
    从单个 RSS 源抓取最近 time_window_seconds 内的新闻。

    对于没有时间戳的 RSS entry：
    - 默认只保留前 fallback_limit 条，防止漏掉重要信息。
    """
    content = fetch_feed_content(feed_url)

    if not content:
        logger.error("跳过 RSS 源，因为无法获取内容：%s", feed_url)
        return []

    feed = feedparser.parse(content)
    source_name = get_source_name(feed, feed_url)

    if feed.bozo:
        logger.warning(
            "RSS 解析可能异常：%s | bozo_exception=%s",
            feed_url,
            feed.bozo_exception
        )

    now_timestamp = int(time.time())
    articles: List[Article] = []
    fallback_count = 0

    for entry in feed.entries:
        title = clean_html(entry.get("title", "无标题"))
        url = entry.get("link", "")

        if not title or not url:
            continue

        published_timestamp = get_entry_timestamp(entry)

        if published_timestamp is not None:
            age_seconds = now_timestamp - published_timestamp

            # 过滤未来时间和超过窗口的旧新闻
            if age_seconds < 0 or age_seconds > time_window_seconds:
                continue

        else:
            # 没时间戳的源，只保留前几条，避免把老新闻全抓进来
            if fallback_count >= fallback_limit:
                continue
            fallback_count += 1

        raw_summary = get_entry_summary(entry)
        summary = truncate_text(clean_html(raw_summary), max_chars=800)

        article = Article(
            category=category,
            title=title,
            url=url,
            source=source_name,
            summary=summary,
            published_at=timestamp_to_iso(published_timestamp),
            published_timestamp=published_timestamp,
            feed_url=feed_url,
            article_id=make_article_id(title, url)
        )

        articles.append(article)

    logger.info(
        "从 %s 提取到 %d 条新闻 | 类别：%s",
        source_name,
        len(articles),
        category
    )
    return articles


def dedupe_articles(articles: List[Article]) -> List[Article]:
    """
    基于 URL 和标题去重。
    """
    seen_urls = set()
    seen_titles = set()
    unique_articles = []

    for article in articles:
        normalized_url = article.url.strip().lower()
        normalized_title = article.title.strip().lower()

        if normalized_url in seen_urls:
            continue

        if normalized_title in seen_titles:
            continue

        seen_urls.add(normalized_url)
        seen_titles.add(normalized_title)
        unique_articles.append(article)

    return unique_articles


def fetch_daily_articles_by_category(
    rss_feeds_by_category: Dict[str, List[str]],
    max_articles_per_category: Dict[str, int],
    time_window_hours: int = 24,
    max_total_articles: Optional[int] = None
) -> List[Article]:
    """
    按类别抓取 RSS，并对每个类别设置最大新闻数量。
    """
    logger.info("开始按类别抓取过去 %d 小时内的新闻", time_window_hours)

    time_window_seconds = time_window_hours * 3600
    all_articles: List[Article] = []

    for category, feed_urls in rss_feeds_by_category.items():
        category_articles: List[Article] = []

        logger.info("开始抓取类别：%s", category)

        for feed_url in feed_urls:
            try:
                articles = fetch_articles_from_feed(
                    feed_url=feed_url,
                    category=category,
                    time_window_seconds=time_window_seconds
                )
                category_articles.extend(articles)

            except Exception as e:
                logger.exception(
                    "处理 RSS 源失败：%s | 类别：%s | 错误：%s",
                    feed_url,
                    category,
                    e
                )

        before_dedupe_count = len(category_articles)
        category_articles = dedupe_articles(category_articles)

        category_articles.sort(
            key=lambda x: x.published_timestamp or 0,
            reverse=True
        )

        category_limit = max_articles_per_category.get(category)

        if category_limit is not None:
            category_articles = category_articles[:category_limit]

        logger.info(
            "类别 %s 抓取完成：原始 %d 条，去重并限额后保留 %d 条",
            category,
            before_dedupe_count,
            len(category_articles)
        )

        all_articles.extend(category_articles)

    before_global_dedupe_count = len(all_articles)
    all_articles = dedupe_articles(all_articles)

    all_articles.sort(
        key=lambda x: x.published_timestamp or 0,
        reverse=True
    )

    if max_total_articles is not None:
        all_articles = all_articles[:max_total_articles]

    logger.info(
        "全部类别抓取完成：分类汇总 %d 条，全局去重并限额后保留 %d 条",
        before_global_dedupe_count,
        len(all_articles)
    )

    return all_articles


# ==========================================
# 6. 导出文件：Markdown / JSON / CSV
# ==========================================
def export_articles_to_markdown(
    articles: List[Article],
    output_path: Path
) -> None:
    """
    导出为 Markdown，最适合人眼快速检查。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# 抓取新闻预览",
        "",
        f"- 生成时间：{now}",
        f"- 新闻数量：{len(articles)}",
        "",
        "---",
        ""
    ]

    for index, article in enumerate(articles, start=1):
        lines.extend([
            f"## {index}. {article.title}",
            "",
            f"- 类别：{article.category}",
            f"- 来源：{article.source}",
            f"- 发布时间：{article.published_at or '未知'}",
            f"- 原文链接：{article.url}",
            f"- Feed URL：{article.feed_url}",
            "",
            "摘要：",
            "",
            article.summary or "无摘要",
            "",
            "---",
            ""
        ])

    output_path.write_text("\n".join(lines), encoding="utf-8")


def export_articles_to_json(
    articles: List[Article],
    output_path: Path
) -> None:
    """
    导出为 JSON，适合后续 DeepSeek 分层处理。
    """
    data = [asdict(article) for article in articles]

    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def export_articles_to_csv(
    articles: List[Article],
    output_path: Path
) -> None:
    """
    导出为 CSV，适合用 Excel / Numbers / Google Sheets 检查。
    """
    fieldnames = [
        "article_id",
        "category",
        "source",
        "title",
        "summary",
        "url",
        "published_at",
        "published_timestamp",
        "feed_url",
    ]

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for article in articles:
            writer.writerow(asdict(article))


def export_articles(
    articles: List[Article],
    output_dir: str = "exports"
) -> dict:
    """
    一次性导出 Markdown、JSON、CSV 三种格式。
    """
    export_dir = Path(output_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    markdown_path = export_dir / f"news_preview_{timestamp}.md"
    json_path = export_dir / f"news_preview_{timestamp}.json"
    csv_path = export_dir / f"news_preview_{timestamp}.csv"

    export_articles_to_markdown(articles, markdown_path)
    export_articles_to_json(articles, json_path)
    export_articles_to_csv(articles, csv_path)

    return {
        "markdown": str(markdown_path),
        "json": str(json_path),
        "csv": str(csv_path),
    }


def articles_to_raw_text(articles: List[Article]) -> str:
    """
    临时兼容你当前的 DeepSeek prompt。
    后续可以替换成 JSON / 分层摘要。
    """
    blocks = []

    for idx, article in enumerate(articles, start=1):
        block = (
            f"新闻编号: {idx}\n"
            f"类别: {article.category}\n"
            f"来源: {article.source}\n"
            f"发布时间: {article.published_at or '未知'}\n"
            f"标题: {article.title}\n"
            f"摘要: {article.summary or '无摘要'}\n"
            f"【原文链接】: {article.url}\n"
        )
        blocks.append(block)

    return "\n---\n".join(blocks)


# ==========================================
# 7. 本地测试入口
# ==========================================
if __name__ == "__main__":
    articles = fetch_daily_articles_by_category(
        rss_feeds_by_category=RSS_FEEDS_BY_CATEGORY,
        max_articles_per_category=MAX_ARTICLES_PER_CATEGORY,
        time_window_hours=24,
        max_total_articles=MAX_TOTAL_ARTICLES
    )

    if not articles:
        logger.warning("没有抓取到新闻。")
        raise SystemExit(0)

    exported_files = export_articles(articles, output_dir="exports")

    # print("\n✅ 新闻抓取完成，并已导出文件：")
    # print(f"Markdown 预览文件: {exported_files['markdown']}")
    # print(f"JSON 数据文件:     {exported_files['json']}")
    # print(f"CSV 表格文件:      {exported_files['csv']}")

    print("\n前 10 条新闻预览：")
    for article in articles[:10]:
        print(f"- [{article.category}] [{article.source}] {article.title}")
        print(f"  {article.url}")
