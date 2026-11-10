# AgentCheckin

一个运行于 Windows 的多客户端签到工具。它会自动发现已登录的 WorkBuddy、Trae CN 和 Qoder CN，让你选择单项、多项或全部执行。

## 功能

- 自动识别本机已登录的 WorkBuddy、Trae CN 和 Qoder CN
- 支持单选、逗号分隔多选与全选签到
- 自动跳过当天已签到的账号
- 显示连续签到天数、当日获得积分和当前可用积分
- 支持 Qoder CN 的可领取积分活动福利
- 支持 `--status` 仅查询模式，不会发起任何领取请求
- 仅使用本机已有登录态；不会打印完整令牌，也不会上传登录信息

## 使用条件

- Windows
- 已安装并登录相应的桌面客户端
- Python 3
- 首次使用 Trae CN 或 Qoder CN 时，请执行：`python -m pip install -r requirements.txt`

## 运行

双击 `checkin.bat`，或在项目目录中运行：

```powershell
python DailyCheckin.py
```

只查询状态、不领取积分：

```powershell
python DailyCheckin.py --status
```

WorkBuddy 会扫描以下位置中存在的登录态：

```text
C:\Users\<Windows 用户名>\AppData\Local\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info
```

Trae CN 会扫描各 Windows 配置文件 `AppData\\Roaming` 或 `AppData\\Local` 下的 `TRAE SOLO CN` / `TRAE CN` 登录文件。Qoder CN 会扫描当前 Windows 用户数据目录中的 `auth.v1.dat` 与 `Local State`。

输入编号可选择单个项目；如输入 `1,3` 可选择多个项目；输入 `A`、`all` 或 `0` 可签到全部已发现项目。

Qoder 的本地密钥由 Windows DPAPI 按当前 Windows 用户保护。脚本不会尝试绕过这一保护，因此其他 Windows 用户的 Qoder 登录态不会列入菜单；请在对应用户会话中运行脚本。

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

WorkBuddy 登录态包含访问令牌，应视为密码处理。`.gitignore` 已排除登录态、令牌、环境变量文件、私钥、缓存和日志；提交前仍建议检查暂存文件，确认不含个人信息。

本项目会向你选择的平台发送签到或领取请求；`--status` 模式则只查询状态。WorkBuddy 的积分查询为只读操作，不会消耗积分。

Trae CN 与 Qoder CN 的本地登录态和签到逻辑参考本机项目 `D:\AI_Data\workbuddy-trae-auto-signin`，并已按本项目的多账号交互流程重新整合。这是非官方个人工具；客户端存储格式和接口可能随版本变动，请自行遵守各平台服务条款并在异常时停止使用。

## 参考来源

- 签到接口方案参考：[WorkBuddy 积分焦虑终结者：让 AI 每天自动签到领积分，一次配置永久躺赚](https://developer.cloud.tencent.com/article/2734615)
