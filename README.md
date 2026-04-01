# V2ray 自动订阅服务

> 每天自动从 aggregator 项目获取最新代理节点，生成固定订阅链接

## 📌 固定订阅链接

V2ray（base64）：
```
https://c1a200.github.io/wv2ray/subscribe.txt
```

V2ray（Issue #91 对照版）：
```
https://c1a200.github.io/wv2ray/subscribe1.txt
```

Clash / Clash Meta（YAML）：
```
https://c1a200.github.io/wv2ray/clash.yaml
```

Clash / Clash Meta（Issue #91 对照版）：
```
https://c1a200.github.io/wv2ray/clash1.yaml
```

在对应客户端使用相应链接，客户端将自动定期获取最新节点。

## 🚀 快速开始

### 在 V2ray 客户端中使用

1. **打开你的 V2ray 客户端**
   - Clash（ClashX、Clash Meta）
   - V2rayN / V2rayA
   - Surge / Loon / Quanx 等

2. **添加远程订阅**
   - 找到订阅管理或远程订阅选项
   - 添加新的订阅地址

3. **粘贴订阅链接**
   ```
   https://c1a200.github.io/wv2ray/subscribe.txt
   ```

4. **设置自动更新**
   - 建议更新间隔：1-6 小时
   - 客户端将在设定时间自动获取最新节点

5. **导入并使用**
   - 点击导入或更新
   - 选择合适的代理节点
   - 测试连接并使用

## ⚙️ 工作原理

```
GitHub Actions 定时任务 / self-hosted runner (每天 UTC 3点)
         ↓
直接抓取 https://node.zyfx6.xyz/v2rayNG/ 与 https://node.zyfx6.xyz/clash
         ↓
生成主文件 subscribe.txt 与 clash.yaml（直链）
         ↓
额外生成 subscribe1.txt 与 clash1.yaml（Issue #91）
         ↓
上传到 GitHub Pages
         ↓
您的 V2ray 客户端自动更新
```

## 📊 更新信息

| 项目 | 说明 |
|------|------|
| **更新频率** | 每天 1 次 |
| **更新时间** | 北京时间 15:00 (UTC 07:00) |
| **数据源** | aggregator 项目 |
| **节点更新周期** | 源项目每 4 小时更新一次 |
| **格式** | v2ray (base64 编码) |
| **文件大小** | 通常 50-200 KB |

## 📁 文件说明

- `subscribe.txt` - 直链源 v2ray 订阅文件（base64 编码）
- `subscribe1.txt` - Issue #91 源 v2ray 对照订阅文件（base64 编码）
- `clash.yaml` - 直链源 clash 订阅文件（YAML）
- `clash1.yaml` - Issue #91 源 clash 对照订阅文件（YAML）
- `metadata.json` - 订阅元数据和获取时间
- `summary.json` - 订阅摘要信息
- `index.html` - 项目主页面

## 🔄 工作流

这个项目使用 GitHub Actions 自动化以下流程：

1. **定时触发**：每天 UTC 3点自动运行
2. **爬取信息**：抓取直链源，并尝试抓取 Issue #91 源
3. **生成文件**：输出 `subscribe.txt` / `clash.yaml`（直链）以及 `subscribe1.txt` / `clash1.yaml`（Issue）
4. **保存元数据**：生成 `metadata.json` 与 `summary.json`
5. **上传部署**：将文件上传到 GitHub Pages
6. **自动更新**：您的 V2ray 客户端定期自动获取新版本

当前默认主文件仍是直链模式（`USE_DIRECT_SOURCE=true`）。
Issue 对照产物默认开启（`GENERATE_ISSUE_VARIANTS=true`）。

## ☁️ Worker 转发模式（可选）

如果你不想依赖 GitHub-hosted runner 抓取，可以直接用 Cloudflare Worker 做实时转发，客户端地址保持固定。

- Worker 代码与部署说明见 `worker/README.md`
- 典型固定地址：`/subscribe.txt` 与 `/clash.yaml`

## 🌐 线上运行

如果上游拦截 GitHub-hosted runner，正确做法不是回到本地手工跑，而是把抓取作业切到你自己的线上机器。

推荐方案：`GitHub Actions + self-hosted runner + VPS`

1. 准备一台长期在线的 Linux VPS。
2. 进入仓库 Settings → Actions → Runners，添加一个 self-hosted runner。
3. 按 GitHub 给出的命令把 runner 安装到 VPS，并保持服务常驻。
4. 在仓库 Settings → Secrets and variables → Actions → Variables 中新增变量 `FETCH_RUNNER_LABELS`。
5. 变量值填写为 JSON 数组，例如：

```json
["self-hosted", "linux", "x64"]
```

6. 保存后，这个工作流的定时抓取和手动抓取都会优先跑到你的 VPS，而不是 `ubuntu-latest`。

可选：如果你的 VPS 出口同样受限，可以再配置以下 Actions Secrets：

- `HTTP_PROXY`
- `HTTPS_PROXY`
- `ALL_PROXY`

脚本和 `git` 命令会自动继承这些代理环境变量。

这样处理后，整个流程仍然是“在线自动运行”，只是执行出口从 GitHub 公共 runner 改成了你自己的服务器。

## 🛠️ 本地测试

如需在本地测试更新脚本：

```bash
# 安装依赖
pip install requests

# 运行更新脚本
python src/update_subscription.py

# 生成的文件将保存在当前目录
```

## ⚠️ 注意事项

1. **仅供学习使用**：请遵守相关法律法规
2. **模式切换**：默认是直链模式；若上游恢复，可随时切回 Issue 抓取模式
3. **隐私保护**：不建议将此链接公开分享
4. **定期检查**：如果发现节点不可用，可手动触发工作流更新

## 🔧 自定义配置

### 修改更新时间

编辑 `.github/workflows/update-subscription.yml` 中的 cron 表达式：

```yaml
schedule:
  - cron: '0 3 * * *'  # 修改这里 (UTC 时间)
```

Cron 格式：`分 小时 日 月 星期`

示例：
- `0 3 * * *` - 每天 UTC 3点
- `0 */6 * * *` - 每 6 小时
- `0 9,15,21 * * *` - 每天 9、15、21 点

### 修改直链源地址

编辑 `.github/workflows/update-subscription.yml` 中以下环境变量：

```yaml
env:
   USE_DIRECT_SOURCE: 'true'
   DIRECT_V2RAY_URL: 'https://node.zyfx6.xyz/v2rayNG/'
   DIRECT_CLASH_URL: 'https://node.zyfx6.xyz/clash'
```

如果要恢复旧模式：

```yaml
env:
   USE_DIRECT_SOURCE: 'false'
```

## 📊 当前数据源说明

默认数据源：

| 文件 | 来源 |
| --- | --- |
| `subscribe.txt` | [https://node.zyfx6.xyz/v2rayNG/](https://node.zyfx6.xyz/v2rayNG/) |
| `clash.yaml` | [https://node.zyfx6.xyz/clash](https://node.zyfx6.xyz/clash) |
| `subscribe1.txt` | GitHub Issue #91 动态提取 token/api_url 后生成 |
| `clash1.yaml` | GitHub Issue #91 动态提取 token/api_url 后生成 |

兼容模式：

- 当 `USE_DIRECT_SOURCE=false` 时，脚本会回退到 Issue/API 动态抓取流程。
- 当 `GENERATE_ISSUE_VARIANTS=false` 时，将不再生成 `subscribe1.txt` 与 `clash1.yaml`。

## 🎯 项目结构

```
wv2ray/
├── .github/
│   └── workflows/
│       └── update-subscription.yml    # GitHub Actions 工作流
├── src/
│   ├── fetcher.py                     # 爬取和转换脚本
│   └── update_subscription.py         # 更新执行脚本
├── docs/
│   ├── subscribe.txt                  # 生成的订阅文件
│   ├── metadata.json                  # 元数据
│   ├── summary.json                   # 摘要
│   └── index.html                     # 项目首页
├── config.json                        # 项目配置
└── README.md                          # 本文件
```

## 📝 日志和调试

GitHub Actions 每次运行的日志可以在：
```
https://github.com/c1a200/wv2ray/actions
```

查看具体的运行日志和错误信息。

## 💡 常见问题

**Q: 如何手动触发更新？**  
A: 进入 GitHub Actions 页面，选择工作流，点击 "Run workflow" 按钮。

**Q: 节点不可用怎么办？**  
A: 先检查 `https://node.zyfx6.xyz/v2rayNG/` 和 `https://node.zyfx6.xyz/clash` 是否可访问；若直链故障，可临时切回 `USE_DIRECT_SOURCE=false` 使用旧模式。

**Q: 订阅链接打开后直接显示 `{"code":403,"message":"Forbidden: GitHub Actions crawler is not allowed","success":false}` 怎么办？**  
A: 这不是 GitHub Pages 自己报错，而是上游 aggregator 接口识别到请求来自 GitHub Actions 运行环境后，直接返回了一个 JSON 错误。之前脚本没有校验返回内容，错误 JSON 被当成正常订阅发布到了 Pages。现在应这样处理：
   1. 先在非 GitHub Actions 环境手动执行更新，恢复一份可用的 `docs/subscribe.txt` 与 `docs/clash.yaml`。
   2. 再重新部署 GitHub Pages。
   3. 后续如果继续用 GitHub-hosted runner，上游仍可能拦截，建议改成 self-hosted runner、VPS、代理出口，或其他不被上游封禁的执行环境。

**Q: 我需要在线自动跑，不想本地手动更新，怎么办？**  
A: 现在工作流已经支持通过变量切换运行器。最稳妥的方式是在 VPS 上部署 GitHub self-hosted runner，然后把仓库变量 `FETCH_RUNNER_LABELS` 设为对应标签，例如 `["self-hosted", "linux", "x64"]`。这样定时任务还是 GitHub Actions 触发，但真正抓取会在你的线上机器执行。

**Q: 可以修改更新频率吗？**  
A: 可以，编辑工作流文件中的 cron 表达式。

**Q: 订阅链接会改变吗？**  
A: 不会，链接是固定的。内容由 GitHub Actions 自动更新。

**Q: Clash 订阅无法导入，提示乱码？**  
A: 这可能是网络连接问题。如果直接访问 GitHub Pages 显示乱码，尝试：
  1. 使用代理/VPN 重新获取
  2. 更新客户端到最新版本
  3. 检查客户端字符集设置（确保为 UTF-8）
  
  clash.yaml 文件已在生成时添加 UTF-8 BOM，应该能被正确识别。

**Q: Clash 订阅显示连接超时 (socket exception)?**  
A: 通常是由于网络连接不稳定。尝试：
  1. 启用代理/VPN
  2. 使用其他网络连接
  3. 手动刷新订阅或稍后重试

## 📄 许可证

本项目遵循 aggregator 项目的相关规则和条款。

## 🙏 致谢

感谢 [aggregator](https://github.com/wzdnzd/aggregator) 项目提供的节点聚合服务。

---

**⏰ 最后更新**: 2024-01-16  
**✨ 由 GitHub Actions 自动维护**
