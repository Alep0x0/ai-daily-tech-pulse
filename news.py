import smtplib

from openai import OpenAI
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import feedparser
import time
import calendar
import markdown

from datetime import datetime


# ==========================================
# 1. 配置区 (Configuration)
# ==========================================
# 替换为你的 DeepSeek API Key
DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"

# 这里填入我们第一阶段筛选出的 RSS 源链接 (以下为示例)
RSS_FEEDS = [
    "https://news.ycombinator.com/rss",  # Hacker News
    "https://www.ithome.com/rss/", #IT之家
    "https://openai.com/blog/rss.xml", # OPEN AI

    "https://deepmind.google/blog/rss.xml", # GEMINI
    "https://blog.google/technology/ai/rss/",

    "https://feeds.arstechnica.com/arstechnica/index", # Ars Technica
    "https://quanwenrss.com/bloomberg",
    "https://quanwenrss.com/caixin",

    "https://www.technologyreview.com/feed/", # MIT Technology Review
    "http://feeds.marketwatch.com/marketwatch/topstories/",
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://quanwenrss.com/ft",
    "https://quanwenrss.com/nytime",

    "https://plink.anyfeeder.com/zaobao/realtime/china", # 联合早报-国内局势
    "https://plink.anyfeeder.com/zaobao/realtime/world", # 联合早报-国际局势


    "https://news.google.com/rss/search?q=OpenAI+OR+Tesla+OR+Apple+OR+Google+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=NVIDIA+OR+TSMC+OR+ASML+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=SpaceX+OR+CATL+OR+BYD+OR+Boston+Dynamics+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=Microsoft+OR+Meta+Llama+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://www.economist.com/finance-and-economics/rss.xml"
    # "https://rsshub.app/36kr/newsflashes"   # 36氪快讯 (需通过 RSSHub)
]


# ==========================================
# 2. 数据抓取层 (Data Fetcher)
# ==========================================
def fetch_daily_news(rss_urls):
    print("🔄 正在过滤并抓取过去 24 小时内的核心新闻...")
    all_news_text = ""

    # 获取当前时间的 UTC 时间戳 (因为大多数 RSS 的时间标准是 UTC)
    current_timestamp = time.time()
    # 24 小时 = 86400 秒
    time_window = 86400

    for url in rss_urls:
        feed = feedparser.parse(url)

        # 统计一下每个源抓了多少条，方便你在终端看运行状态
        fetched_count = 0

        for entry in feed.entries:
            # 1. 安全检查：确保这条新闻有时间戳
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                # 将 RSS 的结构化时间转换为 UTC 时间戳
                entry_timestamp = calendar.timegm(entry.published_parsed)

                # 2. 核心逻辑：计算新闻发布时间与现在的差值
                if (current_timestamp - entry_timestamp) <= time_window:
                    title = entry.get('title', '无标题')
                    summary = entry.get('summary', '')
                    # 【新增】抓取新闻的原始链接
                    link = entry.get('link', '无链接')

                    # 将链接一并拼接到生肉文本中，告诉 AI 它的源地址
                    all_news_text += f"【原文链接】: {link}\n标题: {title}\n摘要: {summary}\n\n"
                    fetched_count += 1
            else:
                # 如果极个别小众网站的 RSS 不提供时间，为了不漏掉信息，默认放行前 3 条
                pass

        print(f"📡 从 {url} 成功提取了 {fetched_count} 条 24H 内的新闻。")

    return all_news_text


# ==========================================
# 3. AI 处理层 (DeepSeek Engine)
# ==========================================
def generate_ai_summary(news_text):
    print("🧠 正在呼叫 DeepSeek 大脑进行总结计算...")


    # 初始化客户端，指向 DeepSeek 的服务器
    client = OpenAI(
        api_key='sk-c4a4c4fb8a814b8f865cda00bcf3452a',
        base_url="https://api.deepseek.com/v1"
    )

    # 获取今天格式化的日期，例如：April 29, 2026
    today_date = datetime.now().strftime("%B %d, %Y")

    # 核心 Prompt 设计：规定工科生视角的输出格式
    system_prompt = f"""
        # Role
        你是一位以“高信噪比”著称的资深科技与政经主编，专门为具备强逻辑思维、极其反感废话的“硬核工科生” Nailin Wang 撰写每日晨报。

        # Task
        请阅读以下从全球 RSS 源抓取的生肉新闻文本，进行深度清洗、去重、结构化重组，并生成一份高质量的【中英双语】每日简报。

        # Workflow & Rules
        1. 【专属问候】：在全文的最开头，你必须生成问候语，格式严格遵循：“**Good morning, Nailin Wang. Today is {today_date}. Here is your Daily Tech-Pulse.**”（中文版开头请输出：“**早上好，Nailin Wang。今天是 {today_date}，以下是您的今日科技脉动。**”）

        2. 【极致降噪】：强制剔除公关套话、名人八卦、未证实的传闻及情绪化表达。对同一事件的多篇报道必须合并提炼。

        3. 【双轨结构输出】：
           - 优先输出 **Part 1: English Version**。这部分必须将所有新闻汇总为纯英文，绝对禁止出现任何中文字符。
           - 随后输出 **Part 2: 中文版本**。这部分将上述新闻输出为纯中文格式。

        4. 【模块归类】：中英两部分均需严格按以下三个板块进行组织：
           - 🚀 硬核科技与 AI / Hardcore Tech & AI（侧重技术参数、底层基建、模型迭代与工程突破）
           - 💰 宏观商业与巨头 / Macro Business & Giants（侧重核心财务数据、产业链变动与巨头战略决策）
           - 🌍 全球局势 / Global Affairs（侧重地缘核心事实、科技制裁法案与宏观经济指标）

        5. 【极简输出与溯源保留】：严格遵循“结论先行”原则。每条新闻限制在 1-2 句话以内，必须用客观数据或具体事实支撑，禁止使用夸张形容词。**极其重要：你必须在每条新闻总结的末尾，附上生肉文本中对应的【原文链接】。**

        # Format Requirements
        - 严格使用 Markdown 格式排版。
        - 必须将新闻中的**核心数据**、**技术专有名词**和**公司/机构名称**进行加粗处理。
        - 新闻条目的超链接渲染请严格遵循以下格式：
          - 英文版示例：* **Apple:** Released a new AI model with 10B parameters. [🔗 Source](对应的原文链接)
          - 中文版示例：* **苹果:** 发布了具备百亿参数的新型AI模型。[🔗 原文链接](对应的原文链接)
        - 如果当日某板块无高价值新闻，英文板块请输出“No significant updates today.”，中文板块请输出“今日无重要动态”。
        """

    response = client.chat.completions.create(
        model="deepseek-v4-flash",  # 或者使用 deepseek-reasoner
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"以下是今天的生肉新闻资讯，请总结：\n{news_text}"}
        ],
        temperature=0.3,  # 偏向冷静客观
        max_tokens=8000
    )

    return response.choices[0].message.content

# ==========================================
# 4. 邮件配置区 (Configuration)
# ==========================================
# 这里以网易 163 邮箱为例，QQ 邮箱的 server 是 smtp.qq.com
SMTP_SERVER = "smtp.163.com"
SMTP_PORT = 465               # SSL 加密端口通常是 465

SENDER_EMAIL = "alep813@163.com"       # 发件人邮箱
SENDER_AUTH_CODE = "LQZfYN3xZfctZ8AZ"     # ⚠️ 注意：这里填授权码，不是登录密码！

RECEIVER_EMAIL = "alep813@163.com"     # 收件人邮箱（可以发给自己）

# ==========================================
# 5. 邮件发送逻辑
# ==========================================
def send_daily_report(markdown_content):
    print("📧 正在将晨报打包发送至邮箱...")

    # 1. 获取今天的日期，用于生成邮件标题
    today_str = datetime.now().strftime("%Y-%m-%d")
    subject = f"AI Daily Tech-Pulse 晨报 | {today_str}"

    # 2. 将 Markdown 转换为 HTML
    # extensions=['extra'] 可以更好地支持表格和复杂排版
    html_content = markdown.markdown(markdown_content, extensions=['extra'])

    # 3. 注入 CSS 样式，让邮件看起来像一份精美的杂志
    html_body = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; padding: 20px; }}
          h1, h2, h3 {{ color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
          a {{ color: #3498db; text-decoration: none; font-weight: bold; }}
          a:hover {{ text-decoration: underline; }}
          strong {{ color: #e74c3c; }}
          li {{ margin-bottom: 10px; }}
        </style>
      </head>
      <body>
        {html_content}
      </body>
    </html>
    """

    # 4. 构建邮件主体
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL

    # 将 HTML 内容附加到邮件中
    part = MIMEText(html_body, 'html', 'utf-8')
    msg.attach(part)

    # 5. 连接服务器并发送
    try:
        # 使用 SSL 安全连接
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SENDER_EMAIL, SENDER_AUTH_CODE)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        print(f"✅ 邮件发送成功！请查收: {RECEIVER_EMAIL}")
    except Exception as e:
        print(f"❌ 邮件发送失败，请检查配置或网络。错误信息: {e}")


# ==========================================
# 主运行逻辑
# ==========================================
if __name__ == "__main__":
    if __name__ == "__main__":
        print("🚀 正在启动 AI Daily Tech-Pulse 晨报引擎...")

        # 1. 抓取生肉文本
        raw_news = fetch_daily_news(RSS_FEEDS)

