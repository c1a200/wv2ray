# 🚀 快速部署指南

## 已创建的项目结构

```
wv2ray/
├── .github/workflows/
│   └── update-subscription.yml          # ⭐ GitHub Actions 工作流
├── src/
│   ├── fetcher.py                       # 爬取 aggregator 信息的脚本
│   └── update_subscription.py           # 更新订阅的主脚本
├── docs/
│   └── DEPLOYMENT.md                    # 详细部署指南
├── .gitignore                           # Git 忽略规则
├── config.json                          # 项目配置
├── requirements.txt                     # Python 依赖
└── README.md                            # 项目说明
```

## 📋 部署步骤（3 步完成）

### 1️⃣ 创建 GitHub 仓库
```bash
# 在 GitHub 上创建新仓库：c1a200/wv2ray (公开)
# 然后克隆或初始化
git clone https://github.com/c1a200/wv2ray.git
```

### 2️⃣ 上传项目文件
```bash
cd wv2ray

# 将 e:\pyprojects\wzndn 中的所有文件复制到仓库目录

git add .
git commit -m "初始化 V2ray 自动订阅服务"
git branch -M main
git push -u origin main
```

### 3️⃣ 启用 GitHub Pages
1. 进入仓库 Settings
2. 找到 Pages 选项
3. Source 选择：GitHub Actions
4. 完成！

## ✨ 系统工作流程

```
每天 北京时间 15:00
         ↓
GitHub Actions 自动触发
         ↓
执行 src/update_subscription.py
         ↓
从 GitHub Issue #91 抓取最新 token
         ↓
调用 aggregator API 获取代理节点
         ↓
转换为 v2ray base64 格式
         ↓
生成订阅文件到 docs/
         ↓
上传到 GitHub Pages
         ↓
✅ 您的 V2ray 客户端自动更新
```

## 📌 您的固定订阅链接

```
https://c1a200.github.io/wv2ray/subscribe.txt
```

## 🎯 在 V2ray 中添加订阅

### 方法1: Clash / Clash Meta
```
配置 → 配置文件 → 管理 → 远程订阅
输入链接: https://c1a200.github.io/wv2ray/subscribe.txt
```

### 方法2: V2rayN (Windows)
```
右键托盘图标 → 订阅管理 → 添加订阅源
地址: https://c1a200.github.io/wv2ray/subscribe.txt
```

### 方法3: V2rayA (Web UI)
```
订阅 → 添加订阅
输入链接: https://c1a200.github.io/wv2ray/subscribe.txt
```

### 方法4: Surge / Loon / Quanx
```
订阅管理 → 添加远程订阅
输入链接: https://c1a200.github.io/wv2ray/subscribe.txt
```

## ⚙️ 关键特性

✅ **完全自动化**
- 每天自动更新一次
- 无需手动操作
- aggregator token 自动检测更新

✅ **固定链接**
- 一次配置，永久使用
- V2ray 客户端自动定期获取最新节点
- 无需修改链接

✅ **标准格式**
- Base64 编码的 v2ray 订阅
- 支持所有 v2ray 兼容客户端
- 完整的节点信息

✅ **可靠性**
- GitHub 基础设施保证在线
- 自动失败重试
- 完详细的运行日志

## 📊 更新信息

| 项目 | 值 |
|-----|-----|
| 更新频率 | 每天 1 次 |
| 更新时间 | 北京时间 15:00 (UTC 07:00) |
| 数据源 | aggregator 项目 |
| 节点更新周期 | 源项目每 4 小时更新 |
| 订阅格式 | v2ray (base64) |

## 🔍 监控工作流

部署后可以在以下位置查看运行状态：

```
https://github.com/c1a200/wv2ray/actions
```

- 每次运行的详细日志
- 成功/失败状态
- 执行时间

## ⚠️ 重要提示

1. **仅供学习使用** - 请遵守相关法律法规
2. **隐私保护** - 不要公开分享此链接
3. **Token 更新** - 脚本会自动检测并使用新 token
4. **首次更新** - 工作流首次运行需要 5-10 分钟

## 🎉 完成

现在你拥有一个完全自动化的 V2ray 订阅服务！

- 订阅链接: https://c1a200.github.io/wv2ray/subscribe.txt
- 更新周期: 每天自动更新
- 维护: 零维护成本

---

**需要帮助？**
- 查看详细指南：docs/DEPLOYMENT.md
- GitHub Actions 日志：github.com/c1a200/wv2ray/actions
- 项目说明：README.md
