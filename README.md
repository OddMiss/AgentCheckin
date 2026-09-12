# WorkBuddyCheckin

一个运行于 Windows 的 WorkBuddy 每日签到脚本。它会自动发现已登录 WorkBuddy 的 Windows 用户配置文件，让你选择单个、多个或全部账号签到，并在完成后显示当前可用积分。

## 功能

- 自动识别本机已登录 WorkBuddy 的 Windows 账号
- 支持单选、逗号分隔多选与全选签到
- 自动跳过当天已签到的账号
- 显示连续签到天数、当日获得积分和当前可用积分
- 仅使用本机已有登录态；不会打印完整令牌，也不会上传登录信息

## 使用条件

- Windows
- 已安装并登录 WorkBuddy
- Python 3

## 运行

双击 `workbuddycheck.bat`，或在项目目录中运行：

```powershell
python WorkBuddyDailyCheckin.py
```

脚本会扫描以下位置中存在的 WorkBuddy 登录态：

```text
C:\Users\<Windows 用户名>\AppData\Local\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info
```

输入账号编号可签到单个账号；如输入 `1,3` 可选择多个账号；输入 `A`、`all` 或 `0` 可签到全部已发现账号。

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

本项目只查询 WorkBuddy 的签到和积分信息。积分查询为只读操作，不会消耗积分。

## 参考来源

- 签到接口方案参考：[WorkBuddy 积分焦虑终结者：让 AI 每天自动签到领积分，一次配置永久躺赚](https://developer.cloud.tencent.com/article/2734615)
