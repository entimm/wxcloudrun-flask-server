from datetime import datetime

from wxcloudrun import db


class DemoOrders(db.Model):
    """Minimal payment state used only by the throwaway payment demo."""

    __tablename__ = 'DemoOrders'

    id = db.Column(db.String(64), primary_key=True)
    out_trade_no = db.Column('outTradeNo', db.String(64), nullable=False, unique=True)
    amount_fen = db.Column('amountFen', db.Integer, nullable=False)
    service_fee_fen = db.Column('serviceFeeFen', db.Integer, nullable=False)
    sub_mchid = db.Column('subMchid', db.String(32), nullable=False)
    openid = db.Column(db.String(128), nullable=False)
    prepay_id = db.Column('prepayId', db.String(128))
    transaction_id = db.Column('transactionId', db.String(128))
    payment_status = db.Column('paymentStatus', db.String(32), nullable=False)
    profit_status = db.Column('profitStatus', db.String(32), nullable=False)
    profit_sharing_order_no = db.Column('profitSharingOrderNo', db.String(64))
    error_message = db.Column('errorMessage', db.String(1000))
    created_at = db.Column('createdAt', db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column('updatedAt', db.DateTime, nullable=False, default=datetime.utcnow)
