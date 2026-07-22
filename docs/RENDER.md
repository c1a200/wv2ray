# Render 部署

项目已包含 `render.yaml`，在 Render 中选择 **New > Blueprint** 并连接仓库即可创建服务。

## 必填环境变量

- `ADMIN_PASSWORD`：管理登录密码（默认 `admin123`，上线后务必改掉）
- `SECRET_KEY`：Blueprint 会自动生成；手动部署时请设为随机长字符串
- `WEBDAV_URL`：Cloudreve WebDAV **目录**地址，例如：
  - 正确：`https://cloudreve.176111.xyz/dav/V2ray`
  - 错误：`https://cloudreve.176111.xyz/dav/V2ray/V2ray`（会多一层子目录）
- `WEBDAV_USERNAME` / `WEBDAV_PASSWORD`：WebDAV 账号密码

免费 Render 本地磁盘是临时的。配置了 WebDAV 后：
- 启动时从 WebDAV 恢复配置和上次订阅文件
- 每次保存配置或刷新成功后同步回 WebDAV

## 可选环境变量

- `SKIP_INITIAL_REFRESH=true`（默认）：避免开机立刻刷新导致长时间占用
- `HTTP_TIMEOUT_SECONDS=25`
- `SUBCONVERTER_TIMEOUT_SECONDS=45`
- `WEBDAV_TIMEOUT_SECONDS=20`
- `REFRESH_INTERVAL_SECONDS=86400`
- `SUBCONVERTER_URL`：自定义转换服务

## 使用

1. 打开 `https://<service>.onrender.com/`
2. 输入管理密码登录
3. 在「管理设置」填写主订阅地址和其他源
4. 点击「保存并刷新」——刷新在后台执行，页面会轮询状态（避免网关 502）
5. 复制 V2Ray / Clash / Sing-box / NekoBox 链接到客户端

公开订阅文件（客户端可直接拉取）：

```text
/subscribe.txt
/clash.yaml
/singbox.json
/nbsh.txt
```

前端链接始终使用当前访问域名（`location.origin`），绑定自定义域名后会自动变化，无需手工改域名。

## WebDAV 目录说明

`WEBDAV_URL` 必须指向**已经存在的空目录或专用目录**，文件会直接写入该目录根下：

```text
upstream.json
subscribe.txt
clash.yaml
singbox.json
nbsh.txt
metadata.json
summary.json
```

如果你在网盘里看到 `V2ray/V2ray` 两层，说明环境变量多写了一段路径，改成只保留一层后重新保存配置即可。

## Cloudreve WebDAV 专用密码（重要）

Cloudreve 可以为 WebDAV 创建「相对根目录」。例如相对根目录是 /V2ray 时：

- 正确：WEBDAV_URL=https://cloudreve.176111.xyz/dav
- 错误：WEBDAV_URL=https://cloudreve.176111.xyz/dav/V2ray（会变成 /V2ray/V2ray，重启后读不到配置）

服务启动时会从 WebDAV 恢复 upstream.json 和订阅文件。若路径不匹配，设置页会是空的，状态里会显示 WebDAV 恢复错误。
