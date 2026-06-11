import json
import os
import re
import time
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI


# ==========================================
# 1. 日志配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ==========================================
# 2. DeepSeek 配置
# ==========================================
# 强烈建议把 API Key 放到环境变量里：
# Windows PowerShell:
#   setx DEEPSEEK_API_KEY "sk-xxxx"
#
# macOS / Linux:
#   export DEEPSEEK_API_KEY="sk-xxxx"
#
# GitHub Actions:
#   在 Repository Secrets 中添加 DEEPSEEK_API_KEY
#DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# 你可以按自己的账号可用模型修改
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

TEMPERATURE = 0.25
MAX_TOKENS_PER_CATEGORY = 3000

MAX_TOKENS_BY_CATEGORY = {
    "tech_ai": 2600,
    "frontier_companies": 3800,
    "finance_business": 2400,
    "global_affairs": 2400,
    "unknown": 1800,
}

API_RETRIES = 3
API_RETRY_SLEEP_SECONDS = 3


# ==========================================
# 3. 总结策略配置
# ==========================================
# 每个类别最多给模型多少条新闻
MAX_INPUT_ITEMS_PER_CATEGORY = {
    "tech_ai": 18,
    "frontier_companies": 18,
    "finance_business": 14,
    "global_affairs": 14,
}

# 每个类别最终最多输出多少条新闻
MAX_OUTPUT_ITEMS_PER_CATEGORY = {
    "tech_ai": 6,
    "frontier_companies": 6,
    "finance_business": 5,
    "global_affairs": 5,
}

CATEGORY_TITLES = {
    "tech_ai": {
        "zh": "硬核科技与 AI",
        "en": "Hardcore Tech & AI",
    },
    "frontier_companies": {
        "zh": "前沿科技公司",
        "en": "Frontier Tech Companies",
    },
    "finance_business": {
        "zh": "金融与宏观商业",
        "en": "Finance & Macro Business",
    },
    "global_affairs": {
        "zh": "国际政治与全球局势",
        "en": "Global Affairs",
    },
    "unknown": {
        "zh": "其他",
        "en": "Other",
    },
}

CATEGORY_ORDER = [
    "tech_ai",
    "frontier_companies",
    "finance_business",
    "global_affairs",
    "unknown",
]


# ==========================================
# 4. 数据结构
# ==========================================
@dataclass
class DigestItem:
    title: str
    summary: str
    source: str
    url: str
    importance: str


@dataclass
class DigestSection:
    category: str
    title: str
    items: List[DigestItem]


@dataclass
class Digest:
    language: str
    date: str
    greeting: str
    sections: List[DigestSection]


# ==========================================
# 5. 文件工具
# ==========================================
def find_latest_llm_input(exports_dir: str = "exports") -> Optional[str]:
    """
    自动寻找 exports 目录下最新的 llm_input_*.json。
    """
    path = Path(exports_dir)

    if not path.exists():
        return None

    candidates = sorted(
        path.glob("llm_input_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if not candidates:
        return None

    return str(candidates[0])


def load_llm_input(input_path: str) -> List[Dict[str, Any]]:
    """
    读取 processor.py 输出的 llm_input_*.json。
    """
    path = Path(input_path)

    if not path.exists():
        raise FileNotFoundError(f"找不到输入文件：{input_path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, list):
        raise ValueError("llm_input JSON 必须是 list[dict] 格式")

    return data


def export_digest_files(
    zh_digest: Dict[str, Any],
    en_digest: Dict[str, Any],
    preview_markdown: str,
    output_dir: str = "exports"
) -> Dict[str, str]:
    """
    导出中英文 JSON 和 Markdown 预览。
    """
    export_dir = Path(output_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    zh_path = export_dir / f"digest_zh_{timestamp}.json"
    en_path = export_dir / f"digest_en_{timestamp}.json"
    preview_path = export_dir / f"digest_preview_{timestamp}.md"

    zh_path.write_text(
        json.dumps(zh_digest, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    en_path.write_text(
        json.dumps(en_digest, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    preview_path.write_text(preview_markdown, encoding="utf-8")

    return {
        "zh_json": str(zh_path),
        "en_json": str(en_path),
        "preview_markdown": str(preview_path),
    }


# ==========================================
# 6. 数据分组与裁剪
# ==========================================
def group_articles_by_category(
    articles: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    按 category 分组。
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for article in articles:
        category = article.get("category") or "unknown"
        grouped.setdefault(category, []).append(article)

    return grouped


def sort_articles_for_summary(
    articles: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    按 importance_score 和发布时间排序。
    """
    return sorted(
        articles,
        key=lambda x: (
            x.get("importance_score", 0) or 0,
            x.get("published_timestamp", 0) or 0
        ),
        reverse=True
    )


def prepare_category_articles(
    articles: List[Dict[str, Any]],
    category: str
) -> List[Dict[str, Any]]:
    """
    限制每个类别传给 LLM 的新闻数量。
    """
    limit = MAX_INPUT_ITEMS_PER_CATEGORY.get(category, 10)
    sorted_articles = sort_articles_for_summary(articles)
    return sorted_articles[:limit]


def compact_articles_for_prompt(
    articles: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    只保留给模型必要的信息，降低 token 消耗。
    """
    compact = []

    for article in articles:
        compact.append({
            "id": article.get("id"),
            "category": article.get("category", "unknown"),
            "source": article.get("source", "unknown"),
            "title": article.get("title", ""),
            "summary": article.get("summary", ""),
            "url": article.get("url", ""),
            "published_at": article.get("published_at"),
            "importance_score": article.get("importance_score", 0),
        })

    return compact


# ==========================================
# 7. DeepSeek 客户端与调用
# ==========================================
def get_deepseek_client() -> OpenAI:
    """
    初始化 DeepSeek 客户端。
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "未找到 DEEPSEEK_API_KEY 环境变量。请先配置 API Key，"
            "不要把 Key 直接写进代码。"
        )

    return OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL
    )


def call_deepseek(
    client: OpenAI,
    messages: List[Dict[str, str]],
    max_tokens: int = MAX_TOKENS_PER_CATEGORY,
    temperature: float = TEMPERATURE
) -> Tuple[str, Optional[str]]:
    """
    带重试的 DeepSeek 调用。
    返回：content, finish_reason
    """
    last_error = None

    for attempt in range(API_RETRIES):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason

            if finish_reason == "length":
                logger.warning("DeepSeek 输出被截断：finish_reason=length")

            return content, finish_reason

        except Exception as e:
            last_error = e
            logger.warning(
                "DeepSeek 调用失败，第 %d/%d 次：%s",
                attempt + 1,
                API_RETRIES,
                e
            )

            if attempt < API_RETRIES - 1:
                time.sleep(API_RETRY_SLEEP_SECONDS * (2 ** attempt))

    raise RuntimeError(f"DeepSeek 调用失败，已重试 {API_RETRIES} 次：{last_error}")


# ==========================================
# 8. Prompt 构造
# ==========================================
def get_language_instruction(language: str) -> str:
    """
    返回语言要求。
    """
    if language == "zh":
        return (
            "请只使用简体中文输出。"
            "除公司名、产品名、模型名、机构名等专有名词外，不要夹杂英文句子。"
        )

    if language == "en":
        return (
            "Write only in English. "
            "Do not include any Chinese characters in the output."
        )

    raise ValueError(f"不支持的语言：{language}")


def get_section_title(category: str, language: str) -> str:
    """
    获取类别标题。
    """
    return CATEGORY_TITLES.get(
        category,
        CATEGORY_TITLES["unknown"]
    ).get(language, category)


def build_category_summary_prompt(
    category: str,
    articles: List[Dict[str, Any]],
    language: str
) -> List[Dict[str, str]]:
    """
    为单个类别构造总结 prompt。
    """
    language_instruction = get_language_instruction(language)
    section_title = get_section_title(category, language)
    max_items = MAX_OUTPUT_ITEMS_PER_CATEGORY.get(category, 5)

    if language == "zh":
        system_prompt = f"""
你是一位高信噪比的科技与政经晨报编辑，服务对象是具备强逻辑思维、讨厌废话的工科读者。

你的任务：阅读输入的新闻列表，筛选、合并、去重，并生成一个结构化 JSON 板块总结。

语言要求：
{language_instruction}

内容要求：
1. 只保留高价值新闻，最多输出 {max_items} 条。
2. 对同一事件的多条新闻必须合并，不要重复输出。
3. 每条 summary 控制在 1-2 句话。
4. 结论先行，强调事实、数据、公司动作、政策变化、技术变化。
5. 不要编造输入中没有的信息。
6. 必须保留 source 和 url。
7. 如果没有高价值新闻，items 返回空数组。

输出格式要求：
你必须只输出 JSON，不要 Markdown，不要代码块，不要解释。
JSON 格式如下：
{{
  "category": "{category}",
  "title": "{section_title}",
  "items": [
    {{
      "title": "新闻短标题",
      "summary": "1-2 句话总结",
      "source": "来源名称",
      "url": "原文链接",
      "importance": "high | medium | low"
    }}
  ]
}}
"""
    else:
        system_prompt = f"""
You are a high-signal daily briefing editor for an engineering-minded reader who dislikes fluff.

Your task: read the input news list, filter, merge duplicates, and produce a structured JSON section summary.

Language requirement:
{language_instruction}

Content rules:
1. Keep only high-value updates, with at most {max_items} items.
2. Merge multiple articles about the same event. Do not repeat the same story.
3. Each summary must be 1-2 sentences.
4. Lead with the conclusion. Focus on facts, numbers, company moves, policy changes, and technical changes.
5. Do not invent facts that are not present in the input.
6. Preserve source and url.
7. If there are no valuable updates, return an empty items array.

Output format:
Return JSON only. No Markdown. No code fence. No explanation.
JSON schema:
{{
  "category": "{category}",
  "title": "{section_title}",
  "items": [
    {{
      "title": "Short news title",
      "summary": "1-2 sentence summary",
      "source": "source name",
      "url": "original URL",
      "importance": "high | medium | low"
    }}
  ]
}}
"""

    user_prompt = {
        "category": category,
        "section_title": section_title,
        "articles": compact_articles_for_prompt(articles),
    }

    messages = [
        {
            "role": "system",
            "content": system_prompt.strip()
        },
        {
            "role": "user",
            "content": json.dumps(user_prompt, ensure_ascii=False, indent=2)
        }
    ]

    return messages


# ==========================================
# 9. JSON 解析与修复
# ==========================================
def extract_json_object(text: str) -> Dict[str, Any]:
    """
    尝试从模型输出中提取 JSON object。
    兼容模型偶尔包裹 ```json 的情况。
    """
    if not text:
        raise ValueError("模型输出为空，无法解析 JSON")

    cleaned = text.strip()

    # 去掉 ```json ... ``` 包裹
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 尝试截取第一个 { 到最后一个 }
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start != -1 and end != -1 and end > start:
        possible_json = cleaned[start:end + 1]
        return json.loads(possible_json)

    raise ValueError(f"无法从模型输出中解析 JSON：{text[:500]}")


def normalize_section_json(
    section: Dict[str, Any],
    category: str,
    language: str
) -> Dict[str, Any]:
    """
    规范化模型输出，避免字段缺失导致后续渲染失败。
    """
    normalized = {
        "category": section.get("category") or category,
        "title": section.get("title") or get_section_title(category, language),
        "items": [],
    }

    raw_items = section.get("items", [])

    if not isinstance(raw_items, list):
        raw_items = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        source = str(item.get("source") or "unknown").strip()
        url = str(item.get("url") or "").strip()
        importance = str(item.get("importance") or "medium").strip().lower()

        if not title or not summary or not url:
            continue

        if importance not in {"high", "medium", "low"}:
            importance = "medium"

        normalized["items"].append({
            "title": title,
            "summary": summary,
            "source": source,
            "url": url,
            "importance": importance,
        })

    return normalized


# ==========================================
# 10. 总结主逻辑
# ==========================================
def summarize_category(
    client: OpenAI,
    category: str,
    articles: List[Dict[str, Any]],
    language: str
) -> Dict[str, Any]:
    """
    总结单个类别。
    """
    prepared_articles = prepare_category_articles(articles, category)

    if not prepared_articles:
        return {
            "category": category,
            "title": get_section_title(category, language),
            "items": [],
        }

    messages = build_category_summary_prompt(
        category=category,
        articles=prepared_articles,
        language=language
    )

    logger.info(
        "开始总结类别：%s | 语言：%s | 输入新闻：%d 条",
        category,
        language,
        len(prepared_articles)
    )

    content, finish_reason = call_deepseek(
        client=client,
        messages=messages,
        max_tokens=MAX_TOKENS_PER_CATEGORY,
        temperature=TEMPERATURE
    )

    if finish_reason == "length":
        logger.warning(
            "类别 %s | 语言 %s 的输出可能被截断。建议减少 MAX_OUTPUT_ITEMS_PER_CATEGORY 或增大 max_tokens。",
            category,
            language
        )

    section_json = extract_json_object(content)
    section_json = normalize_section_json(
        section=section_json,
        category=category,
        language=language
    )

    logger.info(
        "类别总结完成：%s | 语言：%s | 输出新闻：%d 条",
        category,
        language,
        len(section_json.get("items", []))
    )

    return section_json


def build_digest(
    sections: List[Dict[str, Any]],
    language: str,
    reader_name: str = "Nailin Wang"
) -> Dict[str, Any]:
    """
    构建完整日报 JSON。
    """
    today = datetime.now().strftime("%Y-%m-%d")

    if language == "zh":
        greeting = f"早上好，{reader_name}。今天是 {today}，以下是您的今日科技脉动。"
    else:
        greeting = f"Good morning, {reader_name}. Today is {today}. Here is your Daily Tech-Pulse."

    return {
        "language": language,
        "date": today,
        "greeting": greeting,
        "sections": sections,
    }


def summarize_digest(
    articles: List[Dict[str, Any]],
    language: str,
    reader_name: str = "Nailin Wang"
) -> Dict[str, Any]:
    """
    按类别生成完整日报。
    """
    client = get_deepseek_client()
    grouped = group_articles_by_category(articles)

    sections = []

    for category in CATEGORY_ORDER:
        category_articles = grouped.get(category, [])

        # unknown 类别没有新闻时跳过
        if category == "unknown" and not category_articles:
            continue

        section = summarize_category(
            client=client,
            category=category,
            articles=category_articles,
            language=language
        )
        sections.append(section)

    return build_digest(
        sections=sections,
        language=language,
        reader_name=reader_name
    )


# ==========================================
# 11. Markdown 预览
# ==========================================
def digest_to_markdown(digest: Dict[str, Any]) -> str:
    """
    将单个 digest JSON 转成 Markdown。
    """
    language = digest.get("language", "unknown")
    title = "中文版本" if language == "zh" else "English Version"

    lines = [
        f"# {title}",
        "",
        digest.get("greeting", ""),
        "",
    ]

    for section in digest.get("sections", []):
        lines.extend([
            f"## {section.get('title', section.get('category', 'Unknown'))}",
            "",
        ])

        items = section.get("items", [])

        if not items:
            if language == "zh":
                lines.append("今日无重要动态。")
            else:
                lines.append("No significant updates today.")
            lines.append("")
            continue

        for item in items:
            lines.append(
                f"- **{item.get('title', '').strip()}**: "
                f"{item.get('summary', '').strip()} "
                f"[🔗 Source]({item.get('url', '').strip()})"
            )

        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_combined_preview_markdown(
    zh_digest: Dict[str, Any],
    en_digest: Dict[str, Any]
) -> str:
    """
    合并中英文 Markdown 预览。
    """
    return (
        digest_to_markdown(en_digest)
        + "\n---\n\n"
        + digest_to_markdown(zh_digest)
    )


# ==========================================
# 12. 命令行测试入口
# ==========================================
if __name__ == "__main__":
    latest_input = find_latest_llm_input("exports")

    if not latest_input:
        logger.error("没有找到 exports/llm_input_*.json，请先运行 processor.py")
        raise SystemExit(1)

    logger.info("使用最新 LLM 输入文件：%s", latest_input)

    articles = load_llm_input(latest_input)

    if not articles:
        logger.warning("LLM 输入为空，程序结束。")
        raise SystemExit(0)

    en_digest = summarize_digest(
        articles=articles,
        language="en",
        reader_name="Nailin Wang"
    )

    zh_digest = summarize_digest(
        articles=articles,
        language="zh",
        reader_name="Nailin Wang"
    )

    preview_markdown = build_combined_preview_markdown(
        zh_digest=zh_digest,
        en_digest=en_digest
    )

    exported_files = export_digest_files(
        zh_digest=zh_digest,
        en_digest=en_digest,
        preview_markdown=preview_markdown,
        output_dir="exports"
    )

    print("\n✅ DeepSeek 总结完成，并已导出文件：")
    print(f"中文 JSON:       {exported_files['zh_json']}")
    print(f"英文 JSON:       {exported_files['en_json']}")
    print(f"Markdown 预览:   {exported_files['preview_markdown']}")
