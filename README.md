# wxcloudrun-flask
[![GitHub license](https://img.shields.io/github/license/WeixinCloud/wxcloudrun-express)](https://github.com/WeixinCloud/wxcloudrun-express)
![GitHub package.json dependency version (prod)](https://img.shields.io/badge/python-3.7.3-green)

微信云托管 python Flask 框架模版，实现简单的计数器读写接口，使用云托管 MySQL 读写、记录计数值。

![](https://qcloudimg.tencent-cloud.cn/raw/be22992d297d1b9a1a5365e606276781.png)


## 快速开始
前往 [微信云托管快速开始页面](https://developers.weixin.qq.com/miniprogram/dev/wxcloudrun/src/basic/guide.html)，选择相应语言的模板，根据引导完成部署。

## 本地调试
下载代码在本地调试，请参考[微信云托管本地调试指南](https://developers.weixin.qq.com/miniprogram/dev/wxcloudrun/src/guide/debug/)

## 实时开发
代码变动时，不需要重新构建和启动容器，即可查看变动后的效果。请参考[微信云托管实时开发指南](https://developers.weixin.qq.com/miniprogram/dev/wxcloudrun/src/guide/debug/dev.html)

## Dockerfile最佳实践
请参考[如何提高项目构建效率](https://developers.weixin.qq.com/miniprogram/dev/wxcloudrun/src/scene/build/speed.html)

## 目录结构说明

~~~
.
├── Dockerfile dockerfile       dockerfile
├── README.md README.md         README.md文件
├── container.config.json       模板部署「服务设置」初始化配置（二开请忽略）
├── requirements.txt            依赖包文件
├── config.py                   项目的总配置文件  里面包含数据库 web应用 日志等各种配置
├── run.py                      flask项目管理文件 与项目进行交互的命令行工具集的入口
└── wxcloudrun                  app目录
    ├── __init__.py             python项目必带  模块化思想
    ├── dao.py                  数据库访问模块
    ├── model.py                数据库对应的模型
    ├── response.py             响应结构构造
    ├── templates               模版目录,包含主页index.html文件
    └── views.py                执行响应的代码所在模块  代码逻辑处理主要地点  项目大部分代码在此编写
~~~



## 服务 API 文档

### `GET /api/count`

获取当前计数

#### 请求参数

无

#### 响应结果

- `code`：错误码
- `data`：当前计数值

##### 响应结果示例

```json
{
  "code": 0,
  "data": 42
}
```

#### 调用示例

```
curl https://<云托管服务域名>/api/count
```



### `POST /api/count`

更新计数，自增或者清零

#### 请求参数

- `action`：`string` 类型，枚举值
  - 等于 `"inc"` 时，表示计数加一
  - 等于 `"clear"` 时，表示计数重置（清零）

##### 请求参数示例

```
{
  "action": "inc"
}
```

#### 响应结果

- `code`：错误码
- `data`：当前计数值

##### 响应结果示例

```json
{
  "code": 0,
  "data": 42
}
```

#### 调用示例

```
curl -X POST -H 'content-type: application/json' -d '{"action": "inc"}' https://<云托管服务域名>/api/count
```

## 使用注意
如果不是通过微信云托管控制台部署模板代码，而是自行复制/下载模板代码后，手动新建一个服务并部署，需要在「服务设置」中补全以下环境变量，才可正常使用，否则会引发无法连接数据库，进而导致部署失败。
- MYSQL_ADDRESS
- MYSQL_PASSWORD
- MYSQL_USERNAME
以上三个变量的值请按实际情况填写。如果使用云托管内MySQL，可以在控制台MySQL页面获取相关信息。

## 支付分账 Demo

本模板已经加入一个一次性的微信支付服务商分账 Demo，入口仍然是模板的 `run.py`，容器端口仍然是 80。

Dockerfile 已包含 `cryptography`/`cffi` 源码构建所需的 Alpine 编译依赖。微信支付 V3 的商户签名和回调解密依赖该加密库，不能删除对应依赖后继续运行支付流程。

部署前在微信云托管服务设置中增加 `.env.example` 中的微信支付环境变量。建议使用云托管环境变量保存 `WX_PRIVATE_KEY` 和 `WX_PLATFORM_CERT`，换行使用 `\\n` 表示；不要把真实证书提交到代码仓库。

Demo 接口：

- `POST /demo/login`：使用小程序 `wx.login` 的 code 自动换取 OpenID。
- `POST /demo/pay`：创建固定金额的 JSAPI 支付订单。
- `GET /demo/orders/<order_id>`：查询支付和分账状态。
- `POST /demo/orders/<order_id>/split`：请求服务商分账并完结分账。
- `POST /demo/notify/payment`：接收微信支付回调。

支付回调地址需要配置为：

```text
https://<云托管服务域名>/demo/notify/payment
```

服务商需要提前在微信支付侧配置为物业子商户的分账接收方。`DemoOrders` 表会由模板数据库初始化脚本创建，应用启动时也会尝试创建缺失表。

小程序调用云托管

小程序端使用 `wx.cloud.callContainer` 调用上述 Demo 接口，不直接请求云托管公网域名。请在小程序目录的 `config.js` 中填写：

- `CLOUD_ENV_ID`：微信云开发/云托管环境 ID。
- `CLOUD_SERVICE_NAME`：云托管服务名称，对应请求头 `X-WX-SERVICE`。

调用前请确认该小程序已关联到对应云开发环境，并在云托管服务的访问配置中允许该小程序调用。



## License

[MIT](./LICENSE)
