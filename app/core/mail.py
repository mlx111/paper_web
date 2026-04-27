import builtins

from settings.url import (
    MAIL_FROM,
    MAIL_FROM_NAME,
    MAIL_PASSWORD,
    MAIL_PORT,
    MAIL_SERVER,
    MAIL_SSL_TLS,
    MAIL_STARTTLS,
    MAIL_USERNAME,
)


def _patch_fastapi_mail_compat() -> None:
    """兼容 fastapi-mail 1.5.2 在部分环境下漏导入 SecretStr 的问题."""

    if not hasattr(builtins, "SecretStr"):
        from pydantic import SecretStr

        builtins.SecretStr = SecretStr


def create_mail_instance():
    _patch_fastapi_mail_compat()
    from fastapi_mail import ConnectionConfig, FastMail
    from pydantic import SecretStr

    conf = ConnectionConfig(
        MAIL_USERNAME=MAIL_USERNAME,
        MAIL_PASSWORD=SecretStr(MAIL_PASSWORD),
        MAIL_FROM=MAIL_FROM,
        MAIL_PORT=MAIL_PORT,
        MAIL_SERVER=MAIL_SERVER,
        MAIL_SSL_TLS=MAIL_SSL_TLS,
        MAIL_STARTTLS=MAIL_STARTTLS,
        MAIL_FROM_NAME=MAIL_FROM_NAME,
        LOCAL_HOSTNAME="localhost",
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True,
    )
    return FastMail(conf)
