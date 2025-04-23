import re
import base64
import random
import requests
import urllib.parse
import warnings
import pandas as pd
from html import unescape as html_unescape
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor

# 禁用 SSL 警告
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)

# 桌面端 & 移动端 UA 列表
DESKTOP_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'
]

MOBILE_USER_AGENTS = [
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (iPad; CPU OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1'
]

def create_session():
    """创建带重试机制的会话"""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=['GET']
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def get_headers(device_type):
    """生成指定设备类型的请求头"""
    ua = random.choice(DESKTOP_USER_AGENTS if device_type == 'desktop' else MOBILE_USER_AGENTS)
    return {
        'User-Agent': ua,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Connection': 'keep-alive',
        'DNT': '1',
        'Referer': 'https://www.google.com/'
    }

def decode_url(text):
    """URL解码"""
    try:
        return urllib.parse.unquote(text)
    except Exception:
        return text

def decode_html(text):
    """HTML实体解码"""
    return html_unescape(text)

def decode_hex(text):
    r"""十六进制解码（处理 \xXX 格式）"""
    def replace_hex(match):
        try:
            return bytes.fromhex(match.group(1)).decode('utf-8', errors='ignore')
        except Exception:
            return match.group(0)
    return re.sub(r'\\x([0-9a-fA-F]{2})', replace_hex, text)

def decode_base64(text):
    """Base64解码（自动填充处理）"""
    def base64_replacer(match):
        base64_str = match.group(0)
        try:
            missing_padding = 4 - len(base64_str) % 4
            if missing_padding and missing_padding != 4:
                base64_str += "=" * missing_padding
            return base64.b64decode(base64_str).decode('utf-8', errors='ignore')
        except Exception:
            return base64_str
    return re.sub(r'[A-Za-z0-9+/]{4,}(?:={0,2})', base64_replacer, text)

def deep_decode(text, max_depth=3):
    """
    多层嵌套解码
    按照 URL 解码、HTML实体解码、十六进制解码、Base64 解码依次执行，直至稳定或达到最大深度
    """
    decoded = text
    prev = None
    depth = 0
    while decoded != prev and depth < max_depth:
        prev = decoded
        decoded = decode_url(decoded)
        decoded = decode_html(decoded)
        decoded = decode_hex(decoded)
        decoded = decode_base64(decoded)
        depth += 1
    return decoded

def extract_combined_text(html_content):
    """
    同时提取页面中除去HTML标签的纯文本和所有script标签中的内容，
    这样可以捕获暗链可能隐藏在js代码中的关键词。
    """
    # 提取非script/style标签的纯文本
    text = re.sub(r'<(script|style).*?>.*?</\1>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    # 提取所有script标签的内容
    scripts = re.findall(r'<script.*?>(.*?)</script>', html_content, flags=re.DOTALL | re.IGNORECASE)
    script_text = " ".join(scripts)
    combined = text + " " + script_text
    return combined

def check_url(url):
    session = create_session()
    ua_types = set()  # 记录成功访问的 UA 设备类型
    matched_rules_set = set()
    error_message = None

    for device_type in ['desktop', 'mobile']:
        try:
            headers = get_headers(device_type)
            resp = session.get(url, headers=headers, timeout=(7, 15), verify=False, allow_redirects=True)
            if resp.status_code != 200:
                error_message = f"状态码 {resp.status_code}"
                continue

            ua_types.add(device_type)  # 记录成功访问的设备
            print(f"[✓] 成功访问（{device_type.upper()}）：{url}")  # 实时打印成功的 URL

            # 进行多层解码
            decoded_content = deep_decode(resp.text)
            # 提取页面中所有文本（包括script标签内容）
            combined_text = extract_combined_text(decoded_content)
            # 直接匹配关键词（去除 \b 限定以适应中文关键词）
            matched_rules = {rule for rule in rules if re.search(re.escape(rule), combined_text, re.I)}
            if matched_rules:
                matched_rules_set.update(matched_rules)
        except Exception as e:
            error_message = str(e)
            continue

    # 确定 UA 访问情况
    if "desktop" in ua_types and "mobile" in ua_types:
        ua_status = "桌面端和移动端"
    elif "desktop" in ua_types:
        ua_status = "桌面"
    elif "mobile" in ua_types:
        ua_status = "移动"
    else:
        ua_status = "桌面端和移动端"

    return {
        "URL": url,
        "状态": "成功" if ua_types else "失败",
        "UA头": ua_status,
        "是否存在暗链": "是" if matched_rules_set else "否",
        "匹配规则": ", ".join(matched_rules_set) if matched_rules_set else None,
        "错误信息": error_message if not ua_types else None
    }

def check_dark_links():
    global rules
    try:
        with open('rules.txt', 'r', encoding='utf-8') as f:
            rules = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("[x] 规则文件 rules.txt 不存在")
        return
    
    try:
        with open('urls.txt', 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("[x] URL 文件 urls.txt 不存在")
        return

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(check_url, urls))
    
    successful = [res for res in results if res["状态"] == "成功"]
    failed = [res for res in results if res["状态"] == "失败"]

    print("=" * 60)
    print(f"检测完成，共处理 {len(urls)} 个 URL")
    print(f"成功访问：{len(successful)} 个")
    print(f"访问失败：{len(failed)} 个")

    # 将结果导出到 Excel
    df = pd.DataFrame(results)
    df.to_excel("result.xlsx", index=False)

    print("[✔] 结果已导出到 result.xlsx")

if __name__ == '__main__':
    print("=" * 60)
    print("暗链排查系统启动".center(60))
    check_dark_links()
