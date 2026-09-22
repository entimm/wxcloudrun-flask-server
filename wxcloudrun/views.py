import secrets
import logging
from typing import Dict

from flask import jsonify, render_template, request

from wxcloudrun import app, db
from wxcloudrun.model import DemoOrders
from wxcloudrun.pay_config import PaySettings
from wxcloudrun.wechat_pay import WeChatAPIError, WeChatPay


logger = logging.getLogger(__name__)
demo_sessions: Dict[str, str] = {}
wechat_client = None
login_client = None


def get_wechat_client() -> WeChatPay:
    global wechat_client
    if wechat_client is None:
        wechat_client = WeChatPay(PaySettings.from_env())
    return wechat_client


def get_login_client() -> WeChatPay:
    global login_client
    if login_client is None:
        login_client = WeChatPay(PaySettings.login_from_env())
    return login_client


def error_response(message: str, status_code: int):
    return jsonify({'detail': message}), status_code


def order_response(order: DemoOrders):
    return {
        'id': order.id,
        'out_trade_no': order.out_trade_no,
        'amount_fen': order.amount_fen,
        'service_fee_fen': order.service_fee_fen,
        'sub_mchid': order.sub_mchid,
        'prepay_id': order.prepay_id,
        'transaction_id': order.transaction_id,
        'payment_status': order.payment_status,
        'profit_status': order.profit_status,
        'profit_sharing_order_no': order.profit_sharing_order_no,
        'error_message': order.error_message,
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'updated_at': order.updated_at.isoformat() if order.updated_at else None,
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'ok': True})


@app.route('/demo/login', methods=['POST'])
def login():
    payload = request.get_json(silent=True) or {}
    code = payload.get('code', '')
    if not code:
        return error_response('code is required', 400)
    try:
        session = get_login_client().code2session(code)
    except WeChatAPIError as error:
        logger.warning('WeChat code2session failed: %s', error.detail)
        detail = error.detail
        if '40125' in detail:
            message = (
                'AppSecret 无效 (40125)：请确认云托管环境变量 WX_LOGIN_APPID 与 '
                'WX_LOGIN_SECRET 对应当前小程序，修改后需重新部署生效'
            )
        elif '40013' in detail:
            message = 'AppID 无效 (40013)：请检查云托管环境变量 WX_LOGIN_APPID'
        else:
            message = f'code2session 失败: {detail}'
        return error_response(message, 502)
    except Exception as error:
        logger.exception('Unexpected error during demo login')
        return error_response(str(error), 500)
    openid = session.get('openid')
    if not openid:
        return error_response('WeChat did not return openid', 502)
    token = secrets.token_urlsafe(24)
    demo_sessions[token] = openid
    return jsonify({'session_token': token})


@app.route('/demo/pay', methods=['POST'])
def create_payment():
    payload = request.get_json(silent=True) or {}
    openid = demo_sessions.get(payload.get('session_token', ''))
    if not openid:
        return error_response('Invalid demo session', 401)
    settings = PaySettings.from_env()
    try:
        amount_fen = int(payload.get('amount_fen', settings.total_amount_fen))
    except (TypeError, ValueError):
        return error_response('amount_fen must be an integer (单位：分)', 400)
    # 金额需大于分账服务费，否则分账后子商户无剩余资金
    if amount_fen <= settings.service_fee_fen or amount_fen > 100000000:
        return error_response(
            f'支付金额无效：需大于服务费 {settings.service_fee_fen} 分且不超过 1000000 元',
            400,
        )
    order_id = secrets.token_urlsafe(12)
    out_trade_no = 'D' + secrets.token_hex(12)
    order = DemoOrders(
        id=order_id,
        out_trade_no=out_trade_no,
        amount_fen=amount_fen,
        service_fee_fen=settings.service_fee_fen,
        sub_mchid=settings.sub_mchid,
        openid=openid,
        payment_status='CREATED',
        profit_status='NOT_STARTED',
    )
    db.session.add(order)
    db.session.commit()
    try:
        result = get_wechat_client().create_jsapi_order(out_trade_no, openid, amount_fen)
        order.prepay_id = result['prepay_id']
        order.payment_status = 'PREPAY_CREATED'
        db.session.commit()
    except Exception as error:
        if isinstance(error, WeChatAPIError):
            logger.warning('WeChat create JSAPI order failed: %s', error.detail)
        else:
            logger.exception('Unexpected error while creating JSAPI order')
        order.payment_status = 'FAILED'
        order.error_message = str(error)[:1000]
        db.session.commit()
        if isinstance(error, WeChatAPIError):
            return error_response(error.detail, 502)
        return error_response(str(error), 500)
    return jsonify(
        {
            'order_id': order.id,
            'out_trade_no': order.out_trade_no,
            'payment': get_wechat_client().build_payment_params(order.prepay_id),
        }
    )


@app.route('/demo/orders/<order_id>', methods=['GET'])
def get_order(order_id):
    order = DemoOrders.query.get(order_id)
    if not order:
        return error_response('Order not found', 404)
    return jsonify(order_response(order))


@app.route('/demo/orders/<order_id>/split', methods=['POST'])
def split_order(order_id):
    order = DemoOrders.query.get(order_id)
    if not order:
        return error_response('Order not found', 404)
    if order.payment_status != 'PAID':
        return error_response('Payment is not confirmed', 409)
    if order.profit_status == 'FINISHED':
        return jsonify({'status': 'FINISHED', 'order': order_response(order)})
    client = get_wechat_client()
    if order.profit_status in ('NOT_STARTED', 'FAILED') and not order.profit_sharing_order_no:
        out_order_no = 'S' + secrets.token_hex(12)
        try:
            # 分账前先确保接收方与分账方存在分账关系。
            # 重复添加会返回错误（关系已存在），这里忽略；否则首次分账会报
            # PARAM_ERROR「分账接收方关系不存在」。
            try:
                pay_settings = PaySettings.from_env()
                client.add_profit_sharing_receiver(
                    'MERCHANT_ID',
                    pay_settings.profit_mchid,
                    name=pay_settings.profit_receiver_name,
                )
            except WeChatAPIError as receiver_error:
                if 'EXIST' not in receiver_error.detail.upper():
                    raise
            client.request_profit_sharing(order.transaction_id, out_order_no)
            order.profit_sharing_order_no = out_order_no
            # 请求分账时已传 unfreeze_unsplit=True，剩余资金随分账一并解冻，
            # 无需再调 finish_profit_sharing。
            order.profit_status = 'FINISHED'
            order.error_message = None
            db.session.commit()
            return jsonify({'status': 'FINISHED', 'order': order_response(order)})
        except WeChatAPIError as error:
            logger.warning('WeChat profit sharing failed for order %s: %s', order.id, error.detail)
            order.profit_status = 'FAILED'
            order.error_message = error.detail[:1000]
            db.session.commit()
            return error_response(error.detail, 502)
    # 兼容历史订单：此前分账时 unfreeze_unsplit=False，剩余资金仍冻结，
    # 需要补调解冻接口释放。
    try:
        client.finish_profit_sharing(order.transaction_id, order.profit_sharing_order_no)
        order.profit_status = 'FINISHED'
        db.session.commit()
    except WeChatAPIError as error:
        logger.warning('WeChat finish profit sharing failed for order %s: %s', order.id, error.detail)
        order.profit_status = 'FAILED'
        order.error_message = error.detail[:1000]
        db.session.commit()
        return error_response(error.detail, 502)
    return jsonify({'status': 'FINISHED', 'order': order_response(order)})


@app.route('/demo/notify/payment', methods=['POST'])
def payment_notification():
    raw_body = request.get_data(as_text=True)
    try:
        transaction = get_wechat_client().decrypt_notification(
            dict(request.headers), raw_body
        )
    except Exception as error:
        logger.exception('Invalid payment notification')
        return error_response(f'Invalid notification: {error}', 400)
    if transaction.get('trade_state') == 'SUCCESS':
        order = DemoOrders.query.filter_by(
            out_trade_no=transaction['out_trade_no']
        ).first()
        if order:
            order.payment_status = 'PAID'
            order.transaction_id = transaction['transaction_id']
            db.session.commit()
    return jsonify({'code': 'SUCCESS', 'message': '成功'})
