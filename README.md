# AgentCheckin

一个运行于 Windows 的多客户端签到工具。它会自动发现已登录的 WorkBuddy、Trae CN、Qoder CN、豆包工作和 MiniMax Code，让你选择单项、多项或全部执行。

## 平台一览

| 平台 | 默认运行范围 | 输出内容 | 备注 |
| --- | --- | --- | --- |
| WorkBuddy | 可扫描多个 Windows 用户 | 签到状态、连签、资源包余额 | 新版加密登录态由客户端运行时在内存中读取 |
| Trae CN | 可扫描多个 Windows 用户 | 用户名、已脱敏手机号、积分 | 按平台设备规则执行签到 |
| Qoder CN | 当前 Windows 用户；其他用户需密码 | 用户名、活动领取结果 | 平台不提供总积分余额接口 |
| 豆包工作 | 当前 Windows 用户；其他用户需密码 | 用户标识、已脱敏手机号、签到结果 | 使用桌面端登录态与 Playwright |
| MiniMax Code | 当前 Windows 用户；其他用户需密码 | 用户标识、签到结果、可用 OP 积分 | OAuth 登录态可自动刷新并写回客户端原文件 |

| 交互 | 行为 |
| --- | --- |
| 输入 `1` | 选择一项 |
| 输入 `1,3` | 选择多项 |
| 输入 `A`、`all`、`0` 或直接回车 | 选择列表中全部项目 |
| `Ctrl+C` | 退出，不执行签到 |
| `--status` | 只读模式，不发起领取；MiniMax 仅确认本机登录态，不刷新 OAuth |

## 使用条件

| 条件 | 说明 |
| --- | --- |
| 系统 | Windows |
| 客户端 | 已安装并登录要签到的平台客户端 |
| Python | 可在命令行运行 `python` |
| Python 依赖 | 首次使用 Trae CN、Qoder CN、豆包工作或 MiniMax Code 前执行 `python -m pip install -r requirements.txt` |
| 豆包浏览器 | 跨 Windows 用户运行豆包工作时启动器会自动安装 Chromium；若直接运行模块时缺失，可执行 `python -m playwright install chromium` |

## 运行

双击 `checkin.bat`，或在项目目录中运行：

```powershell
python DailyCheckin.py
```

只查询状态、不领取积分：

```powershell
python DailyCheckin.py --status
```

## 登录态发现与跨用户运行

| 平台 | 自动发现的位置 | 可直接运行的 Windows 用户 | 其他 Windows 用户 |
| --- | --- | --- | --- |
| WorkBuddy | `%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info` | 所有已发现用户 | 直接按对应配置文件运行 |
| Trae CN | `AppData\Roaming` 或 `AppData\Local` 下的 `TRAE SOLO CN` / `TRAE CN` | 所有已发现用户 | 直接按对应配置文件运行 |
| Qoder CN | `AppData\Roaming` / `AppData\Local` 中的 `auth.v1.dat` 与 `Local State` | 当前用户 | 菜单单独列出，需输入该 Windows 用户密码 |
| 豆包工作 | `%LOCALAPPDATA%` 下的豆包客户端 `Local State` | 当前用户 | 菜单单独列出，需输入该 Windows 用户密码 |
| MiniMax Code | `~\.minimax\auth\prod\cn\mcode-public\auth.json` | 当前用户 | 菜单单独列出，需输入该 Windows 用户密码 |

Qoder、豆包工作与 MiniMax Code 的认证或设备状态受对应 Windows 用户保护。其他用户的项目会以“需 Windows 密码”单独显示；选择后，普通项目先完成，Windows 再通过 `runas` 为该用户启动仅包含所选平台的子任务。同一 Windows 用户选中多项时只需认证一次。

| Windows 密码处理 | 行为 |
| --- | --- |
| 输入位置 | Windows `runas` 的系统控制台提示 |
| Python / 命令行参数 / 日志 / Git | 不接收、不保存、不输出密码 |
| 适用凭据 | Windows 用户登录密码；不支持 Windows Hello PIN |

## 新版 WorkBuddy 兼容性

新版 WorkBuddy 可能会加密本机登录态。脚本会自动识别该格式，并仅在内存中调用已安装的 WorkBuddy 客户端读取所需的登录令牌；令牌和解封密钥不会写入文件或显示在控制台。

这不需要打开 WorkBuddy 图形界面。脚本会短暂以后台 Node 模式启动客户端自带的 Electron 运行时，并调用其本机凭据存储能力解封登录态；令牌仅经子进程管道交给脚本，用完即释放。脚本不会修改 WorkBuddy 的登录文件、不会保存解封密钥，也不会上传令牌。

默认会查找常见安装位置及本机 `D:\WorkBuddy\WorkBuddy.exe`。如果客户端安装在其他位置，可在运行前设置环境变量：

```powershell
$env:WORKBUDDY_APP_EXECUTABLE = "C:\\你的路径\\WorkBuddy.exe"
```

## 展示示例

```text
==================
[2/3] Windows 账号：...
Windows 账号：...
WorkBuddy 用户：...  token：已加载（内容已隐藏）
活动：Buddy加油站  每日 100 积分  连签 1 天
✅ 今天已经签到过了，获得 100 积分，明天再来。
当前剩余积分：
  • CodeBuddy个人版拉新权益包：1,000
  • CodeBuddy个人版国内运营裂变包：123.99000023
  • CodeBuddy个人版国内运营裂变包：100
  • CodeBuddy个人版国内运营裂变包：300
  • CodeBuddy个人版国内运营裂变包：100
  • CodeBuddy个人版国内运营裂变包：100
  合计：1,723.99000023 积分
```

## 隐私与安全

| 项目 | 安全边界 |
| --- | --- |
| 通用登录态 | 令牌、Cookie、刷新令牌均应视为密码；`.gitignore` 已排除凭据、私钥、缓存、日志和 MiniMax 本地状态 |
| `--status` | 不会发起领取；MiniMax 仅检查登录态文件存在，避免 OAuth 刷新与原地写回 |
| WorkBuddy | 解密与令牌只在内存中短暂使用；积分查询为只读，不消耗积分 |
| Qoder CN | 仅提供活动及可领取福利，不提供账号总积分或套餐余额；脚本不会将活动奖励误显示为余额 |
| 豆包工作 | 只显示安全结果摘要，不显示 Cookie、令牌、客户端目录或截图路径；`doubao_data/` 永不提交。客户端锁库时，上游模块可能请求一次 Windows 管理员授权 |
| MiniMax Code | OAuth access token 有效期较短。需要签到时，模块可使用 refresh token 刷新并**原地写回 MiniMax 客户端自身**的 `auth.json` / `auth-state.json`；不创建额外的凭据副本 |
| 用户手机号 | 只显示客户端已有的脱敏格式；绝不输出完整手机号 |

这是非官方个人工具。客户端存储格式和接口可能随版本变动；请仅用于自己的账号，遵守平台服务条款，并在异常时停止使用。

## 参考来源

- 签到接口方案参考：[WorkBuddy 积分焦虑终结者：让 AI 每天自动签到领积分，一次配置永久躺赚](https://developer.cloud.tencent.com/article/2734615)
- 豆包工作模块参考并保留来源：[tututashu/doubao-auto-checkin](https://github.com/tututashu/doubao-auto-checkin)（MIT License；完整许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)）
- MiniMax Code 模块参考本机项目 `D:\AI_Data\AIAutomator`（MIT License；完整许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)）
