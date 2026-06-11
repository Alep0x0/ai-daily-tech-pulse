import json
import re
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Any


# ==========================================
# 1. 日志配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ==========================================
# 2. 处理策略配置
# ==========================================
CATEGORY_LIMITS = {
    "tech_ai": 20,
    "frontier_companies": 20,
    "finance_business": 15,
    "global_affairs": 15,
}

MAX_TOTAL_ARTICLES = 70

MIN_TITLE_LENGTH = 6
MIN_SUMMARY_LENGTH = 25
MAX_SUMMARY_CHARS_FOR_LLM = 600

# 标题相似度超过这个值，就认为可能是重复新闻
SIMILAR_TITLE_THRESHOLD = 0.84

# 低价值关键词：先保守一点，避免误杀真正重要的新闻
LOW_VALUE_KEYWORDS = [
    "sponsored",
    "advertisement",
    "subscribe",
    "newsletter",
    "podcast",
    "live updates",
    "live blog",
    "deal",
    "coupon",
    "shopping",
    "best deals",
    "how to watch",
    "roundup",
    "trailer",
    "quiz",
    "gallery",
    "photo gallery",
    "折扣",
    "优惠",
    "广告",
    "订阅",
    "播客",
    "直播",
    "图赏",
    "开箱",
    "促销",
]

# 明显应该保留的关键词：用于给新闻打重要性分数
HIGH_SIGNAL_KEYWORDS = [
    # AI / Tech
    "openai",
    "chatgpt",
    "gpt",
    "deepmind",
    "gemini",
    "anthropic",
    "claude",
    "llama",
    "meta ai",
    "nvidia",
    "gpu",
    "h100",
    "b200",
    "blackwell",
    "tsmc",
    "asml",
    "semiconductor",
    "chip",
    "apple",
    "iphone",
    "mac",
    "microsoft",
    "google",
    "tesla",
    "spacex",
    "robot",
    "robotics",
    "model",
    "ai model",
    "人工智能",
    "大模型",
    "芯片",
    "半导体",
    "英伟达",
    "苹果",
    "微软",
    "谷歌",
    "特斯拉",

    # Finance / Macro
    "fed",
    "federal reserve",
    "interest rate",
    "inflation",
    "cpi",
    "pce",
    "nasdaq",
    "s&p",
    "earnings",
    "revenue",
    "market cap",
    "ipo",
    "tariff",
    "sanction",
    "美联储",
    "利率",
    "通胀",
    "财报",
    "营收",
    "关税",
    "制裁",

    # Global affairs
    "china",
    "us",
    "russia",
    "ukraine",
    "taiwan",
    "middle east",
    "israel",
    "iran",
    "election",
    "policy",
    "regulation",
    "中国",
    "美国",
    "俄罗斯",
    "乌克兰",
    "台湾",
    "中东",
    "以色列",
    "伊朗",
    "选举",
    "监管",
]


# ==========================================
# 3. 数据结构
# ==========================================
@dataclass
class ProcessedArticle:
    id: int
    category: str
    source: str
    title: str
    summary: str
    url: str
    published_at: Optional[str]
    published_timestamp: Optional[int]
    importance_score: int


# ==========================================
# 4. 基础清洗函数
# ==========================================
def normalize_text(text: Optional[str]) -> str:
    """
    标准化文本：去掉多余空白、控制字符。
    """
    if not text:
        return ""

    text = str(text)
    text = text.replace("\u200b", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_title_for_compare(title: str) -> str:
    """
    用于标题相似度比较的标准化。
    """
    title = normalize_text(title).lower()

    # 去掉常见标点，降低标题格式差异影响
    title = re.sub(r"[^\w\u4e00-\u9fff]+", " ", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def truncate_text(text: str, max_chars: int) -> str:
    """
    控制文本长度，避免给 LLM 的输入过长。
    """
    text = normalize_text(text)

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "..."


def safe_get(article: Any, key: str, default=None):
    """
    兼容 dict 和 dataclass/object。
    """
    if isinstance(article, dict):
        return article.get(key, default)

    return getattr(article, key, default)


# ==========================================
# 5. 过滤逻辑
# ==========================================
def is_valid_article(article: Any) -> bool:
    """
    判断新闻是否具备基本信息量。
    """
    title = normalize_text(safe_get(article, "title", ""))
    summary = normalize_text(safe_get(article, "summary", ""))
    url = normalize_text(safe_get(article, "url", ""))

    if len(title) < MIN_TITLE_LENGTH:
        return False

    if not url:
        return False

    if len(summary) < MIN_SUMMARY_LENGTH:
        return False

    return True


def is_low_value_article(article: Any) -> bool:
    """
    根据低价值关键词过滤明显噪音。
    """
    title = normalize_text(safe_get(article, "title", ""))
    summary = normalize_text(safe_get(article, "summary", ""))
    source = normalize_text(safe_get(article, "source", ""))

    combined_text = f"{title} {summary} {source}".lower()

    for keyword in LOW_VALUE_KEYWORDS:
        if keyword.lower() in combined_text:
            return True

    return False


def calculate_importance_score(article: Any) -> int:
    """
    简单打分：用于排序，不用于最终判断事实重要性。

    分数来源：
    - 命中高信号关键词
    - 标题较短清晰
    - 有发布时间
    - 摘要信息量适中
    """
    title = normalize_text(safe_get(article, "title", ""))
    summary = normalize_text(safe_get(article, "summary", ""))
    published_timestamp = safe_get(article, "published_timestamp", None)

    combined_text = f"{title} {summary}".lower()
    score = 0

    for keyword in HIGH_SIGNAL_KEYWORDS:
        if keyword.lower() in combined_text:
            score += 2

    if published_timestamp:
        score += 2

    if 30 <= len(summary) <= 800:
        score += 1

    if 8 <= len(title) <= 120:
        score += 1

    return score


# ==========================================
# 6. 去重逻辑
# ==========================================
def title_similarity(title_a: str, title_b: str) -> float:
    """
    标题相似度。
    """
    a = normalize_title_for_compare(title_a)
    b = normalize_title_for_compare(title_b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def dedupe_by_url_and_title(articles: List[Any]) -> List[Any]:
    """
    先做精确去重：URL 和标题。
    """
    seen_urls = set()
    seen_titles = set()
    unique_articles = []

    for article in articles:
        url = normalize_text(safe_get(article, "url", "")).lower()
        title = normalize_title_for_compare(safe_get(article, "title", ""))

        if not url or not title:
            continue

        if url in seen_urls:
            continue

        if title in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(title)
        unique_articles.append(article)

    return unique_articles


def dedupe_similar_titles(
    articles: List[Any],
    threshold: float = SIMILAR_TITLE_THRESHOLD
) -> List[Any]:
    """
    按类别做标题相似去重。
    同一类别内，如果标题高度相似，只保留前面那条。

    注意：
    - 这里保留排序靠前的文章。
    - 所以调用前最好先按重要性和时间排序。
    """
    unique_articles = []

    for article in articles:
        article_title = safe_get(article, "title", "")
        article_category = safe_get(article, "category", "unknown")

        is_duplicate = False

        for existing in unique_articles:
            existing_category = safe_get(existing, "category", "unknown")

            if article_category != existing_category:
                continue

            similarity = title_similarity(
                article_title,
                safe_get(existing, "title", "")
            )

            if similarity >= threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            unique_articles.append(article)

    return unique_articles


# ==========================================
# 7. 排序和限额
# ==========================================
def sort_articles_for_processing(articles: List[Any]) -> List[Any]:
    """
    先按重要性分数，再按发布时间排序。
    """
    return sorted(
        articles,
        key=lambda article: (
            calculate_importance_score(article),
            safe_get(article, "published_timestamp", 0) or 0
        ),
        reverse=True
    )


def limit_by_category(
    articles: List[Any],
    category_limits: Dict[str, int]
) -> List[Any]:
    """
    每个类别保留固定数量。
    """
    result = []

    for category, limit in category_limits.items():
        category_articles = [
            article for article in articles
            if safe_get(article, "category", "unknown") == category
        ]

        category_articles = sort_articles_for_processing(category_articles)
        result.extend(category_articles[:limit])

    # 对于没有出现在 category_limits 里的未知类别，也保留少量，避免误删
    known_categories = set(category_limits.keys())
    unknown_articles = [
        article for article in articles
        if safe_get(article, "category", "unknown") not in known_categories
    ]

    if unknown_articles:
        unknown_articles = sort_articles_for_processing(unknown_articles)
        result.extend(unknown_articles[:5])

    return result


# ==========================================
# 8. 转换为 LLM 输入
# ==========================================
def to_processed_article(article: Any, index: int) -> ProcessedArticle:
    """
    转换为给 LLM 使用的干净结构。
    """
    return ProcessedArticle(
        id=index,
        category=normalize_text(safe_get(article, "category", "unknown")) or "unknown",
        source=normalize_text(safe_get(article, "source", "unknown")) or "unknown",
        title=normalize_text(safe_get(article, "title", "")),
        summary=truncate_text(
            safe_get(article, "summary", ""),
            max_chars=MAX_SUMMARY_CHARS_FOR_LLM
        ),
        url=normalize_text(safe_get(article, "url", "")),
        published_at=safe_get(article, "published_at", None),
        published_timestamp=safe_get(article, "published_timestamp", None),
        importance_score=calculate_importance_score(article)
    )


def articles_to_llm_input(articles: List[Any]) -> List[Dict[str, Any]]:
    """
    转换为 LLM 友好的 JSON 列表。
    """
    processed = []

    for index, article in enumerate(articles, start=1):
        processed_article = to_processed_article(article, index)
        processed.append(asdict(processed_article))

    return processed


# ==========================================
# 9. 主处理入口
# ==========================================
def process_articles(
    articles: List[Any],
    category_limits: Optional[Dict[str, int]] = None,
    max_total_articles: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    完整处理流程：
    1. 基础有效性过滤
    2. 低价值过滤
    3. URL / 标题精确去重
    4. 按重要性和时间排序
    5. 相似标题去重
    6. 按类别限额
    7. 全局限额
    8. 转换为 LLM 输入 JSON
    """
    category_limits = category_limits or CATEGORY_LIMITS
    max_total_articles = max_total_articles or MAX_TOTAL_ARTICLES

    logger.info("开始处理新闻：输入 %d 条", len(articles))

    valid_articles = [article for article in articles if is_valid_article(article)]
    logger.info("基础过滤后：%d 条", len(valid_articles))

    high_value_articles = [
        article for article in valid_articles
        if not is_low_value_article(article)
    ]
    logger.info("低价值过滤后：%d 条", len(high_value_articles))

    unique_articles = dedupe_by_url_and_title(high_value_articles)
    logger.info("URL / 标题精确去重后：%d 条", len(unique_articles))

    sorted_articles = sort_articles_for_processing(unique_articles)

    deduped_articles = dedupe_similar_titles(sorted_articles)
    logger.info("相似标题去重后：%d 条", len(deduped_articles))

    limited_articles = limit_by_category(deduped_articles, category_limits)
    logger.info("按类别限额后：%d 条", len(limited_articles))

    limited_articles = sort_articles_for_processing(limited_articles)

    if max_total_articles is not None:
        limited_articles = limited_articles[:max_total_articles]

    logger.info("全局限额后：%d 条", len(limited_articles))

    llm_input = articles_to_llm_input(limited_articles)
    logger.info("处理完成：输出 %d 条 LLM 输入新闻", len(llm_input))

    return llm_input


# ==========================================
# 10. 文件读写
# ==========================================
def load_articles_from_json(input_path: str) -> List[Dict[str, Any]]:
    """
    从 crawler 导出的 news_preview_*.json 中读取新闻。
    """
    path = Path(input_path)

    if not path.exists():
        raise FileNotFoundError(f"找不到输入文件：{input_path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, list):
        raise ValueError("输入 JSON 必须是新闻列表 list[dict]")

    return data


def export_llm_input(
    llm_input: List[Dict[str, Any]],
    output_dir: str = "exports"
) -> Dict[str, str]:
    """
    导出处理后的 LLM 输入文件。
    """
    export_dir = Path(output_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = export_dir / f"llm_input_{timestamp}.json"
    markdown_path = export_dir / f"llm_input_preview_{timestamp}.md"

    json_path.write_text(
        json.dumps(llm_input, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    export_llm_input_markdown(llm_input, markdown_path)

    return {
        "json": str(json_path),
        "markdown": str(markdown_path),
    }


def export_llm_input_markdown(
    llm_input: List[Dict[str, Any]],
    output_path: Path
) -> None:
    """
    导出 Markdown 预览，方便人工检查。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    category_counts = {}
    for item in llm_input:
        category = item.get("category", "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1

    lines = [
        "# LLM 输入新闻预览",
        "",
        f"- 生成时间：{now}",
        f"- 新闻数量：{len(llm_input)}",
        "",
        "## 类别统计",
        "",
    ]

    for category, count in sorted(category_counts.items()):
        lines.append(f"- {category}: {count}")

    lines.extend([
        "",
        "---",
        ""
    ])

    for item in llm_input:
        lines.extend([
            f"## {item['id']}. {item['title']}",
            "",
            f"- 类别：{item['category']}",
            f"- 来源：{item['source']}",
            f"- 重要性分数：{item['importance_score']}",
            f"- 发布时间：{item.get('published_at') or '未知'}",
            f"- 原文链接：{item['url']}",
            "",
            "摘要：",
            "",
            item.get("summary") or "无摘要",
            "",
            "---",
            ""
        ])

    output_path.write_text("\n".join(lines), encoding="utf-8")


def find_latest_news_json(exports_dir: str = "exports") -> Optional[str]:
    """
    自动寻找 exports 目录下最新的 news_preview_*.json。
    """
    path = Path(exports_dir)

    if not path.exists():
        return None

    candidates = sorted(
        path.glob("news_preview_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if not candidates:
        return None

    return str(candidates[0])


# ==========================================
# 11. 命令行测试入口
# ==========================================
if __name__ == "__main__":
    latest_input = find_latest_news_json("exports")

    if not latest_input:
        logger.error("没有找到 exports/news_preview_*.json，请先运行 crawler.py")
        raise SystemExit(1)

    logger.info("使用最新抓取文件：%s", latest_input)

    raw_articles = load_articles_from_json(latest_input)

    llm_input = process_articles(
        articles=raw_articles,
        category_limits=CATEGORY_LIMITS,
        max_total_articles=MAX_TOTAL_ARTICLES
    )

    exported_files = export_llm_input(llm_input, output_dir="exports")

    print("\n✅ 新闻预处理完成，并已导出文件：")
    print(f"LLM JSON 输入文件: {exported_files['json']}")
    print(f"Markdown 预览文件: {exported_files['markdown']}")

    print("\n前 10 条 LLM 输入新闻预览：")
    for item in llm_input[:10]:
        print(
            f"- [{item['category']}] "
            f"[score={item['importance_score']}] "
            f"{item['title']}"
        )
