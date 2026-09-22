from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import pymysql
import config

from wxcloudrun.errors import register_error_handlers

# 因MySQLDB不支持Python3，使用pymysql扩展库代替MySQLDB库
pymysql.install_as_MySQLdb()

# 初始化web应用
app = Flask(__name__, instance_relative_config=True)
app.config['DEBUG'] = config.DEBUG
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 所有未捕获异常统一返回 JSON，避免前端收到 Flask 默认的 HTML 错误页
register_error_handlers(app)

# 设定数据库链接
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://{}:{}@{}/flask_demo'.format(config.username, config.password,
                                                                             config.db_address)

# 云托管内网代理会回收空闲连接，池中缓存的连接可能已被服务端断开，
# 复用时触发 2013 Lost connection / Connection reset by peer。
# 取连接前先探活，并定期重建连接（需小于服务端 wait_timeout）。
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280,
    'pool_timeout': 10,
}

# 初始化DB操作对象
db = SQLAlchemy(app)

# 加载控制器
from wxcloudrun import views

# Create the small demo table when the configured Cloud Hosting database is available.
with app.app_context():
    db.create_all()

# 加载配置
app.config.from_object('config')
