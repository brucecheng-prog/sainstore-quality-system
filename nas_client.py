"""
NAS 文件存储客户端
通过 Synology DSM FileStation API 操作 NAS 上的文件
"""

import os
import json
import re
import zipfile
import socket
import urllib.request
import urllib.parse
import http.cookiejar
import io
import unicodedata
from datetime import datetime

# 不在模块级别设置全局超时，避免影响其他 socket 操作
# 各函数通过 opener.open(req, timeout=N) 单独控制
# socket.setdefaulttimeout(3)  # ❌ 已移除 — 会导致 Windows 服务器上所有 socket 操作受限


def _filename_readability_score(name):
    if not name:
        return -999

    score = 0
    for ch in name:
        code = ord(ch)
        if ch == "\ufffd":
            score -= 10
        elif 0x2500 <= code <= 0x257F:
            score -= 6
        elif unicodedata.category(ch).startswith("C") and ch not in ("\t", "\n", "\r"):
            score -= 4
        elif "\u4e00" <= ch <= "\u9fff":
            score += 3
        elif ch.isalnum():
            score += 1
        elif ch in " ._()-[]{}&+,，（）【】":
            score += 1
    return score


def repair_filename_mojibake(name):
    """尽量修复 Windows/WPS ZIP 内中文文件名乱码。"""
    if not name:
        return name

    name = str(name).replace("\\", "/").strip()
    candidates = {name}

    for source_encoding in ("cp437", "latin1"):
        try:
            raw_bytes = name.encode(source_encoding)
        except Exception:
            continue

        for target_encoding in ("utf-8", "gbk", "gb18030", "big5"):
            try:
                repaired = raw_bytes.decode(target_encoding).strip()
                if repaired:
                    candidates.add(repaired.replace("\\", "/").strip())
            except Exception:
                continue

    return max(candidates, key=_filename_readability_score)


def _env_or_default(name, default):
    value = os.environ.get(name, "").strip()
    return value or default


# ── 配置 ─────────────────────────────────────────────
NAS_URL = os.environ.get("NAS_URL", "").strip()
NAS_ACCOUNT = os.environ.get("NAS_ACCOUNT", "").strip()
NAS_PASSWORD = os.environ.get("NAS_PASSWORD", "").strip()
NAS_BASE_PATH = _env_or_default("NAS_BASE_PATH", "/QA/验货相关文件")

# 暂存区路径：报告提交后先暂存于此，审核通过后再迁移到正式路径
STAGING_PATH = _env_or_default("NAS_STAGING_PATH", "/QA/待审批暂存区")

# ── 全局 NAS 路径路由映射 ──
# 报告(PDF) 和 图片(ZIP) 分别存放在不同目录
# {year} 会被动态替换为检验日期年份
NAS_ROUTING_MAP = {
    "驻厂验货": {
        "report":  "/QA/验货相关文件/驻厂验货报告/{year}年度/",
        "picture": "/QA/验货相关文件/验货图片/{year}年/",
    },
    "来料检验": {
        "report":  "/QA/验货相关文件/来料检验/{year}年度/",
        "picture": "/QA/验货相关文件/验货图片/{year}年/",
    },
    "出货检验": {
        "report":  "/QA/验货相关文件/出货检验/{year}年度/",
        "picture": "/QA/验货相关文件/验货图片/{year}年/",
    },
    "过程检验": {
        "report":  "/QA/验货相关文件/来料检验/{year}年度/",
        "picture": "/QA/验货相关文件/验货图片/{year}年/",
    },
    "可靠性测试": {
        "report":  "/QA/验货相关文件/来料检验/{year}年度/",
        "picture": "/QA/验货相关文件/验货图片/{year}年/",
    },
    "其他": {
        "report":  "/QA/验货相关文件/其他报告/{year}年/",
        "picture": "/QA/验货相关文件/其他图片/{year}年/",
    },
    # 兜底默认路径
    "default": {
        "report":  "/QA/验货相关文件/其他报告/{year}年/",
        "picture": "/QA/验货相关文件/其他图片/{year}年/",
    },
}

def get_nas_routes(report_type, year):
    """
    根据报告类型和年份，从路由映射中获取 NAS 报告目录和图片目录

    参数:
        report_type: 报告类型（来料检验、驻厂验货 等）
        year:        年份字符串，如 '2026'

    返回:
        (report_folder, picture_folder) 两个 NAS 绝对路径
    """
    route = NAS_ROUTING_MAP.get(report_type, NAS_ROUTING_MAP['default'])
    report_folder  = route['report'].format(year=year)
    picture_folder = route['picture'].format(year=year)
    return report_folder, picture_folder


# ── 会话管理 ─────────────────────────────────────────
_cookie_jar = http.cookiejar.CookieJar()
_session_sid = None


def _get_opener():
    """获取带 cookie 的 opener"""
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))


def _ensure_login():
    """确保已登录，返回有效的 SID"""
    global _session_sid
    if _session_sid:
        return _session_sid
    if not (NAS_URL and NAS_ACCOUNT and NAS_PASSWORD):
        raise RuntimeError("NAS 运行凭据未配置")

    opener = _get_opener()
    login_params = urllib.parse.urlencode({
        'api': 'SYNO.API.Auth',
        'version': '7',
        'method': 'login',
        'account': NAS_ACCOUNT,
        'passwd': NAS_PASSWORD,
        'session': 'FileStation',
        'format': 'cookie',
    }).encode()
    req = urllib.request.Request(f'{NAS_URL}/webapi/auth.cgi', data=login_params)
    resp = opener.open(req, timeout=5)
    result = json.loads(resp.read())
    if not result.get('success'):
        raise RuntimeError(f"NAS 登录失败: {result.get('error', {}).get('code')}")
    _session_sid = result['data']['sid']
    return _session_sid


def _api_call(method, api='SYNO.FileStation.List', version='2', **params):
    """调用 DSM API"""
    sid = _ensure_login()
    params.setdefault('_sid', sid)
    query = urllib.parse.urlencode({'api': api, 'version': version, 'method': method, **params})
    url = f'{NAS_URL}/webapi/entry.cgi?{query}'
    opener = _get_opener()
    req = urllib.request.Request(url)
    resp = opener.open(req, timeout=5)
    return json.loads(resp.read())


# ── 核心操作 ─────────────────────────────────────────

def list_files(folder_path):
    """列出目录内容"""
    r = _api_call('list', folder_path=folder_path)
    if not r.get('success'):
        return []
    return r['data']['files']


def create_folder(parent_path, folder_name):
    """创建子目录"""
    r = _api_call(
        'create',
        api='SYNO.FileStation.CreateFolder',
        version='2',
        folder_path=parent_path,
        name=folder_name,
        force_parent='true',
    )
    return r.get('success', False)


def delete_file(file_path):
    """删除文件（也支持目录）"""
    r = _api_call(
        'start',
        api='SYNO.FileStation.Delete',
        version='2',
        path=json.dumps([file_path]),
        accurate='true',
    )
    return r.get('success', False)


def upload_file(remote_folder, filename, file_content):
    """
    上传文件到 NAS

    参数:
        remote_folder: NAS 上的目标文件夹路径，如 /QA/验货相关文件/驻厂验货报告/2026年度
        filename:      文件名，如 test_report.pdf
        file_content:  文件内容 bytes

    返回:
        (success, nas_full_path) 例如: (True, '/QA/验货相关文件/驻厂验货报告/2026年度/test_report.pdf')
    """
    sid = _ensure_login()

    # 构造 multipart/form-data
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    body = io.BytesIO()

    def add_field(name, value):
        body.write(f'--{boundary}\r\n'.encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(f'{value}\r\n'.encode())

    add_field('_sid', sid)
    add_field('path', remote_folder)
    add_field('create_parents', 'true')
    add_field('overwrite', 'true')

    # 文件部分
    body.write(f'--{boundary}\r\n'.encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body.write(b'Content-Type: application/octet-stream\r\n\r\n')
    body.write(file_content)
    body.write(f'\r\n--{boundary}--\r\n'.encode())

    data = body.getvalue()

    # 调用 Upload API v2
    query = urllib.parse.urlencode({
        'api': 'SYNO.FileStation.Upload',
        'version': '2',
        'method': 'upload',
    })
    url = f'{NAS_URL}/webapi/entry.cgi?{query}'
    opener = _get_opener()
    req = urllib.request.Request(url, data=data)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

    resp = opener.open(req, timeout=60)
    result = json.loads(resp.read())

    if result.get('success'):
        nas_path = f"{remote_folder.rstrip('/')}/{filename}"
        return True, nas_path
    else:
        error_code = result.get('error', {}).get('code', 'unknown')
        return False, f"error_{error_code}"


# ── 暂存区操作 ──────────────────────────────────────

def download_file(nas_path):
    """
    从 NAS 下载文件到内存。

    参数:
        nas_path: NAS 上的完整文件路径，如 /QA/待审批暂存区/xxx.pdf

    返回:
        (bytes, filename) 成功时；失败时返回 (None, error_msg)
    """
    sid = _ensure_login()
    folder = os.path.dirname(nas_path)
    name = os.path.basename(nas_path)

    try:
        # 先获取文件信息拿到真实名称
        r = _api_call('list', folder_path=folder)
        if not r.get('success'):
            return None, f"列出目录失败: {nas_path}"

        files = r['data'].get('files', [])
        target = None
        for f in files:
            if f['name'] == name:
                target = f
                break
        if not target:
            return None, f"文件不存在: {nas_path}"

        # 通过 HTTP GET 下载
        query = urllib.parse.urlencode({
            'api': 'SYNO.FileStation.Download',
            'version': '2',
            'method': 'download',
            'path': nas_path,
            'mode': 'download',
            '_sid': sid,
        })
        url = f'{NAS_URL}/webapi/entry.cgi?{query}'
        opener = _get_opener()
        req = urllib.request.Request(url)
        resp = opener.open(req, timeout=60)

        # 检查 Content-Type 判断是否返回了错误 JSON
        content_type = resp.headers.get('Content-Type', '')
        data = resp.read()
        if 'application/json' in content_type:
            err = json.loads(data)
            return None, f"NAS 返回错误: {err.get('error', {}).get('code', 'unknown')}"

        return data, name

    except Exception as e:
        return None, str(e)[:200]


def ensure_staging_folder():
    """
    确保暂存区目录存在，不存在则自动创建。

    返回:
        True 表示目录可用，False 表示创建失败
    """
    parent = os.path.dirname(STAGING_PATH)  # /QA
    folder_name = os.path.basename(STAGING_PATH)  # 待审批暂存区

    # 检查是否已存在
    try:
        existing = list_files(parent)
        for f in existing:
            if f.get('name') == folder_name and f.get('isdir'):
                return True
    except Exception:
        pass

    return create_folder(parent, folder_name)


def upload_to_staging(file_bytes, report_brand, report_sku, inspection_date):
    """
    将报告上传到 NAS 暂存区，文件名加时间戳防重名。

    参数:
        file_bytes:       PDF 文件内容 bytes
        report_brand:     品牌
        report_sku:       SKU
        inspection_date:  检验日期字符串 (YYYY-MM-DD)

    返回:
        (success_bool, nas_full_path)
    """
    # 确保暂存区存在
    if not ensure_staging_folder():
        return False, None

    # 构建防重名文件名
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    date_clean = inspection_date.replace('-', '') if inspection_date else ''
    name_segments = [report_brand, report_sku, date_clean, ts]
    staging_filename = "_".join([s for s in name_segments if s]) + ".pdf"

    return upload_file(STAGING_PATH, staging_filename, file_bytes)


def ensure_single_folder(parent_path, folder_name):
    """
    创建单层子目录（不递归！上级目录必须已存在）

    参数:
        parent_path: NAS 上的父目录绝对路径，如 /QA/验货相关文件/验货图片/2026年
        folder_name: 要创建的子目录名称

    返回:
        True 表示创建成功或已存在，False 表示失败
    """
    # 先检查是否已存在
    try:
        existing = list_files(parent_path)
        for f in existing:
            if f.get('name') == folder_name and f.get('isdir'):
                return True  # 已存在，无需创建
    except Exception:
        pass

    # 不存在则创建
    return create_folder(parent_path, folder_name)


def upload_report_to_nas(report_type, year, pdf_bytes, pdf_filename):
    """
    上传检验报告 PDF 到 NAS 对应路由目录下的产品子文件夹

    根据路由映射获取 report 基础路径，在其下创建一个以产品信息命名的子文件夹，
    然后将 PDF 写入该子文件夹。只创建一级子目录（不递归）。

    参数:
        report_type:  报告类型
        year:         年份字符串
        pdf_bytes:    PDF 文件的 bytes 内容
        pdf_filename: PDF 文件名

    返回:
        (success, nas_full_path, detail_msg)
        例如: (True, '/QA/验货相关文件/驻厂验货报告/2026年度/Aura_SKU001_产品名/Aura_SKU001_产品名验货报告20260616.pdf', '')
    """
    report_base, _ = get_nas_routes(report_type, year)

    # 提取产品子文件夹名（PDF文件名去掉扩展名和"验货报告日期"后缀）
    folder_candidate = os.path.splitext(pdf_filename)[0]

    # 去掉末尾的"验货报告YYYYMMDD"以得到纯产品名
    import re as _re
    cleaned = _re.sub(r'验货报告\d{8}$', '', folder_candidate)
    # 也处理带下划线时间戳的变体
    cleaned = _re.sub(r'验货报告\d{8}_\d{8}_\d{6}$', '', cleaned)
    if not cleaned:
        cleaned = folder_candidate

    # 创建产品子文件夹（仅一层）
    report_base_clean = report_base.rstrip('/')
    ensure_single_folder(report_base_clean, cleaned)

    # 上传 PDF 到该子文件夹
    nas_target_folder = f"{report_base_clean}/{cleaned}"
    ok, result = upload_file(nas_target_folder, pdf_filename, pdf_bytes)
    if ok:
        return True, result, ''
    else:
        # 重名处理
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_no_ext, ext_part = os.path.splitext(pdf_filename)
        new_name = f"{name_no_ext}_{timestamp}{ext_part}"
        ok2, result2 = upload_file(nas_target_folder, new_name, pdf_bytes)
        if ok2:
            return True, result2, ''
        return False, nas_target_folder, f"上传失败: {result}"


def generate_report_path(report_type, year, brand, po, date_str):
    """
    根据报告信息生成 NAS 存储路径

    返回: (folder_path, filename_prefix)
    例如: ('/QA/验货相关文件/驻厂验货报告/2026年度/Aura_PO12345_20260615', 'Aura_PO12345_20260615')
    """
    # 映射报告类型到子目录
    type_map = {
        '驻厂验货报告': '驻厂验货报告',
        '不合格报告': '不合格报告（东莞仓验货）',
        '第三方检验报告': '第三方检验资料库/第三方验货报告',
    }
    sub_dir = type_map.get(report_type, '驻厂验货报告')

    # 构建路径
    base = f"{NAS_BASE_PATH}/{sub_dir}/{year}年度"
    date_clean = date_str.replace('-', '')
    report_dir_name = f"{brand}_{po}_{date_clean}" if po else f"{brand}_{date_clean}"
    full_dir = f"{base}/{report_dir_name}"

    return full_dir, report_dir_name


def process_zip_images(zip_bytes, zip_filename, report_type, year):
    """
    处理 ZIP 压缩包：提取顶层文件夹名和年份，将图片流式上传到 NAS 验货图片目录

    用户操作：右键压缩外层文件夹 → 同名 .zip。压缩包内部第一层就是同名文件夹。
    例如：TUBRBO (POSSHK-006932) 厚膜烤盘 EG13 验货图片 20251230.zip
          内部结构：TUBRBO (POSSHK-006932) 厚膜烤盘 EG13 验货图片 20251230/
                      ├── img001.jpg
                      ├── img002.jpg
                      └── __MACOSX/ (自动过滤)

    参数:
        zip_bytes:    ZIP 文件的 bytes 内容
        zip_filename: 原始 ZIP 文件名（用于提取文件夹名称和年份）
        report_type:  报告类型（用于路由映射获取 picture 基础路径）
        year:         年份字符串

    返回:
        (success, nas_folder_path, uploaded_count, detail_msg)
    """
    # 1. 提取文件夹名称（去掉 .zip 后缀）
    folder_name = os.path.splitext(repair_filename_mojibake(zip_filename))[0]

    # 2. 从路由映射获取图片基础路径
    _, picture_base = get_nas_routes(report_type, year)

    # 3. 拼装完整 NAS 目标路径：{picture_base}/{folder_name}/
    picture_base_clean = picture_base.rstrip('/')
    nas_folder = f"{picture_base_clean}/{folder_name}"

    # 4. 创建唯一一层产品专属文件夹（上级目录必须已人工创建）
    ensure_single_folder(picture_base_clean, folder_name)

    # 5. 内存中打开 ZIP，遍历文件
    image_paths = []
    skipped_dirs = 0
    skipped_hidden = 0
    skipped_non_image = 0
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    zip_buffer = io.BytesIO(zip_bytes)
    try:
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            for member in zf.infolist():
                fixed_member_name = repair_filename_mojibake(member.filename)
                bare_name = fixed_member_name.split('/')[-1]

                if member.is_dir():
                    skipped_dirs += 1
                    continue

                if bare_name.startswith('.') or '__MACOSX' in fixed_member_name:
                    skipped_hidden += 1
                    continue

                ext = os.path.splitext(bare_name)[1].lower()
                if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'):
                    skipped_non_image += 1
                    continue

                file_content = zf.read(member)
                ok, result = upload_file(nas_folder, bare_name, file_content)
                if ok:
                    image_paths.append(result)
                else:
                    name_no_ext, ext_part = os.path.splitext(bare_name)
                    new_name = f"{name_no_ext}_{timestamp}_{len(image_paths)}{ext_part}"
                    ok2, result2 = upload_file(nas_folder, new_name, file_content)
                    if ok2:
                        image_paths.append(result2)

    except zipfile.BadZipFile:
        return False, nas_folder, 0, "ZIP 文件格式无效，无法解压"
    except Exception as e:
        return False, nas_folder, 0, f"ZIP 处理异常: {str(e)[:200]}"

    # 6. 汇总结果
    detail = f"成功上传 {len(image_paths)} 张图片到 {nas_folder}"
    if skipped_dirs or skipped_hidden or skipped_non_image:
        parts = []
        if skipped_dirs: parts.append(f"跳过 {skipped_dirs} 个目录")
        if skipped_hidden: parts.append(f"跳过 {skipped_hidden} 个隐藏文件")
        if skipped_non_image: parts.append(f"跳过 {skipped_non_image} 个非图片文件")
        detail += "（" + "，".join(parts) + "）"

    return True, nas_folder, len(image_paths), detail


# ── 测试 ─────────────────────────────────────────────
if __name__ == '__main__':
    # 测试连接
    print('测试 NAS 连接...')
    sid = _ensure_login()
    print(f'✅ 登录成功, SID: {sid[:20]}...')

    print('\n列出 /QA/验货相关文件:')
    for f in list_files('/QA/验货相关文件'):
        print(f"  {'[DIR]' if f.get('isdir') else '[FILE]'} {f['name']}")

    # 测试上传
    print('\n测试上传...')
    test_content = 'NAS客户端模块测试文件 - 品质系统'.encode('utf-8')
    ok, result = upload_file('/QA/验货相关文件', 'nas_client_test.txt', test_content)
    if ok:
        print(f'✅ 上传成功: {result}')
        delete_file('/QA/验货相关文件/nas_client_test.txt')
        print('✅ 测试文件已清理')
    else:
        print(f'❌ 上传失败: {result}')


def check_connection():
    """
    检测 NAS 连接是否可用
    返回: (available: bool, message: str)
    """
    try:
        sid = _ensure_login()
        _api_call('list', folder_path='/QA/验货相关文件')
        return True, '连接正常'
    except Exception as e:
        return False, str(e)
