from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from settings.url import MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM, MAIL_PORT, MAIL_SERVER, MAIL_SSL_TLS, MAIL_STARTTLS,MAIL_FROM_NAME


from pydantic import EmailStr, BaseModel,SecretStr

def create_mail_instance():
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
        VALIDATE_CERTS=True
    )
    return FastMail(conf)