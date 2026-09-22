import base64
import json
import logging
import os
import re
import secrets
import time
from typing import Any, Dict, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509 import load_pem_x509_certificate

from wxcloudrun.pay_config import PaySettings


logger = logging.getLogger(__name__)


class WeChatAPIError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"WeChat API {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class WeChatPay:
    API_BASE = "https://api.mch.weixin.qq.com"

    def __init__(self, settings: PaySettings):
        self.settings = settings
        self._private_key = None
        self._wechat_public_key = None
        self._wechat_platform_serial_no = None

    @staticmethod
    def _http_client():
        # Alpine's ca-certificates package is installed in the Cloud Hosting image.
        # Use its bundle explicitly instead of relying on an implicit certifi path.
        ca_file = os.getenv("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")
        return httpx.Client(timeout=20, verify=ca_file)

    def _sign(self, message: bytes) -> str:
        if self._private_key is None:
            if not self.settings.private_key_pem:
                raise RuntimeError("Missing merchant private key configuration")
            self._private_key = serialization.load_pem_private_key(
                self.settings.private_key_pem.encode(), password=None
            )
        signature = self._private_key.sign(
            message,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("ascii")

    def _authorization(self, method: str, path: str, body: str) -> str:
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n".encode()
        signature = self._sign(message)
        return (
            "WECHATPAY2-SHA256-RSA2048 "
            f'mchid="{self.settings.sp_mchid}",'
            f'nonce_str="{nonce}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self.settings.merchant_serial_no}",'
            f'signature="{signature}"'
        )

    def request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        include_platform_serial: bool = False,
    ) -> Dict[str, Any]:
        body_text = "" if body is None else json.dumps(
            body, ensure_ascii=False, separators=(",", ":")
        )
        headers = {
            "Authorization": self._authorization(method, path, body_text),
            "Accept": "application/json",
            "User-Agent": "wxcloudrun-paydemo/0.1",
        }
        if include_platform_serial:
            headers["Wechatpay-Serial"] = self._get_wechat_platform_serial_no()
        if body is not None:
            headers["Content-Type"] = "application/json"
        with self._http_client() as client:
            response = client.request(
                method,
                self.API_BASE + path,
                content=body_text.encode("utf-8"),
                headers=headers,
            )
        if response.status_code >= 400:
            logger.warning(
                "WeChat API error %s %s status=%s detail=%s",
                method,
                path,
                response.status_code,
                response.text,
            )
            raise WeChatAPIError(response.status_code, response.text)
        return response.json() if response.content else {}

    def code2session(self, code: str) -> Dict[str, Any]:
        params = {
            "appid": self.settings.login_appid,
            "secret": self.settings.login_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        try:
            with self._http_client() as client:
                response = client.get(
                    "https://api.weixin.qq.com/sns/jscode2session", params=params
                )
        except httpx.HTTPError as error:
            raise WeChatAPIError(502, f"WeChat code2session network error: {error}") from error
        data = response.json()
        if response.status_code >= 400 or data.get("errcode"):
            raise WeChatAPIError(response.status_code, json.dumps(data, ensure_ascii=False))
        return data

    def create_jsapi_order(
        self, out_trade_no: str, openid: str, amount_fen: Optional[int] = None
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "sp_appid": self.settings.sp_appid,
            "sp_mchid": self.settings.sp_mchid,
            "sub_mchid": self.settings.sub_mchid,
            "description": "微信支付分账 Demo",
            "out_trade_no": out_trade_no,
            "notify_url": self.settings.payment_notify_url,
            "amount": {
                "total": amount_fen if amount_fen is not None else self.settings.total_amount_fen,
                "currency": "CNY",
            },
            "settle_info": {"profit_sharing": True},
        }
        if self.settings.sub_appid:
            body["sub_appid"] = self.settings.sub_appid
            body["payer"] = {"sub_openid": openid}
        else:
            body["payer"] = {"sp_openid": openid}
        # 服务商模式必须使用 partner 专用下单接口；
        # /v3/pay/transactions/jsapi 是普通商户接口，只认 appid/mchid，
        # 传 sp_mchid/sub_mchid 会被微信支付报 PARAM_ERROR 商户号格式错误。
        return self.request("POST", "/v3/pay/partner/transactions/jsapi", body)

    def build_payment_params(self, prepay_id: str) -> Dict[str, str]:
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        package = f"prepay_id={prepay_id}"
        message = f"{self.settings.pay_appid}\n{timestamp}\n{nonce}\n{package}\n".encode()
        return {
            "timeStamp": timestamp,
            "nonceStr": nonce,
            "package": package,
            "signType": "RSA",
            "paySign": self._sign(message),
        }

    def _encrypt_sensitive(self, plaintext: str) -> str:
        """Encrypt sensitive fields (e.g. receiver name) with the WeChat public key.

        微信要求敏感信息使用 RSA/ECB/OAEPWithSHA-1AndMGF1Padding 加密后 base64。
        """
        public_key = self._load_wechat_public_key()
        ciphertext = public_key.encrypt(
            plaintext.encode("utf-8"),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA1()),
                algorithm=hashes.SHA1(),
                label=None,
            ),
        )
        return base64.b64encode(ciphertext).decode("ascii")

    def add_profit_sharing_receiver(
        self,
        receiver_type: str,
        account: str,
        name: str = "",
        relation_type: str = "PARTNER",
    ):
        # 请求分账前，接收方必须与分账方存在“分账接收方关系”。
        # MERCHANT_ID 类型的接收方只能通过该接口添加（商户平台只能加个人微信号接收方）。
        # 已存在的关系重复添加会返回错误，调用方需忽略“已存在”类错误。
        # relation_type 为必填项，可选值：STORE/STAFF/STORE_OWNER/PARTNER/
        # HEADQUARTER/BRAND/DISTRIBUTOR/USER/SUPPLIER/CUSTOM（CUSTOM 需另传 custom_relation）。
        # type 为 MERCHANT_ID 时 name（商户全称）必填，且需用微信支付公钥加密。
        if receiver_type == "MERCHANT_ID" and not name:
            raise RuntimeError(
                "添加 MERCHANT_ID 分账接收方必须提供商户全称："
                "请设置环境变量 WX_PROFIT_RECEIVER_NAME 为接收方商户的工商注册全称"
            )
        body: Dict[str, Any] = {
            "appid": self.settings.profit_appid,
            "sub_mchid": self.settings.sub_mchid,
            "type": receiver_type,
            "account": account,
            "relation_type": relation_type,
        }
        if name:
            body["name"] = self._encrypt_sensitive(name)
        return self.request(
            "POST",
            "/v3/profitsharing/receivers/add",
            body,
            include_platform_serial=bool(name),
        )

    def request_profit_sharing(self, transaction_id: str, out_order_no: str):
        # 服务商请求分账的 body 不包含 mchid 字段，官方仅支持
        # sub_mchid/appid/transaction_id/out_order_no/receivers/unfreeze_unsplit。
        body = {
            "appid": self.settings.profit_appid,
            "sub_mchid": self.settings.sub_mchid,
            "transaction_id": transaction_id,
            "out_order_no": out_order_no,
            "receivers": [
                {
                    "type": "MERCHANT_ID",
                    "account": self.settings.profit_mchid,
                    "amount": self.settings.service_fee_fen,
                    "description": "Demo 服务费",
                }
            ],
            # True：分账的同时解冻剩余资金给分账方，无需再单独调解冻接口。
            # 若为 False，剩余资金会一直保持「待分账」冻结状态，
            # 必须再调 /v3/profitsharing/orders/unfreeze 或等 180 天自动解冻。
            "unfreeze_unsplit": True,
        }
        return self.request("POST", "/v3/profitsharing/orders", body)

    def finish_profit_sharing(self, transaction_id: str, out_order_no: str):
        # 旧的 /v3/profitsharing/orders/{out_order_no}/finish 已下线，
        # 现使用“解冻剩余资金”接口 /v3/profitsharing/orders/unfreeze。
        body = {
            "sub_mchid": self.settings.sub_mchid,
            "transaction_id": transaction_id,
            "out_order_no": out_order_no,
            "description": "Demo 分账完结",
        }
        return self.request("POST", "/v3/profitsharing/orders/unfreeze", body)

    _PEM_BLOCK_RE = re.compile(
        r"-----BEGIN ([A-Z0-9 ]+)-----(.*?)-----END \1-----", re.DOTALL
    )

    @staticmethod
    def _normalize_pem(value: str) -> str:
        """Rebuild a canonical PEM block from pasted configuration content.

        在云控制台粘贴 PEM 时，换行常被吞掉或变成字面 ``\\n``；这里提取
        BEGIN/END 之间的 base64 主体并按 64 列重新折行，恢复标准 PEM 格式。
        """
        if not value or not value.strip():
            raise RuntimeError(
                "缺少微信支付公钥/平台证书配置：请设置 WX_PLATFORM_CERT 为"
                "微信支付公钥(pub_key.pem)或平台证书 PEM 的完整内容"
            )
        text = value.replace("\\n", "\n")
        match = WeChatPay._PEM_BLOCK_RE.search(text)
        if not match:
            raise RuntimeError(
                "WX_PLATFORM_CERT 的值不是有效的 PEM（缺少 -----BEGIN/END----- 标记）。"
                "请粘贴微信支付公钥文件或平台证书文件的完整内容"
                "（含 -----BEGIN PUBLIC KEY----- / -----END PUBLIC KEY----- 行），"
                "而不是公钥ID(PUB_KEY_ID_...)或证书序列号"
            )
        label = match.group(1)
        if label not in ("PUBLIC KEY", "CERTIFICATE"):
            raise RuntimeError(
                f"WX_PLATFORM_CERT 内容为 {label}，应为微信支付公钥(PUBLIC KEY)"
                "或平台证书(CERTIFICATE)，请勿填入商户API私钥等其它密钥"
            )
        body = re.sub(r"\s+", "", match.group(2))
        lines = [body[i : i + 64] for i in range(0, len(body), 64)]
        return "-----BEGIN {}-----\n{}\n-----END {}-----\n".format(
            label, "\n".join(lines), label
        )

    def _get_wechat_platform_serial_no(self) -> str:
        if self._wechat_platform_serial_no is not None:
            return self._wechat_platform_serial_no
        configured = self.settings.platform_serial_no
        if configured:
            self._wechat_platform_serial_no = configured
            return configured
        pem = self._normalize_pem(self.settings.platform_cert_pem)
        if "BEGIN CERTIFICATE" not in pem:
            raise RuntimeError(
                "使用微信支付公钥(PUBLIC KEY)加密敏感字段时，必须设置 "
                "WX_PLATFORM_SERIAL_NO 为商户号对应的微信支付公钥ID"
                "（PUB_KEY_ID_...）"
            )
        certificate = load_pem_x509_certificate(pem.encode())
        self._wechat_platform_serial_no = format(certificate.serial_number, "X")
        return self._wechat_platform_serial_no

    def _load_wechat_public_key(self):
        """Load the key used to verify WeChat notifications.

        Supports both the legacy WeChat platform certificate (X.509, the PEM
        block starts with ``CERTIFICATE``) and the newer WeChat Pay public key
        (a bare RSA public key, the PEM block starts with ``PUBLIC KEY``).
        """
        if self._wechat_public_key is not None:
            return self._wechat_public_key
        pem = self._normalize_pem(self.settings.platform_cert_pem)
        pem_bytes = pem.encode()
        if "BEGIN CERTIFICATE" in pem:
            self._wechat_public_key = load_pem_x509_certificate(pem_bytes).public_key()
        else:
            self._wechat_public_key = serialization.load_pem_public_key(pem_bytes)
        return self._wechat_public_key

    def decrypt_notification(self, headers: Dict[str, str], raw_body: str):
        normalized = {key.lower(): value for key, value in headers.items()}
        timestamp = normalized.get("wechatpay-timestamp", "")
        nonce = normalized.get("wechatpay-nonce", "")
        signature = normalized.get("wechatpay-signature", "")
        if not timestamp or not nonce or not signature:
            raise ValueError("Missing WeChat notification signature headers")
        public_key = self._load_wechat_public_key()
        message = f"{timestamp}\n{nonce}\n{raw_body}\n".encode()
        public_key.verify(
            base64.b64decode(signature), message, padding.PKCS1v15(), hashes.SHA256()
        )
        envelope = json.loads(raw_body)
        resource = envelope["resource"]
        plaintext = AESGCM(self.settings.api_v3_key.encode()).decrypt(
            resource["nonce"].encode(),
            base64.b64decode(resource["ciphertext"]),
            resource.get("associated_data", "").encode(),
        )
        return json.loads(plaintext.decode("utf-8"))
