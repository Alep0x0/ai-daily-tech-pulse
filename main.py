import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List


# ==========================================
# 1. 日志配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ==========================================
# 2. 导入项目模块
# ==========================================
try:
    from crawler import (
        RSS_FEEDS_BY_CATEGORY,
        MAX_ARTICLES_PER_CATEGORY,
        MAX_TOTAL_ARTICLES,
        fetch_daily_articles_by_category,
        export_articles,
    )
except ImportError:
    from crawler import (
        RSS_FEEDS_BY_CATEGORY,
        MAX_ARTICLES_PER_CATEGORY,
        MAX_TOTAL_ARTICLES,
        fetch_daily_articles_by_category,
        export_articles,
    )

from processor import (
    CATEGORY_LIMITS,
    MAX_TOTAL_ARTICLES as PROCESSOR_MAX_TOTAL_ARTICLES,
    process_articles,
    export_llm_input,
)

from summarizer import (
    summarize_digest,
    build_combined_preview_markdown,
    export_digest_files,
)

from renderer import (
    export_dual_layout_emails,
)

from mailer import (
    send_html_file,
    build_subject,
)


# ==========================================
# 3. 主流程配置
# ==========================================
DEFAULT_EXPORTS_DIR = "exports"
DEFAULT_TIME_WINDOW_HOURS = 24

# 收件人布局规则
STACKED_RECIPIENTS = ["alep813@163.com"]
SIDE_BY_SIDE_RECIPIENTS = ["979239648@qq.com"]


# ==========================================
# 4. 单步流程函数
# ==========================================
def step_crawl(
    time_window_hours: int = DEFAULT_TIME_WINDOW_HOURS,
    exports_dir: str = DEFAULT_EXPORTS_DIR
) -> List[Any]:
    logger.info("========== Step 1/5: 抓取新闻 ==========")

    articles = fetch_daily_articles_by_category(
        rss_feeds_by_category=RSS_FEEDS_BY_CATEGORY,
        max_articles_per_category=MAX_ARTICLES_PER_CATEGORY,
        time_window_hours=time_window_hours,
        max_total_articles=MAX_TOTAL_ARTICLES,
    )

    if not articles:
        raise RuntimeError("抓取结果为空，流程终止。")

    exported_files = export_articles(
        articles=articles,
        output_dir=exports_dir
    )

    logger.info("抓取完成：%d 条新闻", len(articles))
    logger.info("原始 Markdown 预览：%s", exported_files.get("markdown"))
    logger.info("原始 JSON 文件：%s", exported_files.get("json"))
    logger.info("原始 CSV 文件：%s", exported_files.get("csv"))

    return articles


def step_process(
    articles: List[Any],
    exports_dir: str = DEFAULT_EXPORTS_DIR
) -> List[Dict[str, Any]]:
    logger.info("========== Step 2/5: 预处理新闻 ==========")

    llm_input = process_articles(
        articles=articles,
        category_limits=CATEGORY_LIMITS,
        max_total_articles=PROCESSOR_MAX_TOTAL_ARTICLES,
    )

    if not llm_input:
        raise RuntimeError("预处理后新闻为空，流程终止。")

    exported_files = export_llm_input(
        llm_input=llm_input,
        output_dir=exports_dir
    )

    logger.info("预处理完成：%d 条新闻进入 LLM", len(llm_input))
    logger.info("LLM JSON 输入文件：%s", exported_files.get("json"))
    logger.info("LLM Markdown 预览：%s", exported_files.get("markdown"))

    return llm_input


def step_summarize(
    llm_input: List[Dict[str, Any]],
    exports_dir: str = DEFAULT_EXPORTS_DIR,
    reader_name: str = "Nailin Wang"
) -> Dict[str, Dict[str, Any]]:
    logger.info("========== Step 3/5: 生成中英文日报 ==========")

    en_digest = summarize_digest(
        articles=llm_input,
        language="en",
        reader_name=reader_name,
    )

    zh_digest = summarize_digest(
        articles=llm_input,
        language="zh",
        reader_name=reader_name,
    )

    preview_markdown = build_combined_preview_markdown(
        zh_digest=zh_digest,
        en_digest=en_digest,
    )

    exported_files = export_digest_files(
        zh_digest=zh_digest,
        en_digest=en_digest,
        preview_markdown=preview_markdown,
        output_dir=exports_dir,
    )

    logger.info("日报总结完成")
    logger.info("中文 JSON：%s", exported_files.get("zh_json"))
    logger.info("英文 JSON：%s", exported_files.get("en_json"))
    logger.info("Markdown 预览：%s", exported_files.get("preview_markdown"))

    return {
        "zh": zh_digest,
        "en": en_digest,
    }


def step_render_dual_layouts(
    digests: Dict[str, Dict[str, Any]],
    exports_dir: str = DEFAULT_EXPORTS_DIR
) -> Dict[str, Dict[str, str]]:
    logger.info("========== Step 4/5: 渲染两种 HTML 邮件 ==========")

    exported_files = export_dual_layout_emails(
        en_digest=digests["en"],
        zh_digest=digests["zh"],
        output_dir=exports_dir,
    )

    logger.info("上英下中 HTML：%s", exported_files["stacked"]["html"])
    logger.info("左右双栏 HTML：%s", exported_files["side_by_side"]["html"])

    return exported_files


def step_send_dual_layouts(email_files: Dict[str, Dict[str, str]]) -> None:
    logger.info("========== Step 5/5: 按收件人发送不同版式 ==========")

    stacked_subject = build_subject(suffix="Stacked")
    side_subject = build_subject(suffix="Side-by-side")

    send_html_file(
        html_path=email_files["stacked"]["html"],
        receiver_emails=STACKED_RECIPIENTS,
        subject=stacked_subject,
    )

    send_html_file(
        html_path=email_files["side_by_side"]["html"],
        receiver_emails=SIDE_BY_SIDE_RECIPIENTS,
        subject=side_subject,
    )

    logger.info("两种版式邮件发送完成。")


# ==========================================
# 5. 总流程
# ==========================================
def run_pipeline(
    time_window_hours: int = DEFAULT_TIME_WINDOW_HOURS,
    exports_dir: str = DEFAULT_EXPORTS_DIR,
    reader_name: str = "Nailin Wang, Zilong Jiao",
    send_email: bool = True
) -> Dict[str, Any]:
    Path(exports_dir).mkdir(parents=True, exist_ok=True)

    logger.info("🚀 AI Daily Tech-Pulse 流程启动")
    logger.info("时间窗口：过去 %d 小时", time_window_hours)
    logger.info("导出目录：%s", exports_dir)
    logger.info("是否发送邮件：%s", "是" if send_email else "否")

    articles = step_crawl(
        time_window_hours=time_window_hours,
        exports_dir=exports_dir,
    )

    llm_input = step_process(
        articles=articles,
        exports_dir=exports_dir,
    )

    digests = step_summarize(
        llm_input=llm_input,
        exports_dir=exports_dir,
        reader_name=reader_name,
    )

    email_files = step_render_dual_layouts(
        digests=digests,
        exports_dir=exports_dir,
    )

    if send_email:
        step_send_dual_layouts(email_files)
    else:
        logger.info("已跳过邮件发送。")
        logger.info("上英下中预览：%s", email_files["stacked"]["html"])
        logger.info("左右双栏预览：%s", email_files["side_by_side"]["html"])

    logger.info("✅ AI Daily Tech-Pulse 流程结束")

    return {
        "articles_count": len(articles),
        "llm_input_count": len(llm_input),
        "stacked_html": email_files["stacked"]["html"],
        "side_by_side_html": email_files["side_by_side"]["html"],
        "sent": send_email,
    }


# ==========================================
# 6. 命令行参数
# ==========================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Daily Tech-Pulse 新闻日报流水线"
    )

    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_TIME_WINDOW_HOURS,
        help="抓取过去多少小时内的新闻，默认 24"
    )

    parser.add_argument(
        "--exports-dir",
        type=str,
        default=DEFAULT_EXPORTS_DIR,
        help="导出文件夹，默认 exports"
    )

    parser.add_argument(
        "--reader-name",
        type=str,
        default="Nailin Wang",
        help="日报问候中的读者名字"
    )

    parser.add_argument(
        "--no-send",
        action="store_true",
        help="只生成预览文件，不发送邮件"
    )

    return parser.parse_args()


# ==========================================
# 7. 命令行入口
# ==========================================
if __name__ == "__main__":
    args = parse_args()

    try:
        result = run_pipeline(
            time_window_hours=args.hours,
            exports_dir=args.exports_dir,
            reader_name=args.reader_name,
            send_email=not args.no_send,
        )

        print("\n✅ 全流程运行完成！")
        print(f"抓取新闻数: {result['articles_count']}")
        print(f"进入 LLM 新闻数: {result['llm_input_count']}")
        print(f"上英下中 HTML: {result['stacked_html']}")
        print(f"左右双栏 HTML: {result['side_by_side_html']}")
        print(f"是否已发送邮件: {'是' if result['sent'] else '否'}")

    except Exception as e:
        logger.exception("流程运行失败：%s", e)
        print(f"\n❌ 流程运行失败：{e}")
        sys.exit(1)
