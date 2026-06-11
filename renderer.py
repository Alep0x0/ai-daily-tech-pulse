import html
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ==========================================
# 1. 日志配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ==========================================
# 2. 渲染配置
# ==========================================
EXPORTS_DIR = "exports"

CATEGORY_ORDER = [
    "tech_ai",
    "frontier_companies",
    "finance_business",
    "global_affairs",
    "unknown",
]

CATEGORY_EMOJIS = {
    "tech_ai": "🚀",
    "frontier_companies": "🧠",
    "finance_business": "💰",
    "global_affairs": "🌍",
    "unknown": "🗂️",
}

LANGUAGE_LABELS = {
    "en": "English Version",
    "zh": "中文版本",
}

EMPTY_SECTION_TEXT = {
    "en": "No significant updates today.",
    "zh": "今日无重要动态。",
}


# ==========================================
# 3. 文件读取工具
# ==========================================
def find_latest_file(pattern: str, exports_dir: str = EXPORTS_DIR) -> Optional[str]:
    path = Path(exports_dir)

    if not path.exists():
        return None

    candidates = sorted(
        path.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if not candidates:
        return None

    return str(candidates[0])


def find_latest_digest_files(exports_dir: str = EXPORTS_DIR) -> Tuple[str, str]:
    zh_path = find_latest_file("digest_zh_*.json", exports_dir)
    en_path = find_latest_file("digest_en_*.json", exports_dir)

    if not zh_path:
        raise FileNotFoundError("没有找到 digest_zh_*.json，请先运行 summarizer.py")

    if not en_path:
        raise FileNotFoundError("没有找到 digest_en_*.json，请先运行 summarizer.py")

    return zh_path, en_path


def load_digest(path: str) -> Dict[str, Any]:
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"找不到 digest 文件：{path}")

    data = json.loads(file_path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError(f"digest 文件格式错误，必须是 dict：{path}")

    return data


# ==========================================
# 4. HTML 工具函数
# ==========================================
def escape_text(value: Any) -> str:
    if value is None:
        return ""

    return html.escape(str(value), quote=True)


def safe_url(value: Any) -> str:
    if value is None:
        return ""

    url = str(value).strip()

    if not url.startswith(("http://", "https://")):
        return ""

    return html.escape(url, quote=True)


def importance_badge(importance: str) -> str:
    importance = (importance or "medium").lower()

    label_map = {
        "high": "HIGH",
        "medium": "MED",
        "low": "LOW",
    }

    label = label_map.get(importance, "MED")

    return (
        '<span style="'
        'display:inline-block;'
        'font-size:10px;'
        'font-weight:700;'
        'letter-spacing:0.3px;'
        'padding:2px 6px;'
        'border:1px solid #d0d7de;'
        'border-radius:999px;'
        'color:#57606a;'
        'background:#f6f8fa;'
        'vertical-align:middle;'
        f'">{label}</span>'
    )


def source_link(url: str, language: str) -> str:
    url = safe_url(url)

    if not url:
        return ""

    label = "Source" if language == "en" else "原文"
    return (
        f'<a href="{url}" '
        'style="color:#0969da;text-decoration:none;font-weight:600;" '
        'target="_blank" rel="noopener noreferrer">'
        f'🔗 {label}</a>'
    )


# ==========================================
# 5. Digest 规范化
# ==========================================
def normalize_digest(digest: Dict[str, Any]) -> Dict[str, Any]:
    language = digest.get("language") or "unknown"

    normalized = {
        "language": language,
        "date": digest.get("date") or datetime.now().strftime("%Y-%m-%d"),
        "greeting": digest.get("greeting") or "",
        "sections": [],
    }

    sections = digest.get("sections", [])

    if not isinstance(sections, list):
        sections = []

    for section in sections:
        if not isinstance(section, dict):
            continue

        category = section.get("category") or "unknown"
        title = section.get("title") or category
        items = section.get("items", [])

        if not isinstance(items, list):
            items = []

        normalized_items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            normalized_items.append({
                "title": item.get("title") or "",
                "summary": item.get("summary") or "",
                "source": item.get("source") or "unknown",
                "url": item.get("url") or "",
                "importance": item.get("importance") or "medium",
            })

        normalized["sections"].append({
            "category": category,
            "title": title,
            "items": normalized_items,
        })

    normalized["sections"] = sort_sections(normalized["sections"])
    return normalized


def sort_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    order_map = {category: index for index, category in enumerate(CATEGORY_ORDER)}

    return sorted(
        sections,
        key=lambda section: order_map.get(section.get("category", "unknown"), 999)
    )


# ==========================================
# 6. HTML 渲染：单语言内容
# ==========================================
def render_digest_section(section: Dict[str, Any], language: str, compact: bool = False) -> str:
    category = section.get("category", "unknown")
    emoji = CATEGORY_EMOJIS.get(category, "🗂️")
    title = escape_text(section.get("title", category))
    items = section.get("items", [])

    h2_size = "17px" if compact else "20px"
    item_title_size = "14px" if compact else "16px"
    summary_size = "13px" if compact else "14px"
    item_padding = "12px 13px" if compact else "14px 16px"

    section_html = [
        '<section style="margin:24px 0;">',
        (
            '<h2 style="'
            f'font-size:{h2_size};'
            'line-height:1.35;'
            'margin:0 0 12px 0;'
            'padding-bottom:7px;'
            'border-bottom:1px solid #d8dee4;'
            'color:#24292f;'
            '">'
            f'{emoji} {title}'
            '</h2>'
        )
    ]

    if not items:
        empty_text = EMPTY_SECTION_TEXT.get(language, "No significant updates today.")
        section_html.append(
            '<p style="margin:0;color:#6e7781;font-size:13px;">'
            f'{escape_text(empty_text)}'
            '</p>'
        )
        section_html.append("</section>")
        return "\n".join(section_html)

    section_html.append('<ul style="padding-left:0;margin:0;list-style:none;">')

    for item in items:
        item_title = escape_text(item.get("title", ""))
        summary = escape_text(item.get("summary", ""))
        source = escape_text(item.get("source", "unknown"))
        url = item.get("url", "")
        importance = item.get("importance", "medium")

        section_html.append(
            '<li style="'
            'margin:0 0 13px 0;'
            f'padding:{item_padding};'
            'border:1px solid #d8dee4;'
            'border-radius:11px;'
            'background:#ffffff;'
            '">'
        )

        section_html.append(
            '<div style="margin-bottom:7px;">'
            f'{importance_badge(importance)} '
            f'<strong style="font-size:{item_title_size};line-height:1.45;color:#24292f;">{item_title}</strong>'
            '</div>'
        )

        section_html.append(
            '<p style="'
            'margin:0 0 9px 0;'
            f'font-size:{summary_size};'
            'line-height:1.62;'
            'color:#3b434b;'
            '">'
            f'{summary}'
            '</p>'
        )

        section_html.append(
            '<div style="font-size:12px;line-height:1.5;color:#6e7781;">'
            f'<span>Source: {source}</span>'
            f' · {source_link(url, language)}'
            '</div>'
        )

        section_html.append("</li>")

    section_html.append("</ul>")
    section_html.append("</section>")

    return "\n".join(section_html)


def render_single_language_digest(digest: Dict[str, Any], compact: bool = False) -> str:
    digest = normalize_digest(digest)

    language = digest.get("language", "unknown")
    label = LANGUAGE_LABELS.get(language, language)
    greeting = escape_text(digest.get("greeting", ""))
    date = escape_text(digest.get("date", ""))

    h1_size = "22px" if compact else "26px"

    html_parts = [
        '<div>',
        (
            '<h1 style="'
            f'font-size:{h1_size};'
            'line-height:1.25;'
            'margin:0 0 8px 0;'
            'color:#111827;'
            '">'
            f'{escape_text(label)}'
            '</h1>'
        ),
        (
            '<p style="'
            'margin:0 0 6px 0;'
            'font-size:14px;'
            'line-height:1.65;'
            'color:#3b434b;'
            '">'
            f'{greeting}'
            '</p>'
        ),
        (
            '<p style="'
            'margin:0 0 18px 0;'
            'font-size:12px;'
            'color:#6e7781;'
            '">'
            f'Date: {date}'
            '</p>'
        )
    ]

    for section in digest.get("sections", []):
        html_parts.append(render_digest_section(section, language, compact=compact))

    html_parts.append("</div>")

    return "\n".join(html_parts)


# ==========================================
# 7. 两种 HTML 布局
# ==========================================
def render_header() -> str:
    return """
<tr>
  <td style="padding:28px 28px 18px 28px;background:#0f172a;">
    <h1 style="margin:0;font-size:28px;line-height:1.25;color:#ffffff;">
      AI Daily Tech-Pulse
    </h1>
    <p style="margin:8px 0 0 0;font-size:14px;line-height:1.6;color:#cbd5e1;">
      Bilingual high-signal briefing on tech, finance, and global affairs.
    </p>
  </td>
</tr>
"""


def render_footer(generated_at: str) -> str:
    return f"""
<tr>
  <td style="padding:18px 28px;background:#f6f8fa;border-top:1px solid #d8dee4;">
    <p style="margin:0;font-size:12px;line-height:1.6;color:#6e7781;">
      Generated at {html.escape(generated_at)}. This briefing was automatically generated from RSS sources and summarized by AI. Please verify critical information before making decisions.
    </p>
  </td>
</tr>
"""


def wrap_email_body(inner_rows: str, max_width: int = 880) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>AI Daily Tech-Pulse</title>
</head>
<body style="margin:0;padding:0;background:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,'Noto Sans',sans-serif;color:#24292f;">
  <div style="display:none;max-height:0;overflow:hidden;color:transparent;">
    AI Daily Tech-Pulse bilingual briefing.
  </div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f6f8fa;margin:0;padding:0;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:{max_width}px;background:#ffffff;border:1px solid #d8dee4;border-radius:18px;overflow:hidden;">
          {inner_rows}
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def render_stacked_email_html(en_digest: Dict[str, Any], zh_digest: Dict[str, Any]) -> str:
    """
    上英文，下中文。适合发给 alep813。
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    en_html = render_single_language_digest(en_digest, compact=False)
    zh_html = render_single_language_digest(zh_digest, compact=False)

    rows = (
        render_header()
        + f"""
<tr>
  <td style="padding:28px;">
    {en_html}

    <hr style="border:none;border-top:1px solid #d8dee4;margin:34px 0;">

    {zh_html}
  </td>
</tr>
"""
        + render_footer(generated_at)
    )

    return wrap_email_body(rows, max_width=880)


def render_side_by_side_email_html(en_digest: Dict[str, Any], zh_digest: Dict[str, Any]) -> str:
    """
    左英文，右中文。适合发给 QQ 邮箱。
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    en_html = render_single_language_digest(en_digest, compact=True)
    zh_html = render_single_language_digest(zh_digest, compact=True)

    header = """
<tr>
  <td colspan="2" style="padding:28px 28px 18px 28px;background:#0f172a;">
    <h1 style="margin:0;font-size:28px;line-height:1.25;color:#ffffff;">
      AI Daily Tech-Pulse
    </h1>
    <p style="margin:8px 0 0 0;font-size:14px;line-height:1.6;color:#cbd5e1;">
      Bilingual high-signal briefing on tech, finance, and global affairs.
    </p>
  </td>
</tr>
"""

    footer = f"""
<tr>
  <td colspan="2" style="padding:18px 28px;background:#f6f8fa;border-top:1px solid #d8dee4;">
    <p style="margin:0;font-size:12px;line-height:1.6;color:#6e7781;">
      Generated at {html.escape(generated_at)}. This briefing was automatically generated from RSS sources and summarized by AI. Please verify critical information before making decisions.
    </p>
  </td>
</tr>
"""

    rows = (
        header
        + f"""
<tr>
  <td width="50%" valign="top" style="padding:26px 20px 28px 28px;border-right:1px solid #d8dee4;background:#ffffff;">
    {en_html}
  </td>

  <td width="50%" valign="top" style="padding:26px 28px 28px 20px;background:#ffffff;">
    {zh_html}
  </td>
</tr>
"""
        + footer
    )

    return wrap_email_body(rows, max_width=1180)


def render_email_html(en_digest: Dict[str, Any], zh_digest: Dict[str, Any], layout: str = "stacked") -> str:
    """
    layout:
    - stacked: 上英文，下中文
    - side_by_side: 左英文，右中文
    """
    if layout == "stacked":
        return render_stacked_email_html(en_digest, zh_digest)

    if layout == "side_by_side":
        return render_side_by_side_email_html(en_digest, zh_digest)

    raise ValueError(f"不支持的布局：{layout}")


# 为了兼容旧 main.py 里调用的函数名，默认返回左右版
def render_full_email_html(en_digest: Dict[str, Any], zh_digest: Dict[str, Any]) -> str:
    return render_side_by_side_email_html(en_digest, zh_digest)


# ==========================================
# 8. Markdown 渲染
# ==========================================
def render_digest_markdown(digest: Dict[str, Any]) -> str:
    digest = normalize_digest(digest)

    language = digest.get("language", "unknown")
    label = LANGUAGE_LABELS.get(language, language)

    lines = [
        f"# {label}",
        "",
        digest.get("greeting", ""),
        "",
    ]

    for section in digest.get("sections", []):
        category = section.get("category", "unknown")
        emoji = CATEGORY_EMOJIS.get(category, "🗂️")
        title = section.get("title", category)

        lines.extend([
            f"## {emoji} {title}",
            "",
        ])

        items = section.get("items", [])

        if not items:
            lines.append(EMPTY_SECTION_TEXT.get(language, "No significant updates today."))
            lines.append("")
            continue

        for item in items:
            title = item.get("title", "")
            summary = item.get("summary", "")
            url = item.get("url", "")
            source = item.get("source", "unknown")
            importance = item.get("importance", "medium")

            lines.append(
                f"- **[{importance.upper()}] {title}**: {summary} "
                f"({source}) [🔗 Source]({url})"
            )

        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_full_markdown(en_digest: Dict[str, Any], zh_digest: Dict[str, Any]) -> str:
    return (
        render_digest_markdown(en_digest)
        + "\n---\n\n"
        + render_digest_markdown(zh_digest)
    )


# ==========================================
# 9. 导出文件
# ==========================================
def export_email_render(
    html_content: str,
    markdown_content: str,
    output_dir: str = EXPORTS_DIR,
    layout: str = "default"
) -> Dict[str, str]:
    export_dir = Path(output_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    html_path = export_dir / f"email_preview_{layout}_{timestamp}.html"
    markdown_path = export_dir / f"email_preview_{layout}_{timestamp}.md"

    html_path.write_text(html_content, encoding="utf-8")
    markdown_path.write_text(markdown_content, encoding="utf-8")

    return {
        "html": str(html_path),
        "markdown": str(markdown_path),
    }


def export_dual_layout_emails(
    en_digest: Dict[str, Any],
    zh_digest: Dict[str, Any],
    output_dir: str = EXPORTS_DIR
) -> Dict[str, Dict[str, str]]:
    stacked_html = render_stacked_email_html(en_digest, zh_digest)
    side_html = render_side_by_side_email_html(en_digest, zh_digest)
    markdown_content = render_full_markdown(en_digest, zh_digest)

    stacked_files = export_email_render(
        html_content=stacked_html,
        markdown_content=markdown_content,
        output_dir=output_dir,
        layout="stacked"
    )

    side_files = export_email_render(
        html_content=side_html,
        markdown_content=markdown_content,
        output_dir=output_dir,
        layout="side_by_side"
    )

    return {
        "stacked": stacked_files,
        "side_by_side": side_files,
    }


def render_latest_digest_to_email(exports_dir: str = EXPORTS_DIR) -> Dict[str, Dict[str, str]]:
    zh_path, en_path = find_latest_digest_files(exports_dir)

    logger.info("使用中文 digest：%s", zh_path)
    logger.info("使用英文 digest：%s", en_path)

    zh_digest = load_digest(zh_path)
    en_digest = load_digest(en_path)

    return export_dual_layout_emails(
        en_digest=en_digest,
        zh_digest=zh_digest,
        output_dir=exports_dir
    )


# ==========================================
# 10. 命令行测试入口
# ==========================================
if __name__ == "__main__":
    exported_files = render_latest_digest_to_email(EXPORTS_DIR)

    print("\n✅ 两种邮件 HTML 渲染完成，并已导出文件：")
    print(f"上英下中 HTML: {exported_files['stacked']['html']}")
    print(f"左右双栏 HTML: {exported_files['side_by_side']['html']}")
