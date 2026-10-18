# Qoder CN 每日签到脚本（qoder_checkin.py）使用指南

> [!NOTE]
> 本文档对应的脚本是 [`qoder_checkin.py`](../qoder_checkin.py)（原名 `checkin.py`），与仓库的 `signin.py`（WorkBuddy 签到）、`trae_checkin.py`（Trae CN 签到）**相互独立**，鉴权方式、目标站点、部署方式都不同，不要混用。

## 一、这是什么

一个自动领取 **Qoder CN 每日签到 100 Credits** 的 Python 脚本，主打青龙面板部署，也支持本地直接运行。

**活动规则**（实测结论，改动前先读脚本头部注释）：

- 每天 **10:00（UTC+8）** 开新一轮窗口，持续到**次日 10:00** 前
- 每轮限领一次 100 Credits，自领取起 30 天有效，**错过不补**

**为什么走 PAT 而不是读客户端本地凭证**：

| 方案 | 问题 |
|---|---|
| 读客户端本地凭证（网上常见做法） | ① DPAPI 绑定 Windows 用户，青龙容器里用不了；② refreshToken（`drt-`）一次一换，静态环境变量写不回去，脚本一刷新客户端就掉登录 |
| **本脚本：PAT 换 jobToken** | PAT 是官方给 CLI/CI 无头环境用的，每次运行现换一个 24h 的 `jt-`，用完即弃、不落盘，不碰 DPAPI、不影响客户端登录 |

鉴权链路：

```
QODERCN_PAT (pt-…，永久)
  --POST /api/v1/jobToken/exchange-->
jobToken (jt-…，24h)  --Authorization: Bearer-->  业务接口
```

## 二、准备工作

1. **Python 3 + requests 库**

   ```bash
   pip install requests
   ```

2. **创建 PAT**：打开 <https://qoder.cn/account/integrations> → 新建个人访问令牌（`pt-` 开头）→ **建完立刻复制，页面关了不再显示**

### 令牌怎么安全存放

脚本**只读环境变量** `QODERCN_PAT`（`os.getenv`），不读取任何文件，这是有意设计。

- **Windows 推荐**：用户级环境变量，不进 git、新终端直接生效：

  ```powershell
  [Environment]::SetEnvironmentVariable("QODERCN_PAT", "pt-账号1&pt-账号2", "User")
  ```

- **青龙**：存在面板「环境变量」里（落在容器卷的数据库中），无需额外处理
- ⚠️ 若图省事在仓库目录建 `.env` / `.pat` 文件存令牌，务必先把该文件名加进 `.gitignore`——否则某天 `git add .` 可能把它提交上去（本仓库 `.gitignore` 已包含 `.env`）

## 三、青龙面板部署（推荐方式）

| 步骤 | 操作 |
|---|---|
| ① 放脚本 | 把 `qoder_checkin.py` 上传到青龙的 `scripts` 目录 |
| ② 加环境变量 | 名称 `QODERCN_PAT`，值 `pt-xxxxxxxx`；多账号用 `&` 或换行分隔：`pt-账号1&pt-账号2` |
| ③ 建定时任务 | 调度表达式填 `5 10 * * *`（每天 10:05） |
| ④ 装依赖 | 订阅管理里加 `requests`，或进容器 `pip install requests` |

**为什么是 10:05**（别乱改）：

- 不能改到 10:00 之前——会落到**前一天**的窗口，领的是几小时后就关闭的那轮，失败重试余量极小
- 不要一天跑两次以上——同一窗口多跑没有额外收益，只多打接口
- 10:05 给上游切窗口留了 5 分钟缓冲，且当天失败后还有近 24 小时重试余量

## 四、本地直接运行（不走青龙）

```powershell
# Windows PowerShell
$env:QODERCN_PAT = "pt-你的令牌"
python qoder_checkin.py
```

```bash
# macOS / Linux
export QODERCN_PAT="pt-你的令牌"
python3 qoder_checkin.py
```

### 多账号

环境变量的值用 `&` 或换行分隔多个 PAT：

```
QODERCN_PAT=pt-账号1&pt-账号2&pt-账号3
```

- 脚本内部按 `&` 和换行切分、去空白、**去重**（重复的 PAT 只跑一次）
- **单账号失败不影响其余账号**——每个账号独立隔离，一个 PAT 失效其余照常签
- 日志以 `账号N(脱敏PAT)` 标识每个账号

## 五、输出怎么读

```
[qoder] 开始签到：共 1 个账号
[qoder] 账号1(pt-xxxx***wxyz) jobToken 交换成功（有效期 24h）
[qoder] 账号1(pt-xxxx***wxyz) 活动列表：共 N 条，可领 1 条
[qoder] 账号1(pt-xxxx***wxyz) ✅ 签到成功 +100 CREDITS
[qoder] 账号1(pt-xxxx***wxyz) 余额：userQuota ...（套餐额度）；addOnQuota ...（资源包，签到发放进这里）
```

| 输出 | 含义 |
|---|---|
| `✅ 签到成功 +100 CREDITS` | 正常领取 |
| `✅ 签到成功 +N（replayed，权益不重复发放）` | 重复领取，接口幂等返回，不算失败 |
| `✅ 今天已签到（无需操作）` | 已领过，正常 |
| `⚠️ 当前没有进行中的签到活动` | 活动可能已下线 |
| `❌ Qoder PAT 已失效` | 重新登录创建 PAT 并更新环境变量 |

- 签到的 100 Credits 落在 **addOnQuota（资源包）**，不在 userQuota（套餐额度），查余额时看对地方
- **退出码**：全部账号成功为 0，任一失败为 1，青龙可据此触发告警
- **通知**：脚本按多条候选路径查找 `sendNotify.py`（当前目录、`/ql/data/scripts` 等），找到即推送；没有则降级打印到日志。通知发送失败**绝不会**中断签到任务
- 日志中 PAT 只显示脱敏形式（前 6 位 + 尾 4 位），可安全外发

## 六、注意事项

- ⚠️ PAT 等同账号权限，泄露即等于账号泄露，别提交进 git、别外传
- ⚠️ 脚本只存 PAT、每次现换 jobToken，不会挤掉你电脑上 Qoder 客户端的登录
- 常见报错排查：
  - `网络请求失败` → 本机/容器连不上 `openapi.qoder.com.cn`
  - `接口返回异常状态 4xx` → 检查 PAT 是否有效、活动是否还在
  - `接口结构未识别（schema_changed）` → Qoder 侧接口有变动，对照脚本头部的接口清单核对

## 七、接口清单（全部本机实测）

| 接口 | 说明 |
|---|---|
| `POST /api/v1/jobToken/exchange` | PAT 换 jobToken（`Cosy-ClientType: 5`，注意与业务接口不同） |
| `GET /sash/api/v1/me/campaigns` | 活动列表（`Cosy-ClientType: 10`，漏了会静默返回空数组） |
| `POST /sash/api/v1/me/campaigns/{campaignId}/claim` | 领取（body `{}`，幂等，重复领返回 replayed） |
| `GET /sash/api/v2/me/usage` | 余额（userQuota / addOnQuota） |

领取必须用 `campaignId`（UUID），不是 `campaignKey`（`act-YYYYMMDD-NNN`）。

**领取判定**：只领 `actionType == CLAIM_BENEFIT` **且** `claimStatus == CLAIMABLE` **且** `campaignId` 非空的条目——只按其中一个条件判会误领 VIEW_DETAILS / ACHIEVEMENT_NOT_COMPLETED，两类实测都存在，两个条件必须同时满足。

## 八、安全说明与免责声明

- 脚本**绝不回显完整 PAT / jobToken**，日志只显示前 6 位 + 尾 4 位，可安全外发
- 错误文案不回显服务端响应体，避免凭证类信息进入日志/通知
- PAT 只在内存中用于 exchange 请求，不写临时文件、不落盘缓存
- 单账号异常隔离不中断其余账号，请求超时 20 秒
- 本脚本为**非官方**工具，与腾讯 / Qoder 无隶属关系。接口系逆向官方客户端所得，可能随时变动且不另行通知，使用风险自负，请遵守相关服务条款
