# 部署和使用指南

## 🎯 项目目标

自动从 aggregator 项目获取最新的代理节点订阅，每天定时更新，并通过固定的 GitHub Pages 链接供 V2ray 客户端使用。

## 📋 前置要求

- GitHub 账户（已有：c1a200）
- 公开的 GitHub 仓库（项目名：wv2ray）
- 启用 GitHub Pages（使用 GitHub Actions 部署）

## 🚀 部署步骤

### 步骤 1：创建 GitHub 仓库

1. 在 GitHub 上创建新仓库：`wv2ray`
2. 设置为公开仓库

### 步骤 2：克隆并上传代码

```bash
# 克隆仓库（首次）
git clone https://github.com/c1a200/wv2ray.git
cd wv2ray

# 或者初始化新仓库
git init
git remote add origin https://github.com/c1a200/wv2ray.git
```

### 步骤 3：添加项目文件

这个项目包含以下结构：

```
wv2ray/
├── .github/
│   └── workflows/
│       └── update-subscription.yml
├── src/
│   ├── fetcher.py
│   └── update_subscription.py
├── docs/
│   ├── index.html
│   ├── subscribe.txt (自动生成)
│   ├── metadata.json (自动生成)
│   └── summary.json (自动生成)
├── .gitignore
├── config.json
├── requirements.txt
└── README.md
```

### 步骤 4：上传到 GitHub

```bash
git add .
git commit -m "初始化 V2ray 自动订阅服务"
git branch -M main
git push -u origin main
```

### 步骤 5：配置 GitHub Pages

1. 进入仓库的 Settings
2. 左侧菜单找到 "Pages"
3. Source 选择：`GitHub Actions`
4. GitHub Pages 将自动部署（由工作流文件指定）

### 步骤 6：等待首次运行

GitHub Actions 会在以下情况运行：

- **自动触发**：每天 UTC 3点（北京时间 15:00）
- **手动触发**：在 Actions 页面手动执行工作流

首次可以手动触发来测试：

1. 进入 GitHub 仓库
2. 点击 "Actions" 标签
3. 选择 "Update V2ray Subscription" 工作流
4. 点击 "Run workflow"

## 📌 固定订阅链接

部署完成后，使用此链接：

```
https://c1a200.github.io/wv2ray/subscribe.txt
```

## 🔧 在 V2ray 客户端中配置

### Clash（ClashX、Clash Meta）

1. 打开 Clash 应用
2. 配置 → 配置文件 → 管理
3. 添加新的配置文件或远程订阅
4. 输入链接：`https://c1a200.github.io/wv2ray/subscribe.txt`
5. 下载/更新配置文件
6. 切换到新配置

### V2rayN（Windows）

1. 打开 V2rayN
2. 右键托盘图标 → 订阅管理
3. 添加订阅源
4. 标签：`aggregator-v2ray`
5. 地址：`https://c1a200.github.io/wv2ray/subscribe.txt`
6. 点击更新订阅
7. 从订阅列表中导入

### V2rayA（Web UI）

1. 打开 V2rayA 管理界面
2. 左侧菜单 → 订阅
3. 添加订阅
4. 输入链接：`https://c1a200.github.io/wv2ray/subscribe.txt`
5. 保存并更新

### Surge / Loon / Quanx

1. 打开应用
2. 找到订阅或远程资源选项
3. 添加新的远程订阅源
4. 输入链接：`https://c1a200.github.io/wv2ray/subscribe.txt`
5. 下载或自动更新

## ⚙️ 工作流说明

### 触发条件

工作流 `.github/workflows/update-subscription.yml` 的触发方式：

```yaml
on:
  schedule:
    # 每天 UTC 3点 (北京时间下午3点)
    - cron: '0 3 * * *'
  
  # 允许手动触发
  workflow_dispatch:
```

### 工作流步骤

1. **检出代码** - 获取最新的仓库代码
2. **配置 Python** - 使用 Python 3.11
3. **安装依赖** - 安装 requests 库
4. **更新订阅** - 运行 `update_subscription.py` 脚本
5. **移动文件** - 将生成的文件复制到 docs 目录
6. **生成首页** - 创建 index.html 页面
7. **提交变化** - 如有变化则提交到 git
8. **部署到 Pages** - 上传到 GitHub Pages
9. **发布** - 使 Pages 上线

## 🔍 监控和调试

### 查看工作流运行历史

1. 进入 GitHub 仓库
2. 点击 "Actions" 标签
3. 在左侧看到 "Update V2ray Subscription" 工作流
4. 点击查看运行详情

### 查看详细日志

1. 点击工作流中的特定运行
2. 展开各个步骤查看日志
3. 找到错误信息（如有）

### 常见问题排查

**问题：工作流显示红色 ❌**

- 查看日志找到错误信息
- 常见原因：
  - aggregator 网站无法访问
  - GitHub API 速率限制
  - 网络问题

**解决方案**：
- 手动重新运行工作流
- 等待几分钟后重试
- 检查 aggregator 项目是否在线

## 📊 文件说明

### subscribe.txt
- 标准的 v2ray 订阅文件
- Base64 编码格式
- 包含所有代理节点信息
- 定期自动更新

### metadata.json
- 订阅的元数据信息
- 包含获取时间、token 等
- 用于调试和监控

### summary.json
- 订阅的摘要信息
- 包含文件大小、更新时间等

### index.html
- 项目的网页介绍页面
- 提供订阅链接和使用说明
- 自动加载元数据显示状态

## 🔐 安全考虑

1. **Token 轮换**
   - aggregator 项目可能会定期更新 token
   - 脚本会自动从 GitHub Issue 中获取最新 token
   - 无需手动更新

2. **仓库权限**
   - 仓库应保持公开以供 GitHub Pages 访问
   - 工作流使用 GitHub 默认权限
   - 无需额外的 PAT（Personal Access Token）

3. **隐私保护**
   - 不建议公开分享订阅链接
   - 不要在公共社交媒体分享
   - 仅供个人使用

## 🛠️ 本地测试

### 测试爬取脚本

```bash
# 进入项目目录
cd wv2ray

# 安装依赖
pip install -r requirements.txt

# 运行爬取脚本
python src/fetcher.py

# 查看输出
# 应该会显示获取的 token 和 API 地址
```

### 测试更新脚本

```bash
# 运行更新脚本
python src/update_subscription.py

# 生成的文件：
# - subscribe.txt (in current directory)
# - metadata.json
# - summary.json
```

## 📈 后续扩展

### 可能的改进方向

1. **多目标支持**
   - 同时生成 clash、singbox 等格式
   - 不同格式的订阅链接

2. **高级过滤**
   - 按地区筛选节点
   - 按延迟筛选
   - 按类型筛选

3. **性能监控**
   - 节点延迟测试
   - 订阅源可用性监控
   - 自动告警

4. **更新通知**
   - 发送更新完成的通知
   - Discord / Telegram 集成

## 📞 支持和反馈

遇到问题时：

1. 检查 GitHub Actions 的运行日志
2. 查看 aggregator 项目是否在线
3. 验证网络连接
4. 确认 GitHub Pages 已启用

## 📝 最后检查清单

部署前确认：

- [ ] 创建了 GitHub 仓库 `c1a200/wv2ray`
- [ ] 上传了所有项目文件
- [ ] 启用了 GitHub Pages
- [ ] 工作流文件在正确的位置（`.github/workflows/`）
- [ ] 首次工作流运行成功
- [ ] 订阅文件已生成（`docs/subscribe.txt`）
- [ ] 可访问 `https://c1a200.github.io/wv2ray/`

## 🎉 完成！

现在您有了一个完全自动化的 V2ray 订阅服务！

- **固定链接**: https://c1a200.github.io/wv2ray/subscribe.txt
- **更新频率**: 每天一次（北京时间 15:00）
- **无需手动**: GitHub Actions 自动处理一切

在您的 V2ray 客户端中添加此链接，享受自动更新的代理节点！
