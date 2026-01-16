# V2ray 自动订阅服务

> 每天自动从 aggregator 项目获取最新代理节点，生成固定订阅链接

## 📌 固定订阅链接

V2ray（base64）：
```
https://c1a200.github.io/wv2ray/subscribe.txt
```

Clash / Clash Meta（YAML）：
```
https://c1a200.github.io/wv2ray/clash.yaml
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
GitHub Actions 定时任务 (每天 UTC 3点)
         ↓
从 GitHub Issue #91 抓取 token 和 API 地址
         ↓
调用 aggregator API 获取最新代理节点
         ↓
转换为标准 v2ray base64 格式
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

- `subscribe.txt` - 标准 v2ray 订阅文件（base64 编码）
- `metadata.json` - 订阅元数据和获取时间
- `summary.json` - 订阅摘要信息
- `index.html` - 项目主页面

## 🔄 工作流

这个项目使用 GitHub Actions 自动化以下流程：

1. **定时触发**：每天 UTC 3点自动运行
2. **爬取信息**：从 GitHub Issue 页面获取最新的 aggregator token 和 API 地址
3. **获取订阅**：调用 aggregator API 获取代理节点
4. **转换格式**：将节点转换为标准 v2ray 订阅格式
5. **上传部署**：将文件上传到 GitHub Pages
6. **自动更新**：您的 V2ray 客户端定期自动获取新版本

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
2. **Token 更新**：如果 aggregator 项目更新了 token，脚本会自动检测并使用新 token
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

### 修改目标客户端

编辑 `src/fetcher.py` 中的 `target` 参数：

```python
subscribe_url = fetcher.build_subscribe_url(
    token=info['token'],
    api_url=info['api_url'],
    target='v2ray'  # 修改为: clash, singbox, surge 等
)
```

## 📊 API 参数说明

该项目调用的 aggregator API 支持以下参数：

| 参数 | 说明 | 必填 | 可选值 |
|------|------|------|--------|
| `token` | 鉴权 token | ✓ | - |
| `target` | 客户端类型 | ✗ | clash, v2ray, singbox, surge, loon, quanx, surfboard |
| `list` | 是否仅返回节点 | ✗ | true/false 或 1/0 |

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
A: 首先检查 aggregator 项目是否在线，可以手动访问源 API 地址测试。

**Q: 可以修改更新频率吗？**  
A: 可以，编辑工作流文件中的 cron 表达式。

**Q: 订阅链接会改变吗？**  
A: 不会，链接是固定的。内容由 GitHub Actions 自动更新。

## 📄 许可证

本项目遵循 aggregator 项目的相关规则和条款。

## 🙏 致谢

感谢 [aggregator](https://github.com/wzdnzd/aggregator) 项目提供的节点聚合服务。

---

**⏰ 最后更新**: 2024-01-16  
**✨ 由 GitHub Actions 自动维护**
