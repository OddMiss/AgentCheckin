# -*- coding: utf-8 -*-
"""
WorkBuddy 每日自动签到（API 直签版）
不点界面，直接读本地登录态调官方接口。

多账号使用方法：
1. 脚本会自动扫描 C:\\Users 下的 Windows 用户配置文件。
2. 只要某个用户的 WorkBuddy 登录态文件存在，该 Windows 用户就会出现在菜单中。
3. 运行脚本后输入账号编号、逗号分隔的多个编号，或输入 A 进行全部签到。

注意：同一个 Windows 用户的 WorkBuddy 客户端通常只保存当前登录的一个账号。
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

AUTH_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~") + "\\AppData\\Local"),
    "CodeBuddyExtension", "Data", "Public", "auth", "workbuddy-desktop.info"
)
STATUS_URL = "https://www.codebuddy.cn/v2/billing/meter/checkin-activity-status"
CHECKIN_URL = "https://www.codebuddy.cn/v2/billing/meter/daily-checkin"
USER_RESOURCE_URL = "https://www.codebuddy.cn/v2/billing/meter/get-user-resource"
CURRENT_WINDOWS_USER = os.environ.get("USERNAME") or os.path.basename(os.path.expanduser("~"))
WORKBUDDY_APP_ENV = "WORKBUDDY_APP_EXECUTABLE"
AUTH_PATH_PARTS = (
    "AppData", "Local", "CodeBuddyExtension", "Data", "Public", "auth",
    "workbuddy-desktop.info",
)

# WorkBuddy 5.6+ 将 accessToken 加密为 {"$wbEncrypted": 1, "envelope": "..."}。
# 此辅助代码只让 WorkBuddy 自己的 Electron 运行时在内存中解封，并把结果通过
# 子进程管道返回；密钥和令牌都不会写入磁盘或输出到控制台。
WORKBUDDY_DECRYPT_HELPER = r"""
const crypto = require("crypto");

function lengthPrefix(value) {
  const bytes = Buffer.from(value, "utf8");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(bytes.length);
  return Buffer.concat([length, bytes]);
}

const chunks = [];
process.stdin.on("data", (chunk) => chunks.push(chunk));
process.stdin.on("end", () => {
  try {
    const wrapped = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    const envelope = JSON.parse(Buffer.from(wrapped.envelope, "base64").toString("utf8"));
    const storage = process._linkedBinding("electron_browser_workbuddy_storage");
    const secret = JSON.parse(storage.loggerGet()).atRestSecretKey;
    if (typeof secret !== "string" || !secret) throw new Error("missing at-rest secret");

    const key = crypto.createHash("sha256").update(secret, "utf8").digest();
    const suite = Buffer.alloc(4);
    suite.writeUInt32BE(envelope.suite);
    const aad = Buffer.concat([
      Buffer.from("WB-AAD\0", "utf8"), Buffer.from([1]),
      lengthPrefix("WBEV1"), lengthPrefix("sym-v1"), suite,
      lengthPrefix(envelope.keyId), Buffer.from([2, 0, 0]),
    ]);
    const decipher = crypto.createDecipheriv(
      "aes-256-gcm", key, Buffer.from(envelope.nonce, "base64")
    );
    decipher.setAAD(aad);
    decipher.setAuthTag(Buffer.from(envelope.authTag, "base64"));
    const plaintext = Buffer.concat([
      decipher.update(Buffer.from(envelope.ciphertext, "base64")), decipher.final(),
    ]).toString("utf8");
    process.stdout.write(plaintext);
  } catch (error) {
    process.stderr.write(error && error.message ? error.message : "decrypt failed");
    process.exitCode = 1;
  }
});
"""


def mask_token(t):
    """安全脱敏：一个真实字符都不输出。

    注意：不要写成 t[:15] + "..." + t[-8:]，
    尾部 8 位同样是真实 token 字符，属于泄露。
    """
    if not t or len(t) < 20:
        return "(无)"
    return "已加载（内容已隐藏）"


def find_workbuddy_executable():
    """查找用于解封新版登录态的本机 WorkBuddy 客户端。"""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.environ.get(WORKBUDDY_APP_ENV, ""),
        r"D:\WorkBuddy\WorkBuddy.exe",
        os.path.join(local_app_data, "Programs", "WorkBuddy", "WorkBuddy.exe"),
        os.path.join(local_app_data, "WorkBuddy", "WorkBuddy.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "WorkBuddy", "WorkBuddy.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def decrypt_workbuddy_value(value):
    """在 WorkBuddy 自身运行时中解开新版的加密字段。"""
    if isinstance(value, str):
        return value, None
    if not isinstance(value, dict) or value.get("$wbEncrypted") != 1:
        return None, "accessToken 格式无法识别"
    if not isinstance(value.get("envelope"), str):
        return None, "加密 accessToken 缺少 envelope"

    executable = find_workbuddy_executable()
    if not executable:
        return None, (
            "检测到新版加密登录态，但找不到 WorkBuddy.exe。"
            "请设置 %s 指向 WorkBuddy.exe" % WORKBUDDY_APP_ENV
        )

    environment = os.environ.copy()
    environment["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        result = subprocess.run(
            [executable, "-e", WORKBUDDY_DECRYPT_HELPER],
            input=json.dumps(value, separators=(",", ":")),
            text=True,
            capture_output=True,
            timeout=20,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "WorkBuddy 客户端无法启动或解封超时"

    if result.returncode != 0 or not result.stdout:
        return None, "WorkBuddy 客户端无法解开加密登录态"
    return result.stdout, None


def find_windows_accounts(users_dir=None):
    """发现保存了 WorkBuddy 登录态的 Windows 用户配置文件。"""
    if users_dir is None:
        # 当前用户目录通常为 C:\\Users\\<用户名>，其父目录就是所有用户配置文件的目录。
        users_dir = os.path.dirname(os.path.expanduser("~"))

    accounts = []
    seen_auth_files = set()
    try:
        profiles = os.scandir(users_dir)
    except OSError as e:
        print("❌ 无法扫描 Windows 用户目录 %s：%s" % (users_dir, e))
        return accounts

    with profiles:
        for profile in profiles:
            if not profile.is_dir():
                continue
            auth_file = os.path.join(profile.path, *AUTH_PATH_PARTS)
            try:
                if not os.path.isfile(auth_file):
                    continue
            except OSError:
                # 个别用户配置文件可能没有访问权限，跳过即可。
                continue

            normalized_path = os.path.normcase(os.path.abspath(auth_file))
            if normalized_path in seen_auth_files:
                continue
            seen_auth_files.add(normalized_path)
            accounts.append({"windows_user": profile.name, "auth_file": auth_file})

    # 避免特殊的用户目录位置导致当前账号未被扫描到。
    current_auth_file = os.path.normcase(os.path.abspath(AUTH_FILE))
    if os.path.isfile(AUTH_FILE) and current_auth_file not in seen_auth_files:
        accounts.append({
            "windows_user": CURRENT_WINDOWS_USER,
            "auth_file": AUTH_FILE,
        })

    return sorted(accounts, key=lambda account: account["windows_user"].lower())


def load_auth(auth_file):
    if not os.path.exists(auth_file):
        return None, "找不到登录态文件：%s" % auth_file
    try:
        with open(auth_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, "登录态文件解析失败：%s" % e
    tok, token_error = decrypt_workbuddy_value(
        data.get("auth", {}).get("accessToken")
    )
    uid = data.get("account", {}).get("uid")
    if not tok:
        return None, token_error or "登录态文件里没有 accessToken"
    if not isinstance(uid, str) or not uid:
        return None, "登录态文件里没有 uid"
    # 留出 5 分钟余量判断是否过期
    expires = data.get("auth", {}).get("expiresAt", 0)
    if isinstance(expires, (int, float)) and expires < (time.time() * 1000 + 5 * 60 * 1000):
        return None, "accessToken 快过期或已过期，请先打开一次 WorkBuddy 刷新登录态"
    nickname = data.get("account", {}).get("nickname", "")
    # 昵称不影响接口鉴权；新版若将其加密，回退显示 uid，避免解封无关个人信息。
    if not isinstance(nickname, str):
        nickname = ""
    return {"token": tok, "uid": uid, "nickname": nickname}, None


def api_post(url, token, uid, payload=None, extra_headers=None):
    headers = {
        "Authorization": "Bearer " + token,
        "X-User-Id": uid,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload if payload is not None else {}).encode("utf-8"),
        headers=headers,
    )
    try:
        r = urllib.request.urlopen(req, timeout=20)
        return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"msg": body[:200]}
    except Exception as e:
        return -1, {"msg": str(e)}


def get_nested_value(data, path):
    """安全读取嵌套 JSON 字段。"""
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def get_resource_items(response):
    """兼容积分接口已知的几种返回层级。"""
    paths = (
        ("data", "Response", "Data", "Accounts"),
        ("data", "data", "Response", "Data", "Accounts"),
        ("data", "resources"),
        ("data", "data", "resources"),
    )
    for path in paths:
        items = get_nested_value(response, path)
        if isinstance(items, list):
            return items
    return None


def to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def format_credits(value):
    """以不丢失小数精度的方式显示积分。"""
    if value == value.to_integral():
        return "{:,}".format(int(value))
    return format(value.normalize(), ",f").rstrip("0").rstrip(".")


def get_remaining_credits(resource):
    """读取一个资源包的周期剩余额度，兼容接口字段命名变化。"""
    for key in (
        "CycleCapacityRemainPrecise",
        "CycleCapacityRemain",
        "CapacityRemainPrecise",
        "CapacityRemain",
    ):
        if key in resource:
            value = to_decimal(resource[key])
            if value is not None:
                return value

    # 少数旧响应不直接返回剩余量时，用总量减已用量兜底。
    capacity = to_decimal(resource.get("CycleCapacitySizePrecise",
                                    resource.get("CapacitySizePrecise")))
    used = to_decimal(resource.get("CycleCapacityUsedPrecise",
                                resource.get("CapacityUsedPrecise")))
    if capacity is not None and used is not None and capacity >= 0:
        return max(capacity - used, Decimal("0"))
    return None


def show_credit_balance(auth):
    """查询并打印当前可用积分；接口为只读，不会消耗积分。"""
    payload = {
        "PageNumber": 1,
        "PageSize": 100,
        "ProductCode": "p_tcaca",
        "Status": [0, 3],
        "OnlyValidPeriod": True,
    }
    status, response = api_post(
        USER_RESOURCE_URL,
        auth["token"],
        auth["uid"],
        payload=payload,
        extra_headers={
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0",
        },
    )
    if status != 200 or response.get("code") not in (0, 200):
        print("⚠️  积分查询失败：HTTP %d / %s" % (
            status, response.get("msg", response)))
        return False

    resources = get_resource_items(response)
    if resources is None:
        print("⚠️  积分查询成功，但返回格式无法识别。")
        return False

    available = []
    unlimited = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        remaining = get_remaining_credits(resource)
        if remaining is None:
            continue
        name = (resource.get("PackageName") or resource.get("ProductName") or
                resource.get("PackageCode") or "未命名资源包")
        if remaining < 0:
            unlimited.append(name)
        elif remaining > 0:
            available.append((name, remaining))

    print("当前剩余积分：")
    if available:
        for name, remaining in available:
            print("  • %s：%s" % (name, format_credits(remaining)))
        total = sum((remaining for _, remaining in available), Decimal("0"))
        print("  合计：%s 积分" % format_credits(total))
    else:
        print("  0 积分")
    for name in unlimited:
        print("  • %s：不限量" % name)
    return True


def finish_checkin(auth, code, message):
    """在成功完成签到流程后展示最新积分余额。"""
    show_credit_balance(auth)
    return code, message


def checkin(account):
    """为一个账号签到，返回 (退出码, 结果说明)。"""
    windows_user = account.get("windows_user") or "未填写"
    auth_file = account.get("auth_file")
    if not auth_file:
        print("❌ 账号配置中缺少 auth_file。")
        return 3, "账号配置不完整"

    auth, err = load_auth(auth_file)
    if err:
        print("❌ %s" % err)
        return 3, "登录态不可用"

    print("Windows 账号：%s" % windows_user)
    print("WorkBuddy 用户：%s  token：%s" % (
        auth["nickname"] or auth["uid"][:8], mask_token(auth["token"])))

    # 1. 查状态
    status, resp = api_post(STATUS_URL, auth["token"], auth["uid"])
    if status != 200 or resp.get("code") != 0:
        print("❌ 查询签到状态失败：HTTP %d / %s" % (status, resp.get("msg", resp)))
        return 4, "查询状态失败"

    d = resp.get("data", {})
    active = d.get("active", False)
    today_done = d.get("today_checked_in", False)
    streak = d.get("streak_days", 0)
    daily = d.get("daily_credit", 0)
    today_got = d.get("today_credit", 0)
    theme = d.get("theme_name", "") or d.get("activity_name", "")

    if not active:
        print("ℹ️  当前没有进行中的签到活动，无需领取。")
        return finish_checkin(auth, 0, "无进行中的活动")

    print("活动：%s  每日 %d 积分  连签 %d 天" % (theme or "Buddy加油站", daily, streak))

    if today_done:
        print("✅ 今天已经签到过了，获得 %d 积分，明天再来。" % today_got)
        return finish_checkin(auth, 0, "今天已签到")

    # 2. 执行签到
    print("🔔 今天还没签，正在领取...")
    status2, resp2 = api_post(CHECKIN_URL, auth["token"], auth["uid"])
    code2 = resp2.get("code")
    msg2 = resp2.get("msg", "")

    if status2 == 200 and code2 == 0:
        status, resp = api_post(STATUS_URL, auth["token"], auth["uid"])
        if status == 200 and resp.get("code") == 0:
            today_got = resp.get("data", {}).get("today_credit", today_got)
            streak = resp.get("data", {}).get("streak_days", streak)
        print("✅ 签到成功，获得 %d 积分，当前连签 %d 天。" % (today_got, streak))
        return finish_checkin(auth, 0, "签到成功")
    elif code2 == 10001:
        print("✅ 今天已经签到过了（%s），明天再来。" % msg2)
        return finish_checkin(auth, 0, "今天已签到")
    else:
        print("❌ 签到失败：HTTP %d / code=%s / %s" % (status2, code2, msg2))
        return 5, "签到失败"


def choose_accounts(accounts):
    """让用户按编号选择一个、多个或全部账号。"""
    if not accounts:
        print("❌ 没有发现 WorkBuddy 登录态。请先在对应的 Windows 账号中登录 WorkBuddy。")
        return None

    print("\n可签到账号：")
    for index, account in enumerate(accounts, start=1):
        print("  %d. Windows 账号：%s" % (
            index, account.get("windows_user") or "未填写"))
    print("  A. 全部账号")

    while True:
        try:
            choice = input("\n请选择（如 1、1,3 或 A；直接回车取消）：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return None

        if not choice:
            print("已取消。")
            return None
        if choice.lower() in ("a", "all", "0"):
            return accounts

        try:
            indexes = [int(item.strip()) for item in choice.split(",")]
            if not indexes or any(index < 1 or index > len(accounts) for index in indexes):
                raise ValueError
        except ValueError:
            print("输入无效，请输入账号编号、逗号分隔的编号，或 A。")
            continue

        # 保留用户输入的顺序，同时去除重复编号。
        selected = []
        for index in indexes:
            account = accounts[index - 1]
            if account not in selected:
                selected.append(account)
        return selected


def main():
    print("WorkBuddy 每日签到  %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    accounts = choose_accounts(find_windows_accounts())
    if accounts is None:
        return 0

    results = []
    for index, account in enumerate(accounts, start=1):
        windows_user = account.get("windows_user") or "未填写"
        print("\n%s" % ("=" * 18))
        print("[%d/%d] Windows 账号：%s" % (index, len(accounts), windows_user))
        code, message = checkin(account)
        results.append((windows_user, code, message))

    print("\n签到结果汇总：")
    for windows_user, code, message in results:
        icon = "✅" if code == 0 else "❌"
        print("%s Windows 账号 %s：%s" % (icon, windows_user, message))
    return 0 if all(code == 0 for _, code, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
