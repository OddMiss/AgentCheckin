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
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    Cipher = algorithms = modes = None

# 直接在旧版 Windows 控制台执行时，GBK 可能无法编码状态图标。保留中文输出，
# 仅将无法表示的字符替换，避免脚本因为显示文本而中断。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, OSError):
        pass

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

TRAE_AUTH_KEY = "iCubeAuthInfo://icube.cloudide"
TRAE_DC_KEY_PREFIX = "iCubeAuthInfo://icube-dc:"
TRAE_PRODUCT_DIRS = ("TRAE SOLO CN", "TRAE CN", "Trae CN")
TRAE_STORAGE_PARTS = ("User", "globalStorage", "storage.json")
TRAE_STATUS_URL = "https://api.trae.cn/trae/api/v2/ug/checkin_credits/status"
TRAE_CLAIM_URL = "https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim"

# Qoder 国际版与国区版使用不同的数据目录名；新版国区客户端使用
# com.qodercn.app.stable，需与旧版目录一起探测。
QODER_PRODUCT_DIRS = ("com.qodercn.app.stable", "com.qoder.app.stable", "Qoder", "qoder")
QODER_AUTH_BASENAME = "auth.v1.dat"
QODER_LOCAL_STATE_BASENAME = "Local State"
QODER_API_BASES = ("https://openapi.qoder.com.cn", "https://openapi.qoder.sh")
QODER_CAMPAIGNS_PATH = "/sash/api/v1/me/campaigns"
QODER_REFRESH_PATH = "/api/v1/deviceToken/refresh"
QODER_EXPIRY_MARGIN = 300.0
QODER_PROFILE_ROOT_ENV = "QODER_PROFILE_ROOT"
DOUBAO_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doubao_checkin.py")
BOUND_CHECKIN_BATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_bound_checkin.bat")
BOUND_PLATFORM_KEYS = {"Qoder CN": "qoder", "豆包工作": "doubao", "MiniMax Code": "minimax"}
MINIMAX_OAUTH_PARTS = (".minimax", "auth", "prod", "cn", "mcode-public", "auth.json")
MINIMAX_LEGACY_PARTS = (".minimax", "local-runtime.auth.json")
MINIMAX_CONFIG_PARTS = ("AppData", "Roaming", "minimax", "minimax-agent-cn-config.json")

# Trae 客户端加密格式中使用的固定参数。它们不是账号密钥；实际会话令牌仍只
# 在进程内短暂使用，永不输出或写入文件。
_TR_EM, _TR_RV, _TR_RH = 6, 32, 64
_TR_URE = bytes([82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
                 124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
                 84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
                 8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37])
_TR_DRE = bytes([31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
                 96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
                 160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
                 23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125])

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


def require_crypto():
    """在真正需要解密时才检查依赖，使 WorkBuddy 仍能单独使用。"""
    if Cipher is None:
        raise RuntimeError("缺少 cryptography 依赖。请运行：python -m pip install -r requirements.txt")


def request_json(url, headers, method="POST", payload=None, timeout=30):
    """统一的 JSON 网络出口；出错时绝不包含或打印认证头。"""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, {"raw": raw[:500]}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw[:500]}
    except Exception as error:
        return -1, {"error": str(error)}


def decrypt_trae_auth(encoded):
    """在内存中解开 Trae storage.json 的 iCube 登录信息。"""
    require_crypto()
    if not isinstance(encoded, str):
        raise ValueError("iCube 登录信息不是字符串")
    try:
        encrypted = base64.b64decode(encoded)
    except Exception as error:
        raise ValueError("Trae 登录信息无法 Base64 解码：%s" % error)
    if len(encrypted) < _TR_EM + _TR_RV + 16:
        raise ValueError("Trae 登录信息格式过短")

    seed = encrypted[_TR_EM:_TR_EM + _TR_RV]
    first_hash = hashlib.sha512(seed).digest()
    mixed = bytes(left ^ right for left, right in zip(_TR_URE, _TR_DRE))
    key_iv = hashlib.sha512(first_hash + mixed).digest()
    ciphertext = encrypted[_TR_EM + _TR_RV:]
    ciphertext = ciphertext[:len(ciphertext) // 16 * 16]
    if not ciphertext:
        raise ValueError("Trae 登录信息密文为空")

    decryptor = Cipher(algorithms.AES(key_iv[:16]), modes.CBC(key_iv[16:32])).decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    padding = plaintext[-1] if plaintext else 0
    if 1 <= padding <= 16:
        plaintext = plaintext[:-padding]
    try:
        return json.loads(plaintext[_TR_RH:].decode("utf-8"))
    except Exception as error:
        raise ValueError("Trae 登录信息解密后格式异常：%s" % error)


def find_trae_accounts(users_dir=None):
    """发现各 Windows 配置文件中的 Trae CN 登录态。"""
    users_dir = users_dir or os.path.dirname(os.path.expanduser("~"))
    accounts, seen = [], set()
    override = os.environ.get("TRAE_AUTH_FILE", "")
    candidates = []
    if override:
        candidates = [("环境变量", path.strip()) for path in override.split(";") if path.strip()]
    else:
        try:
            profiles = [item for item in os.scandir(users_dir) if item.is_dir()]
        except OSError:
            profiles = []
        for profile in profiles:
            for base in ("AppData\\Roaming", "AppData\\Local"):
                for product in TRAE_PRODUCT_DIRS:
                    candidates.append((profile.name, os.path.join(
                        profile.path, base, product, *TRAE_STORAGE_PARTS)))
    for windows_user, path in candidates:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen or not os.path.isfile(path):
            continue
        seen.add(normalized)
        accounts.append({"platform": "Trae CN", "windows_user": windows_user,
                         "auth_file": path})
    return sorted(accounts, key=lambda item: (item["windows_user"].lower(), item["auth_file"].lower()))


def load_trae_session(storage_path):
    try:
        with open(storage_path, encoding="utf-8") as handle:
            storage = json.load(handle)
    except Exception as error:
        raise ValueError("无法读取 Trae 登录文件：%s" % error)
    auth = decrypt_trae_auth(storage.get(TRAE_AUTH_KEY))
    token = auth.get("token") if isinstance(auth, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("Trae 登录信息缺少令牌")
    device_id = next((key[len(TRAE_DC_KEY_PREFIX):] for key in storage
                      if isinstance(key, str) and key.startswith(TRAE_DC_KEY_PREFIX)
                      and key[len(TRAE_DC_KEY_PREFIX):]), None)
    user_name, masked_mobile = trae_user_identity(auth)
    return {"token": token, "device_id": device_id,
            "machine_id": storage.get("telemetry.machineId"),
            "user_name": user_name, "masked_mobile": masked_mobile}


def trae_user_identity(auth):
    """只提取可显示的 Trae 用户名和客户端已脱敏手机号。"""
    account = auth.get("account") if isinstance(auth, dict) else None
    masked_mobile = ""
    if isinstance(account, dict):
        # 只接受客户端已经脱敏的值（如 130******25）；绝不输出完整手机号。
        mobile = account.get("nonPlainTextMobile")
        if isinstance(mobile, str) and re.fullmatch(r"\d{3}\*{2,}\d{2,4}", mobile):
            masked_mobile = mobile
        for key in ("username", "nickname", "name", "displayName", "userName"):
            value = account.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), masked_mobile
    elif isinstance(account, (str, int)) and not isinstance(account, bool):
        value = str(account).strip()
        if value:
            return value, masked_mobile
    user_id = auth.get("userId") if isinstance(auth, dict) else None
    if isinstance(user_id, (str, int)) and not isinstance(user_id, bool):
        return str(user_id).strip(), masked_mobile
    return "", masked_mobile


def trae_headers(session):
    headers = {
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Authorization": "Cloud-IDE-JWT " + session["token"],
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Trae/1.0.0 Chrome/131.0.6778.204 "
                      "Electron/32.2.0 Safari/537.36",
        "x-rust-request-timeout": "30000",
    }
    if session.get("device_id"):
        headers["x-device-id"] = str(session["device_id"])
    if session.get("machine_id"):
        headers["x-machine-id"] = str(session["machine_id"])
    return headers


def trae_status(session):
    code, body = request_json(TRAE_STATUS_URL, trae_headers(session), payload={"req_source": 1})
    if code == 200 and isinstance(body, dict) and body.get("code", 0) == 0:
        return {"ok": True, "checked_in": bool(body.get("checked_in")),
                "enabled": bool(body.get("enable", True)),
                "credits": int(body.get("credits") or 0)}
    return {"ok": False, "http": code, "api_code": body.get("code") if isinstance(body, dict) else None,
            "message": api_message(body), "body": body}


def trae_claim(session):
    code, body = request_json(TRAE_CLAIM_URL, trae_headers(session), payload={"req_source": 1})
    if code == 200 and isinstance(body, dict) and body.get("code") == 0:
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        return {"ok": True, "credits": int(data.get("credits") or body.get("credits") or 0)}
    return {"ok": False, "http": code, "api_code": body.get("code") if isinstance(body, dict) else None,
            "message": api_message(body), "body": body}


def api_message(body):
    """仅展示服务端的简短业务说明，不输出原始响应或敏感字段。"""
    if not isinstance(body, dict):
        return ""
    for key in ("message", "msg", "error_message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


def checkin_trae(account, status_only=False):
    try:
        session = load_trae_session(account["auth_file"])
    except Exception as error:
        print("❌ Trae CN 登录态不可用：%s" % error)
        return 3, "登录态不可用"
    identity = "Trae CN 用户：%s" % (session.get("user_name") or "(未提供用户名称)")
    if session.get("masked_mobile"):
        identity += "  手机号：%s" % session["masked_mobile"]
    print(identity + "  token：已加载（内容已隐藏）")
    state = trae_status(session)
    if not state.get("ok"):
        detail = state.get("message") or "未返回业务说明"
        print("❌ 查询 Trae CN 签到状态失败：HTTP %s / code=%s / %s" %
              (state.get("http", -1), state.get("api_code"), detail))
        return 4, "查询状态失败"
    if state["checked_in"]:
        print("✅ Trae CN 今天已经签到过了，当前积分：%s" % state["credits"])
        return 0, "今天已签到"
    if not state["enabled"]:
        print("ℹ️  Trae CN 签到活动暂未开放，当前积分：%s" % state["credits"])
        return 0, "无进行中的活动"
    if status_only:
        print("ℹ️  Trae CN 今天尚未签到（仅查询模式，未领取），当前积分：%s" % state["credits"])
        return 0, "仅查询：尚未签到"
    result = trae_claim(session)
    if result.get("ok"):
        credits = result.get("credits") or state["credits"]
        print("✅ Trae CN 签到成功，当前积分：%s" % credits)
        return 0, "签到成功"
    detail = result.get("message") or "未返回业务说明"
    print("❌ Trae CN 签到失败：HTTP %s / code=%s / %s" %
          (result.get("http", -1), result.get("api_code"), detail))
    return 5, "签到失败"


def dpapi_unprotect(data):
    """使用当前 Windows 用户的 DPAPI 解封 Qoder 本机密钥。"""
    if sys.platform != "win32":
        raise RuntimeError("Qoder 登录态仅能在 Windows 上解密")
    import ctypes
    import ctypes.wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    input_blob, output_blob = DataBlob(len(data), buffer), DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise RuntimeError("Windows 无法解封 Qoder 登录态；请在其登录的 Windows 用户下运行")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def find_qoder_accounts():
    """发现当前 Windows 用户的 Qoder 登录态与独立 Qoder 配置目录。"""
    override = os.environ.get("QODER_AUTH_FILE")
    profile_root = None
    if override:
        candidates = [os.path.dirname(path.strip()) for path in override.split(";")
                      if path.strip()]
    else:
        home = os.path.expanduser("~")
        local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        roaming = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        candidates = [os.path.join(root, name) for root in (roaming, local)
                      for name in QODER_PRODUCT_DIRS]
        profile_root = os.environ.get(QODER_PROFILE_ROOT_ENV) or os.path.join(
            roaming, "AgentCheckin", "QoderProfiles")
        try:
            candidates.extend(entry.path for entry in os.scandir(profile_root) if entry.is_dir())
        except OSError:
            pass

    found, seen = [], set()
    for path in candidates:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if (os.path.isfile(os.path.join(path, QODER_AUTH_BASENAME)) and
                os.path.isfile(os.path.join(path, QODER_LOCAL_STATE_BASENAME))):
            profile_name = ""
            if (profile_root and os.path.dirname(normalized) ==
                    os.path.normcase(os.path.abspath(profile_root))):
                profile_name = os.path.basename(path)
            found.append({"platform": "Qoder CN", "windows_user": CURRENT_WINDOWS_USER,
                          "qoder_dir": path, "qoder_profile": profile_name})
    return found


def parse_qoder_time(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) / 1000 if value > 1e11 else float(value)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def load_qoder_session(qoder_dir):
    require_crypto()
    try:
        with open(os.path.join(qoder_dir, QODER_LOCAL_STATE_BASENAME), encoding="utf-8") as handle:
            encrypted_key = json.load(handle)["os_crypt"]["encrypted_key"]
        wrapped_key = base64.b64decode(encrypted_key)
    except Exception as error:
        raise ValueError("无法读取 Qoder Local State：%s" % error)
    if not wrapped_key.startswith(b"DPAPI"):
        raise ValueError("Qoder 密钥格式已变更")
    key = dpapi_unprotect(wrapped_key[5:])
    if len(key) != 32:
        raise ValueError("Qoder 本机密钥长度异常")
    try:
        with open(os.path.join(qoder_dir, QODER_AUTH_BASENAME), "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise ValueError("无法读取 Qoder 登录态：%s" % error)
    if not raw.startswith(b"v10") or len(raw) < 31:
        raise ValueError("Qoder 登录态格式已变更")
    nonce, content = raw[3:15], raw[15:]
    try:
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, content[-16:])).decryptor()
        auth = json.loads((decryptor.update(content[:-16]) + decryptor.finalize()).decode("utf-8"))
    except Exception as error:
        raise ValueError("Qoder 登录态无法解密：%s" % error)
    if not isinstance(auth.get("token"), str) or not auth["token"]:
        raise ValueError("Qoder 登录态缺少令牌")
    user = auth.get("user") if isinstance(auth.get("user"), dict) else {}
    user_name = (user.get("nickname") or user.get("name") or user.get("displayName") or
                 user.get("email") or user.get("id"))
    return {"token": auth["token"], "refresh_token": auth.get("refreshToken"),
            "expires_at": parse_qoder_time(auth.get("expiresAt")),
            "user_name": user_name if isinstance(user_name, str) else ""}


def qoder_headers(token):
    return {"Accept": "application/json", "User-Agent": "Qoder",
            "Authorization": "Bearer " + token, "Cosy-ClientType": "10"}


def qoder_campaigns(session):
    auth_error = None
    for base in QODER_API_BASES:
        code, body = request_json(base + QODER_CAMPAIGNS_PATH, qoder_headers(session["token"]), method="GET")
        if code == 200 and isinstance(body, dict):
            return {"ok": True, "base": base, "campaigns": body.get("campaigns") or []}
        if code == 404:
            return {"ok": True, "base": base, "campaigns": []}
        if code in (401, 403):
            auth_error = code
            continue
        return {"ok": False, "http": code, "body": body}
    return {"ok": False, "http": auth_error or -1}


def qoder_claimable(campaigns):
    items = []
    for campaign in campaigns:
        benefit = campaign.get("benefit") if isinstance(campaign, dict) else None
        amount = benefit.get("amount") if isinstance(benefit, dict) else None
        if (campaign.get("actionType") == "CLAIM_BENEFIT" and
                campaign.get("claimStatus") == "CLAIMABLE" and
                benefit.get("kind") == "CREDITS" and isinstance(amount, (int, float)) and
                not isinstance(amount, bool) and math.isfinite(amount)):
            items.append(campaign)
    return items


def checkin_qoder(account, status_only=False):
    try:
        session = load_qoder_session(account["qoder_dir"])
    except Exception as error:
        print("❌ Qoder CN 登录态不可用：%s" % error)
        return 3, "登录态不可用"
    print("Qoder CN 用户：%s  token：已加载（内容已隐藏）" %
          (session.get("user_name") or "(未提供用户名称)"))
    state = qoder_campaigns(session)
    if not state.get("ok"):
        print("❌ 查询 Qoder CN 活动失败：HTTP %s" % state.get("http", -1))
        return 4, "查询活动失败"
    campaigns = state["campaigns"]
    claimable = qoder_claimable(campaigns)
    if not campaigns:
        print("ℹ️  Qoder CN 当前无可领取活动。")
        return 0, "无进行中的活动"
    if not claimable:
        print("✅ Qoder CN 活动福利均已领取（共 %d 项活动）。" % len(campaigns))
        return 0, "活动均已领取"
    total = sum(item["benefit"]["amount"] for item in claimable)
    if status_only:
        print("ℹ️  Qoder CN 有 %d 项可领取福利（共 %s 积分；仅查询模式，未领取）。" %
              (len(claimable), total))
        return 0, "仅查询：有可领取福利"
    claimed, received = 0, 0
    for campaign in claimable:
        campaign_id = urllib.parse.quote(str(campaign.get("campaignId")), safe="")
        url = state["base"] + QODER_CAMPAIGNS_PATH + "/" + campaign_id + "/claim"
        code, _ = request_json(url, qoder_headers(session["token"]), method="POST")
        if not 200 <= code < 300:
            print("❌ Qoder CN 领取失败：HTTP %s（已领取 %d 项）。" % (code, claimed))
            return 5, "部分领取失败" if claimed else "领取失败"
        claimed += 1
        received += campaign["benefit"]["amount"]
    print("✅ Qoder CN 领取成功：%d 项，共 %s 积分。" % (claimed, received))
    return 0, "领取成功"


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


def find_checkin_targets():
    """汇总各平台的本机登录态，按平台和 Windows 用户分别显示。"""
    targets = []
    for account in find_windows_accounts():
        target = dict(account)
        target["platform"] = "WorkBuddy"
        targets.append(target)
    targets.extend(find_trae_accounts())
    targets.extend(find_qoder_accounts())
    targets.extend(find_doubao_accounts())
    targets.extend(find_minimax_accounts())
    return targets


def find_menu_targets():
    """构造主菜单：常规项目加上需切换 Windows 身份的受保护项目。"""
    targets = find_checkin_targets()
    for account in find_other_windows_bound_accounts():
        for platform in account["platforms"]:
            # 每个平台单独一行；后续若同一 Windows 用户选择多项，只认证一次。
            bound_account = dict(account)
            bound_account["platforms"] = (platform,)
            bound_account["bound_platforms"] = (BOUND_PLATFORM_KEYS[platform],)
            targets.append({
                "platform": platform,
                "windows_user": account["windows_user"],
                "requires_windows_password": True,
                "bound_account": bound_account,
            })
    return targets


def find_doubao_accounts():
    """发现当前 Windows 用户已安装且存有客户端数据的豆包工作。

    豆包客户端登录 Cookie 由 Windows DPAPI 保护，不能也不应跨 Windows 用户读取。
    这里只判断客户端数据目录是否存在，不读取、解密或输出登录态。
    """
    local_app_data = os.environ.get(
        "LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
    if not os.path.isdir(local_app_data):
        return []
    try:
        candidates = os.scandir(local_app_data)
        for entry in candidates:
            if not entry.is_dir() or "doubao" not in entry.name.lower():
                continue
            root = entry.path
            if (os.path.isfile(os.path.join(root, "Local State")) or
                    os.path.isfile(os.path.join(root, "User Data", "Local State"))):
                return [{"platform": "豆包工作", "windows_user": CURRENT_WINDOWS_USER}]
    except OSError:
        pass
    return []


def _has_minimax_client_data(profile_path):
    """判断 MiniMax Code OAuth 或旧会话文件是否存在，不读取其内容。"""
    return (os.path.isfile(os.path.join(profile_path, *MINIMAX_OAUTH_PARTS)) or
            os.path.isfile(os.path.join(profile_path, *MINIMAX_LEGACY_PARTS)))


def find_minimax_accounts():
    """发现当前 Windows 用户的 MiniMax Code 客户端登录态。"""
    profile_path = os.path.expanduser("~")
    if not _has_minimax_client_data(profile_path):
        return []
    return [{"platform": "MiniMax Code", "windows_user": CURRENT_WINDOWS_USER,
             "profile_path": profile_path}]


def minimax_user_identity(profile_path):
    """只读取 MiniMax 客户端公开配置中的昵称或用户标识，绝不读取 OAuth token。"""
    path = os.path.join(profile_path, *MINIMAX_CONFIG_PARTS)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, AttributeError):
        return ""
    # 新版客户端将账号资料放到 sharedUser；旧版可能仍使用 user。
    for user in (payload.get("sharedUser"), payload.get("user")):
        if not isinstance(user, dict):
            continue
        for key in ("userName", "subUserName", "realUserID", "userID"):
            value = user.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
                return str(value).strip()
    return ""


def minimax_masked_mobile(profile_path):
    """从 MiniMax 自己的账号资料中读取手机号，并始终返回脱敏形式。

    不能从其他客户端的账号资料补全手机号：同一 Windows 用户在不同平台可能
    登录不同账号。当前 MiniMax 版本通常并不保存手机号；保留兼容读取是为了在
    客户端明确提供该字段时安全显示它。
    """
    path = os.path.join(profile_path, *MINIMAX_CONFIG_PARTS)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, AttributeError):
        return ""

    # 仅接受明确的手机号字段，不扫描日志、令牌或任意文本。
    for user in (payload.get("sharedUser"), payload.get("user")):
        if not isinstance(user, dict):
            continue
        for key in ("nonPlainTextMobile", "maskedMobile", "maskedPhone",
                    "mobile", "phone", "phoneNumber"):
            value = user.get(key)
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                continue
            value = str(value).strip()
            if re.fullmatch(r"\d{3}\*{2,}\d{2,4}", value):
                return value
            # 即使新版客户端意外保存完整号码，控制台也绝不输出完整号码。
            if re.fullmatch(r"1[3-9]\d{9}", value):
                return "%s******%s" % (value[:3], value[-2:])
    return ""


def _has_qoder_client_data(profile_path):
    """只判断其他 Windows 配置文件是否存在 Qoder 数据，不读取登录态。"""
    for base in ("Roaming", "Local"):
        root = os.path.join(profile_path, "AppData", base)
        for product in QODER_PRODUCT_DIRS:
            candidate = os.path.join(root, product)
            if (os.path.isfile(os.path.join(candidate, QODER_AUTH_BASENAME)) and
                    os.path.isfile(os.path.join(candidate, QODER_LOCAL_STATE_BASENAME))):
                return True
    return False


def _has_doubao_client_data(profile_path):
    """只判断其他 Windows 配置文件是否存在豆包客户端数据，不读取登录态。"""
    local_app_data = os.path.join(profile_path, "AppData", "Local")
    try:
        entries = os.scandir(local_app_data)
        for entry in entries:
            if not entry.is_dir() or "doubao" not in entry.name.lower():
                continue
            if (os.path.isfile(os.path.join(entry.path, "Local State")) or
                    os.path.isfile(os.path.join(entry.path, "User Data", "Local State"))):
                return True
    except OSError:
        pass
    return False


def find_other_windows_bound_accounts(users_dir=None):
    """发现其他 Windows 用户的 Qoder/豆包数据，但绝不在当前用户下解密。"""
    if users_dir is None:
        users_dir = os.path.dirname(os.path.expanduser("~"))
    current_profile = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
    found = []
    try:
        profiles = os.scandir(users_dir)
    except OSError:
        return found
    with profiles:
        for profile in profiles:
            if not profile.is_dir():
                continue
            profile_path = os.path.normcase(os.path.abspath(profile.path))
            if profile_path == current_profile:
                continue
            platforms = []
            if _has_qoder_client_data(profile.path):
                platforms.append("Qoder CN")
            if _has_doubao_client_data(profile.path):
                platforms.append("豆包工作")
            if _has_minimax_client_data(profile.path):
                platforms.append("MiniMax Code")
            if platforms:
                found.append({"windows_user": profile.name, "profile_path": profile.path,
                              "platforms": tuple(platforms)})
    return sorted(found, key=lambda item: item["windows_user"].lower())


def resolve_windows_logon_name(profile_path, fallback_user):
    """将 C:\\Users 配置目录映射为 Windows 认证用户名；失败时仅回退本地用户名。"""
    if os.name != "nt":
        return ".\\%s" % fallback_user
    command = (
        "$target=$env:AGENTCHECKIN_PROFILE_PATH;"
        "$profile=Get-CimInstance Win32_UserProfile | Where-Object "
        "{ $_.LocalPath -eq $target } | Select-Object -First 1;"
        "if ($profile) {"
        "(New-Object System.Security.Principal.SecurityIdentifier($profile.SID))."
        "Translate([System.Security.Principal.NTAccount]).Value"
        "}"
    )
    environment = os.environ.copy()
    environment["AGENTCHECKIN_PROFILE_PATH"] = os.path.abspath(profile_path)
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, env=environment,
        )
        resolved = completed.stdout.strip()
        if completed.returncode == 0 and resolved and "\n" not in resolved:
            return resolved
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ".\\%s" % fallback_user


def choose_other_windows_bound_accounts(accounts):
    """选择需要切换 Windows 身份的 Qoder/豆包账号；回车表示跳过。"""
    if not accounts:
        return []
    print("\n其他 Windows 用户的受保护客户端登录态：")
    for index, account in enumerate(accounts, start=1):
        print("  %d. Windows 账号：%s（%s）" % (
            index, account["windows_user"], "、".join(account["platforms"])))
    print("  A. 全部启动")
    while True:
        try:
            choice = input("请选择要以其他 Windows 身份运行的账号（如 1、1,3 或 A；直接回车跳过）：").strip()
        except KeyboardInterrupt:
            print("\n已跳过其他 Windows 用户。")
            return []
        except EOFError:
            return []
        if not choice:
            return []
        if choice.lower() in ("a", "all", "0"):
            return accounts
        try:
            indexes = [int(item.strip()) for item in choice.split(",")]
            if not indexes or any(index < 1 or index > len(accounts) for index in indexes):
                raise ValueError
        except ValueError:
            print("输入无效，请输入账号编号、逗号分隔的编号，或 A。")
            continue
        selected = []
        for index in indexes:
            account = accounts[index - 1]
            if account not in selected:
                selected.append(account)
        return selected


def launch_bound_checkin_as_windows_user(account):
    """让 Windows 自行收集密码并以目标用户运行仅限 Qoder/豆包的子任务。"""
    if not os.path.isfile(BOUND_CHECKIN_BATCH):
        print("❌ 找不到跨 Windows 用户启动器。")
        return False
    logon_name = resolve_windows_logon_name(account["profile_path"], account["windows_user"])
    platform_keys = tuple(account.get("bound_platforms") or
                          (BOUND_PLATFORM_KEYS[name] for name in account["platforms"]))
    if not platform_keys or any(key not in ("qoder", "doubao", "minimax") for key in platform_keys):
        print("❌ 跨 Windows 用户的平台配置无效。")
        return False
    # 密码由 runas 直接在 Windows 控制台读取；绝不作为 Python 参数、变量或日志内容。
    # 显式传入当前可用的 Python，避免目标 Windows 用户的 PATH 未配置 Python。
    command = 'cmd.exe /d /k ""%s" "%s" "%s""' % (
        BOUND_CHECKIN_BATCH, sys.executable, ",".join(platform_keys))
    print("\n🔐 Windows 将提示输入 %s 的登录密码（输入不会显示或保存）。" % logon_name)
    print("   新窗口只会运行：%s" % "、".join(account["platforms"]))
    try:
        completed = subprocess.run(["runas", "/profile", "/user:" + logon_name, command])
    except OSError as error:
        print("❌ 无法启动 Windows 身份切换：%s" % error)
        return False
    if completed.returncode != 0:
        print("❌ Windows 未启动该用户的签到窗口（密码错误或取消输入）。")
        return False
    print("ℹ️  已交给 Windows 启动 %s 的签到窗口，请在该窗口查看结果。" % account["windows_user"])
    return True


def _doubao_result_from_output(output):
    """提取上游模块的最终 JSON 结果，过程日志绝不回显。"""
    for line in reversed((output or "").splitlines()):
        try:
            result = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(result, dict) and isinstance(result.get("result"), str):
            return result
    return None


def doubao_identity_from_trae(windows_user, user_name):
    """仅在豆包与 Trae 显示的账号标识完全一致时复用已脱敏手机号。"""
    if not isinstance(user_name, str) or not user_name:
        return ""
    for account in find_trae_accounts():
        if account.get("windows_user") != windows_user:
            continue
        try:
            session = load_trae_session(account["auth_file"])
        except (OSError, ValueError, RuntimeError):
            continue
        if (session.get("user_name") == user_name and
                re.fullmatch(r"\d{3}\*{2,}\d{2,4}", session.get("masked_mobile", ""))):
            return session["masked_mobile"]
    return ""


def checkin_doubao(account, status_only=False):
    """调用独立的豆包工作模块，并只显示无凭据的最终状态。"""
    print("Windows 账号：%s" % (account.get("windows_user") or "未填写"))
    if status_only:
        print("ℹ️  已发现豆包工作客户端（仅查询模式不读取登录态，也不会签到）。")
        return 0, "仅查询：已发现客户端"
    if not os.path.isfile(DOUBAO_SCRIPT):
        print("❌ 找不到豆包工作签到模块。")
        return 3, "签到模块缺失"
    try:
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", DOUBAO_SCRIPT, "run"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=720,
        )
    except subprocess.TimeoutExpired:
        print("❌ 豆包工作签到超时。")
        return 4, "签到超时"
    except OSError as error:
        print("❌ 无法启动豆包工作签到：%s" % error)
        return 4, "无法启动签到模块"

    result = _doubao_result_from_output(completed.stdout)
    if result:
        state = result.get("result")
        report = result.get("report")
        if not isinstance(report, str) or not report.strip():
            report = "未提供结果说明"
        user_name = result.get("user_name")
        if not isinstance(user_name, str) or not user_name.strip():
            user_name = "(未提供用户名称)"
        else:
            user_name = user_name.strip()
        masked_mobile = result.get("masked_mobile")
        if not isinstance(masked_mobile, str) or not re.fullmatch(r"\d{3}\*{2,}\d{2,4}", masked_mobile):
            masked_mobile = doubao_identity_from_trae(account.get("windows_user"), user_name)
        identity = "豆包工作用户：%s" % user_name
        if masked_mobile:
            identity += "  手机号：%s" % masked_mobile
        else:
            identity += "  手机号：(未提供)"
        print(identity)
        # 上游结果可能带本机截图路径和诊断细节；统一入口仅显示安全的报告文字。
        if state in ("success", "already"):
            print("✅ 豆包工作：%s" % report.strip())
            return 0, "签到成功" if state == "success" else "今天已签到"
        print("❌ 豆包工作签到未完成：%s" % report.strip())
        return 5, "签到未完成"

    if completed.returncode != 0:
        print("❌ 豆包工作签到模块异常退出（未获得可识别结果）。")
        return 5, "签到模块异常"
    print("❌ 豆包工作签到结果无法识别。")
    return 5, "结果无法识别"


def checkin_minimax(account, status_only=False):
    """使用 MiniMax Code 本机 OAuth 登录态执行签到；仅查询模式不刷新或写回凭据。"""
    print("Windows 账号：%s" % (account.get("windows_user") or "未填写"))
    profile_path = account.get("profile_path") or os.path.expanduser("~")
    user_name = minimax_user_identity(profile_path)
    masked_mobile = minimax_masked_mobile(profile_path)
    identity = "MiniMax Code 用户：%s" % (user_name or "(未提供用户名称)")
    identity += "  手机号：%s" % (masked_mobile or "(未提供)")
    if status_only:
        print(identity)
        print("ℹ️  已发现 MiniMax Code 登录态（仅查询模式不刷新登录态，也不会签到）。")
        return 0, "仅查询：已发现客户端登录态"
    try:
        from minimax_checkin import MiniMaxCheckin
        result = MiniMaxCheckin().run()
    except Exception as error:  # noqa: BLE001
        print("❌ MiniMax Code 签到模块异常：%s" % error)
        return 4, "签到模块异常"

    print(identity)
    status = result.get("status") if isinstance(result, dict) else "failed"
    message = result.get("message", "未提供结果说明") if isinstance(result, dict) else "结果格式异常"
    if status in ("success", "already"):
        print("✅ MiniMax Code：%s" % message)
        try:
            balance = MiniMaxCheckin().balance()
            remaining = to_decimal(balance.get("remain"))
            if balance.get("available") and remaining is not None:
                print("当前剩余积分：%s%s" % (
                    format_credits(remaining), balance.get("note", "")))
        except Exception:
            pass
        return 0, "签到成功" if status == "success" else "今天已签到"
    print("❌ MiniMax Code 签到未完成：%s" % message)
    return 5, "签到未完成"


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


def choose_targets(targets):
    """让用户按编号选择一个、多个或全部平台账号。"""
    if not targets:
        print("❌ 没有发现已登录的 WorkBuddy、Trae CN、Qoder CN 或豆包工作。")
        return None

    print("\n可签到项目：")
    for index, target in enumerate(targets, start=1):
        details = []
        if target.get("qoder_profile"):
            details.append("Qoder 配置：%s" % target["qoder_profile"])
        if target.get("requires_windows_password"):
            details.append("需 Windows 密码")
        suffix = "（%s）" % "；".join(details) if details else ""
        print("  %d. [%s] Windows 账号：%s" % (
            index, target.get("platform", "未知平台"),
            (target.get("windows_user") or "未填写") + suffix))
    print("  A. 全部账号")

    while True:
        try:
            choice = input("\n请选择（如 1、1,3 或 A；直接回车全部，Ctrl+C 退出）：").strip()
        except KeyboardInterrupt:
            print("\n已退出。")
            raise SystemExit(130)
        except EOFError:
            print("\n输入已结束，已退出。")
            return None

        if not choice:
            print("已选择全部账号。")
            return targets
        if choice.lower() in ("a", "all", "0"):
            return targets

        try:
            indexes = [int(item.strip()) for item in choice.split(",")]
            if not indexes or any(index < 1 or index > len(targets) for index in indexes):
                raise ValueError
        except ValueError:
            print("输入无效，请输入账号编号、逗号分隔的编号，或 A。")
            continue

        # 保留用户输入的顺序，同时去除重复编号。
        selected = []
        for index in indexes:
            target = targets[index - 1]
            if target not in selected:
                selected.append(target)
        return selected


def checkin_target(target, status_only=False):
    """按平台调度；status_only 永远不发送领取请求。"""
    platform = target.get("platform")
    if platform == "WorkBuddy":
        if status_only:
            return checkin_workbuddy_status(target)
        return checkin(target)
    if platform == "Trae CN":
        return checkin_trae(target, status_only=status_only)
    if platform == "Qoder CN":
        return checkin_qoder(target, status_only=status_only)
    if platform == "豆包工作":
        return checkin_doubao(target, status_only=status_only)
    if platform == "MiniMax Code":
        return checkin_minimax(target, status_only=status_only)
    print("❌ 不支持的平台：%s" % platform)
    return 3, "平台配置错误"


def checkin_workbuddy_status(account):
    """WorkBuddy 只查询状态，不领取积分。"""
    auth, err = load_auth(account.get("auth_file"))
    if err:
        print("❌ %s" % err)
        return 3, "登录态不可用"
    print("Windows 账号：%s" % (account.get("windows_user") or "未填写"))
    print("WorkBuddy 用户：%s  token：%s" % (
        auth["nickname"] or auth["uid"][:8], mask_token(auth["token"])))
    status, response = api_post(STATUS_URL, auth["token"], auth["uid"])
    if status != 200 or response.get("code") != 0:
        print("❌ 查询签到状态失败：HTTP %d / %s" %
              (status, response.get("msg", response)))
        return 4, "查询状态失败"
    data = response.get("data", {})
    if not data.get("active", False):
        print("ℹ️  当前没有进行中的签到活动。")
        return 0, "无进行中的活动"
    if data.get("today_checked_in", False):
        print("✅ 今天已经签到过了，获得 %s 积分。" % data.get("today_credit", 0))
        return 0, "今天已签到"
    print("ℹ️  今天尚未签到（仅查询模式，未领取）。")
    return 0, "仅查询：尚未签到"


def main():
    allowed_options = ("--status", "--bound-only")
    bound_platform_options = [option for option in sys.argv[1:]
                              if option.startswith("--bound-platforms=")]
    unknown_options = [option for option in sys.argv[1:]
                       if option not in allowed_options and not option.startswith("--bound-platforms=")]
    if unknown_options:
        print("用法：python DailyCheckin.py [--status] [--bound-only] [--bound-platforms=qoder,doubao,minimax]")
        return 2
    if len(bound_platform_options) > 1:
        print("❌ --bound-platforms 只能提供一次。")
        return 2
    bound_platforms = None
    if bound_platform_options:
        bound_platforms = {item.strip().lower() for item in
                           bound_platform_options[0].split("=", 1)[1].split(",") if item.strip()}
        if not bound_platforms or not bound_platforms <= {"qoder", "doubao", "minimax"}:
            print("❌ --bound-platforms 仅支持 qoder,doubao,minimax。")
            return 2
    status_only = "--status" in sys.argv[1:]
    bound_only = "--bound-only" in sys.argv[1:]
    print("AgentCheckin 每日签到  %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    if status_only:
        print("仅查询模式：不会发起任何领取请求。")
    password_targets = []
    if bound_only:
        print("跨 Windows 用户模式：仅处理当前 Windows 用户的 Qoder CN、豆包工作与 MiniMax Code。")
        targets = []
        if bound_platforms is None or "qoder" in bound_platforms:
            targets.extend(find_qoder_accounts())
        if bound_platforms is None or "doubao" in bound_platforms:
            targets.extend(find_doubao_accounts())
        if bound_platforms is None or "minimax" in bound_platforms:
            targets.extend(find_minimax_accounts())
    else:
        targets = choose_targets(find_menu_targets())
    if targets is None:
        return 0
    if not targets:
        if bound_only:
            print("❌ 当前 Windows 用户没有发现已登录的 Qoder CN、豆包工作或 MiniMax Code。")
        else:
            print("❌ 没有发现可签到的项目。")
        return 1

    direct_targets = [target for target in targets if not target.get("requires_windows_password")]
    password_targets = [target for target in targets if target.get("requires_windows_password")]
    results = []
    for index, target in enumerate(direct_targets, start=1):
        windows_user = target.get("windows_user") or "未填写"
        platform = target.get("platform", "未知平台")
        print("\n%s" % ("=" * 18))
        print("[%d/%d] [%s] Windows 账号：%s" % (index, len(direct_targets), platform, windows_user))
        code, message = checkin_target(target, status_only=status_only)
        results.append((platform, windows_user, code, message))

    all_succeeded = all(code == 0 for _, _, code, _ in results)
    if status_only:
        for target in password_targets:
            results.append((target.get("platform", "受保护客户端"),
                            target.get("windows_user") or "未填写", 0,
                            "仅查询模式：未切换 Windows 用户"))
    else:
        # 同一 Windows 用户的多个已选平台只认证一次，并且只传给子任务已选的平台。
        grouped = {}
        for target in password_targets:
            account = target["bound_account"]
            key = os.path.normcase(os.path.abspath(account["profile_path"]))
            group = grouped.setdefault(key, {"account": dict(account), "targets": []})
            group["targets"].append(target)
        for group in grouped.values():
            account, selected_targets = group["account"], group["targets"]
            account["platforms"] = tuple(target["platform"] for target in selected_targets)
            account["bound_platforms"] = tuple(
                BOUND_PLATFORM_KEYS[target["platform"]] for target in selected_targets)
            started = launch_bound_checkin_as_windows_user(account)
            for target in selected_targets:
                results.append((target["platform"], target["windows_user"],
                                0 if started else 1,
                                "已启动 Windows 签到窗口" if started else "未启动 Windows 签到窗口"))
            if not started:
                all_succeeded = False

    print("\n签到结果汇总：")
    for platform, windows_user, code, message in results:
        icon = "✅" if code == 0 else "❌"
        print("%s [%s] Windows 账号 %s：%s" % (icon, platform, windows_user, message))
    return 0 if all_succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
