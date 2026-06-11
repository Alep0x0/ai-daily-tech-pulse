import os
import smtplib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ==========================================
# 1. 日志配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ==========================================
# 2. 邮件配置
# ==========================================
EXPORTS_DIR = "exports"

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.163.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))

SENDER_EMAIL = "alep813@163.com"       # 发件人邮箱
SENDER_AUTH_CODE = os.environ.get("SENDER_AUTH_CODE")      # ⚠️ 注意：这里填授权码，不是登录密码！

# 支持多个收件人，用英文逗号分隔：
RECEIVER_EMAILS="alep813@163.com,979239648@qq.com"
#RECEIVER_EMAILS = os.getenv("RECEIVER_EMAILS") or os.getenv("RECEIVER_EMAIL")
EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "AI Daily Tech-Pulse 晨报")

# ==========================================
# 3. 文件工具
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


def find_latest_email_html(exports_dir: str = EXPORTS_DIR) -> str:
    latest = find_latest_file("email_preview_*.html", exports_dir)

    if not latest:
        raise FileNotFoundError("没有找到 exports/email_preview_*.html，请先运行 renderer.py")

    return latest


def read_html_file(path: str) -> str:
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"找不到 HTML 文件：{path}")

    return file_path.read_text(encoding="utf-8")


# ==========================================
# 4. 配置检查
# ==========================================
def parse_receiver_emails(raw_receivers: Optional[str]) -> List[str]:
    if not raw_receivers:
        return []

    return [
        email.strip()
        for email in raw_receivers.split(",")
        if email.strip()
    ]


def validate_email_config(receiver_emails: Optional[List[str]] = None) -> Dict[str, object]:
    missing = []

    if not SMTP_SERVER:
        missing.append("SMTP_SERVER")

    if not SMTP_PORT:
        missing.append("SMTP_PORT")

    if not SENDER_EMAIL:
        missing.append("SENDER_EMAIL")

    if not SENDER_AUTH_CODE:
        missing.append("SENDER_AUTH_CODE")

    receivers = receiver_emails or parse_receiver_emails(RECEIVER_EMAILS)

    if not receivers:
        missing.append("RECEIVER_EMAILS 或 RECEIVER_EMAIL")

    if missing:
        raise RuntimeError(
            "邮件配置缺失，请设置以下环境变量："
            + ", ".join(missing)
        )

    return {
        "smtp_server": SMTP_SERVER,
        "smtp_port": SMTP_PORT,
        "sender_email": SENDER_EMAIL,
        "sender_auth_code": SENDER_AUTH_CODE,
        "receiver_emails": receivers,
    }


# ==========================================
# 5. 邮件构建
# ==========================================
def build_subject(prefix: str = EMAIL_SUBJECT_PREFIX, suffix: Optional[str] = None) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"{prefix} | {today}"

    if suffix:
        subject += f" | {suffix}"

    return subject


def build_email_message(
    sender_email: str,
    receiver_emails: List[str],
    subject: str,
    html_content: str
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = ", ".join(receiver_emails)

    plain_text = (
        "AI Daily Tech-Pulse 晨报\n\n"
        "这封邮件包含 HTML 格式内容。"
        "如果无法正常显示，请查看 HTML 预览文件。"
    )

    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    return msg


# ==========================================
# 6. 邮件发送
# ==========================================
def send_html_email(
    html_content: str,
    subject: Optional[str] = None,
    receiver_emails: Optional[List[str]] = None
) -> None:
    """
    发送 HTML 邮件。

    receiver_emails:
    - None: 使用环境变量 RECEIVER_EMAILS / RECEIVER_EMAIL
    - list[str]: 发送给指定收件人
    """
    config = validate_email_config(receiver_emails=receiver_emails)

    smtp_server = config["smtp_server"]
    smtp_port = config["smtp_port"]
    sender_email = config["sender_email"]
    sender_auth_code = config["sender_auth_code"]
    receivers = config["receiver_emails"]

    subject = subject or build_subject()

    msg = build_email_message(
        sender_email=sender_email,
        receiver_emails=receivers,
        subject=subject,
        html_content=html_content
    )

    logger.info("准备发送邮件：%s", subject)
    logger.info("SMTP 服务器：%s:%s", smtp_server, smtp_port)
    logger.info("发件人：%s", sender_email)
    logger.info("收件人：%s", ", ".join(receivers))

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_auth_code)
            server.sendmail(
                sender_email,
                receivers,
                msg.as_string()
            )

        logger.info("邮件发送成功：%s", ", ".join(receivers))

    except smtplib.SMTPAuthenticationError as e:
        logger.error("邮件认证失败。请检查邮箱账号和授权码，不是登录密码。错误：%s", e)
        raise

    except smtplib.SMTPConnectError as e:
        logger.error("无法连接 SMTP 服务器。请检查 SMTP_SERVER / SMTP_PORT。错误：%s", e)
        raise

    except smtplib.SMTPException as e:
        logger.error("SMTP 发送失败：%s", e)
        raise

    except Exception as e:
        logger.error("邮件发送失败：%s", e)
        raise


def send_html_file(
    html_path: str,
    receiver_emails: List[str],
    subject: Optional[str] = None
) -> None:
    html_content = read_html_file(html_path)

    send_html_email(
        html_content=html_content,
        subject=subject,
        receiver_emails=receiver_emails
    )


def send_latest_email_preview(exports_dir: str = EXPORTS_DIR) -> str:
    html_path = find_latest_email_html(exports_dir)
    logger.info("使用最新 HTML 邮件文件：%s", html_path)

    html_content = read_html_file(html_path)
    send_html_email(html_content)

    return html_path


# ==========================================
# 7. 命令行测试入口
# ==========================================
if __name__ == "__main__":
    sent_file = send_latest_email_preview(EXPORTS_DIR)

    print("\n✅ 邮件发送完成！")
    print(f"已发送 HTML 文件: {sent_file}")
