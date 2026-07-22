# Render 部署

项目已包含 `render.yaml`，在 Render 中选择 **New > Blueprint** 并连接仓库即可创建服务。

部署后建议在 Environment 中设置：

- `ADMIN_TOKEN`：管理前端保存上游地址、手动刷新时使用的令牌。建议设置为随机长字符串。
- `ADMIN_PASSWORD`：管理页面 `/admin` 的登录密码。未设置时默认是 `admin123`，Render 部署后务必覆盖为随机长密码。
- `SECRET_KEY`：管理登录会话的签名密钥；Blueprint 会自动生成，手动部署时请设置随机长字符串。
- `DIRECT_V2RAY_URL`：默认 V2Ray 上游地址。
- `DIRECT_CLASH_URL`：默认 Clash 上游地址。
- `DIRECT_TOKEN`：上游要求 token 时填写，可留空。
- `REFRESH_INTERVAL_SECONDS`：刷新间隔，默认 `86400`（每天一次）。

浏览服务根地址即可打开前端。前端中的“上游配置”可以修改外部订阅地址；保存后点击“立即刷新”。订阅地址为：

```text
/subscribe.txt
/clash.yaml
/singbox.json
/nbsh.txt
```

免费 Render 实例的本地目录是临时的。设置 `WEBDAV_URL`、`WEBDAV_USERNAME` 和 `WEBDAV_PASSWORD` 后，服务会在启动时从 WebDAV 恢复配置和上次成功的订阅文件，并在每次保存配置或刷新成功后同步回 WebDAV。请先在 WebDAV 中创建一个专用的空目录，并将 `WEBDAV_URL` 指向该目录。

服务启动命令是：

```text
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

刷新时，主订阅和“其他订阅源”都会经过 `SUBCONVERTER_URL` 转换并聚合：Clash 节点进入 `clash.yaml`，可转换的节点 URI 进入 `subscribe.txt`。可通过 `SUBCONVERTER_URL` 覆盖默认转换服务。
