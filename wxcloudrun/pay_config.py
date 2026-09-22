import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PaySettings:
    sp_appid: str
    sp_mchid: str
    sub_appid: Optional[str]
    sub_mchid: str
    login_appid: str
    login_secret: str
    pay_appid: str
    profit_appid: str
    profit_mchid: str
    profit_receiver_name: str
    merchant_serial_no: str
    private_key_pem: str
    platform_cert_pem: str
    api_v3_key: str
    payment_notify_url: str
    total_amount_fen: int
    service_fee_fen: int
    platform_serial_no: str = ""

    @classmethod
    def login_from_env(cls):
        login_appid = os.getenv("WX_LOGIN_APPID", "").strip()
        if not login_appid:
            raise RuntimeError("Missing required environment variable: WX_LOGIN_APPID")
        login_secret = os.getenv("WX_LOGIN_SECRET", "").strip()
        if not login_secret:
            raise RuntimeError("Missing required environment variable: WX_LOGIN_SECRET")
        return cls(
            sp_appid="",
            sp_mchid="",
            sub_appid=None,
            sub_mchid="",
            login_appid=login_appid,
            login_secret=login_secret,
            pay_appid="",
            profit_appid="",
            profit_mchid="",
            profit_receiver_name="",
            merchant_serial_no="",
            private_key_pem="",
            platform_cert_pem="",
            api_v3_key="",
            payment_notify_url="",
            total_amount_fen=0,
            service_fee_fen=0,
        )

    @classmethod
    def from_env(cls) -> "PaySettings":
        def required(name: str) -> str:
            value = os.getenv(name, "").strip()
            if not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return value

        def secret_text(name: str, path_name: str) -> str:
            value = os.getenv(name, "")
            if value:
                return value.replace("\\n", "\n")
            path = os.getenv(path_name, "").strip()
            if path:
                return Path(path).read_text()
            raise RuntimeError(f"Missing {name} or {path_name}")

        def mchid(name: str) -> str:
            value = required(name)
            if not value.isdigit() or not 8 <= len(value) <= 10:
                raise RuntimeError(
                    f"Environment variable {name} must be the numeric WeChat Pay "
                    "merchant ID (商户号，通常为 10 位纯数字，例如 1900000109)，"
                    f"got invalid value format"
                )
            return value

        sp_appid = required("WX_SP_APPID")
        sub_appid = os.getenv("WX_SUB_APPID", "").strip() or None
        return cls(
            sp_appid=sp_appid,
            sp_mchid=mchid("WX_SP_MCHID"),
            sub_appid=sub_appid,
            sub_mchid=mchid("WX_SUB_MCHID"),
            login_appid=os.getenv("WX_LOGIN_APPID", sub_appid or sp_appid).strip(),
            login_secret=required("WX_LOGIN_SECRET"),
            pay_appid=os.getenv("WX_PAY_APPID", sub_appid or sp_appid).strip(),
            profit_appid=os.getenv("WX_PROFIT_APPID", sp_appid).strip(),
            profit_mchid=os.getenv("WX_PROFIT_MCHID", os.getenv("WX_SP_MCHID", "")).strip(),
            profit_receiver_name=os.getenv("WX_PROFIT_RECEIVER_NAME", "").strip(),
            merchant_serial_no=required("WX_MERCHANT_SERIAL_NO"),
            private_key_pem=secret_text("WX_PRIVATE_KEY", "WX_PRIVATE_KEY_PATH"),
            platform_cert_pem=secret_text("WX_PLATFORM_CERT", "WX_PLATFORM_CERT_PATH"),
            api_v3_key=required("WX_API_V3_KEY"),
            payment_notify_url=required("WX_PAYMENT_NOTIFY_URL"),
            total_amount_fen=int(os.getenv("DEMO_TOTAL_AMOUNT_FEN", "100")),
            service_fee_fen=int(os.getenv("DEMO_SERVICE_FEE_FEN", "1")),
            platform_serial_no=os.getenv(
                "WX_PLATFORM_SERIAL_NO", os.getenv("WX_PLATFORM_PUBLIC_KEY_ID", "")
            ).strip(),
        )
