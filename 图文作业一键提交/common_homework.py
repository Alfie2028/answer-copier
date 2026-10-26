# -*- coding: utf-8 -*-
"""
头歌(EduCoder) 图文作业(common_homework) 一键提交 / 拉取 核心模块（可迁移，仅依赖 playwright）

已验证的机制（2026-10 探查确认）：
  - 目标账号(未提交)点"提交作品" → 新标签页打开 {classroom}/common_homework/{hwid}/post 提交页
  - 已提交账号点"修改作品"    → 新标签页打开 {classroom}/common_homework/{hwid}/{editId}/edit 编辑页
  - 提交页/编辑页均为 antd Upload 组件：
      * input[type=file] 隐藏(不可见)但存在, multiple=true 支持多文件
      * 通过 set_input_files 直接注入本地文件即可完成上传
      * 页面底部按钮：上传附件 / 提交 / 取消
  - 已提交文件以 <a class="ant-upload-list-item-name" href="OSS签名链接"> 展示，可下载拉取

用法：
    from common_homework import submit_common_homework, fetch_submitted_files

    # 一键提交：目标账号对某作业上传本地答案并提交
    ok, msg = submit_common_homework(
        cookie='autologin_trustie=...; _educoder_session=...',
        detail_url='https://w.educoder.net/classrooms/{课堂code}/common_homework/{作业id}/detail',
        file_paths=[r'D:/答案/软件项目管理.docx'],
        description='可选：作业描述'
    )

    # 拉取：答案账号已提交文件下载到本地
    files = fetch_submitted_files(
        cookie='autologin_trustie=...; _educoder_session=...',
        edit_url='https://w.educoder.net/classrooms/{课堂code}/common_homework/{作业id}/{editId}/edit',
        save_dir=r'D:/拉取答案'
    )
"""

import os
import asyncio
import re
import base64
import hashlib
import time
import uuid
import urllib.request
import requests
from playwright.async_api import async_playwright

# Educoder 公开客户端签名常量（见 educoder_reminder/auth.py）
_AK = 'WlRsa1pEVmlORE15TW1ZNVpqZGtPRE5rTURBNVpHVTVZbVpoTVRBd1l6TT0='
_SK = 'TW1VelpHRXdObUZsTWpaaVlUbG1OelpoTldRNFpETTFOVGMwTm1ZeVptVT0='


def _signing_headers(method='GET', timestamp=None):
    timestamp = time.time_ns() // 1_000_000 if timestamp is None else timestamp
    ak, sk = (base64.b64decode(base64.b64decode(v)).decode('ascii') for v in (_AK, _SK))
    message = f'method={method.upper()}&ak={ak}&sk={sk}&time={timestamp}'
    signature = hashlib.md5(base64.b64encode(message.encode('ascii')), usedforsecurity=False).hexdigest()
    return {'X-EDU-Timestamp': str(timestamp), 'X-EDU-Signature': signature,
            'X-Request-Id': str(uuid.uuid4())}


def _cookie_map(cookie_str):
    d = {}
    for part in cookie_str.split(';'):
        if '=' in part:
            k, _, v = part.strip().partition('=')
            d[k] = v
    return d


def _api_headers(cookie_str, method='GET'):
    d = _cookie_map(cookie_str)
    h = _signing_headers(method)
    h['Cookie'] = cookie_str
    h['Pc-Authorization'] = d.get('_educoder_session', '')
    h['X-EDU-Type'] = 'pc'
    h['Referer'] = 'https://www.educoder.net/'
    h['Origin'] = 'https://www.educoder.net'
    h['User-Agent'] = 'Mozilla/5.0'
    return h

def _launch_kwargs():
    return {'channel': 'msedge'}


async def _inject_cookies(ctx, cookie_str):
    for part in cookie_str.split(';'):
        if '=' in part:
            k, _, v = part.strip().partition('=')
            try:
                await ctx.add_cookies([{'name': k, 'value': v, 'domain': '.educoder.net', 'path': '/'}])
            except Exception:
                pass


def _dispatch_click(button_text):
    """返回一段 JS：找到文本完全等于 button_text 的 <button>，派发可冒泡 click 触发 React onClick。"""
    text = button_text.replace('\\', '\\\\').replace("'", "\\'")
    return """
    (() => {
      const btns = [...document.querySelectorAll('button')];
      const b = btns.find(x => (x.innerText||'').trim() === '%s');
      if (b) { b.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window})); return 'clicked'; }
      return 'notfound';
    })()
    """ % text


async def _open_submit_page(ctx, detail_url, button_text='提交作品', timeout_ms=20000):
    """进入作业详情页，点击提交/修改作品按钮，捕获打开的新标签页(提交页)。全程轮询代替固定等待，大幅提速。"""
    page = await ctx.new_page()
    popups = []
    page.on('popup', lambda pp: popups.append(pp))
    await page.goto(detail_url, wait_until='domcontentloaded', timeout=timeout_ms)
    # 轮询"提交作品/修改作品"按钮出现(SPA 渲染完成)，替代固定 15s
    btn_deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    while asyncio.get_event_loop().time() < btn_deadline:
        has = await page.evaluate(
            "(() => [...document.querySelectorAll('button')].some(x => (x.innerText||'').trim() === '%s'))" % button_text)
        if has:
            break
        await page.wait_for_timeout(400)
    await page.wait_for_timeout(400)  # 按钮渲染稳定
    result = await page.evaluate(_dispatch_click(button_text))
    # 轮询 popup 出现，替代固定 9s
    popup_deadline = asyncio.get_event_loop().time() + 12000 / 1000
    while asyncio.get_event_loop().time() < popup_deadline and not popups:
        await page.wait_for_timeout(300)
    if not popups:
        raise RuntimeError(f'点击"{button_text}"后未打开提交页(popup)，dispatch结果={result}')
    pp = popups[0]
    try:
        await pp.wait_for_load_state('domcontentloaded', timeout=timeout_ms)
    except Exception:
        pass
    # 轮询提交页出现"描述"输入框，替代固定 8s
    ready_deadline = asyncio.get_event_loop().time() + 15000 / 1000
    while asyncio.get_event_loop().time() < ready_deadline:
        has = await pp.evaluate(
            "() => !!([...document.querySelectorAll('textarea')].find(t=>(t.getAttribute('placeholder')||'').includes('描述')))")
        if has:
            break
        await pp.wait_for_timeout(400)
    await page.close()
    return pp


async def _wait_upload_done(page, n_expected, timeout_ms=60000):
    """等待 n_expected 个文件全部进入 ant-upload-list-item-done(上传完成)状态。"""
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    while asyncio.get_event_loop().time() < deadline:
        done = await page.evaluate("""
        () => document.querySelectorAll('.ant-upload-list-item.ant-upload-list-item-done').length
        """)
        if done >= n_expected:
            return done
        await page.wait_for_timeout(1000)
    return done


async def _fill_and_submit(page, file_paths, description, timeout_ms=20000):
    """在已打开的提交页上：填描述(必填)→上传多文件→点提交→处理确认→返回 (ok, msg)。
    描述输入框是 CodeMirror 编辑器且默认开着"实时预览"(on-preview)，关闭后 setValue 写入。"""
    desc = (description or '').strip() or '见附件'
    try:
        tas = page.locator('textarea')
        cnt = await tas.count()
        target_idx = None
        for i in range(cnt):
            ph = (await tas.nth(i).get_attribute('placeholder')) or ''
            if '描述' in ph:
                target_idx = i
                break
        if target_idx is not None:
            # 1) 若描述编辑器开着实时预览则关闭
            await page.evaluate("""() => {
                const tas=[...document.querySelectorAll('textarea')];
                const ta=tas.find(t=>(t.getAttribute('placeholder')||'').includes('描述'));
                if(!ta) return;
                let up=ta, wrap=null;
                while(up){ if((up.className||'').toString().includes('markdown-editor-wrapper')){ wrap=up; break; } up=up.parentElement; }
                if(!wrap) return;
                const cont=wrap.querySelector('.markdown-editor-container');
                if(cont && (cont.className||'').includes('on-preview')){
                    const a=[...wrap.querySelectorAll('.markdown-toolbar-container a')].find(
                        x=>(x.getAttribute('title')||'')==='关闭实时预览');
                    if(a) a.click();
                }
            }""")
            await page.wait_for_timeout(300)
            # 2) 用 CodeMirror 实例 setValue 写入描述(组件提交时读 getValue，确保非空)
            await page.evaluate("""(text) => {
                const ta=[...document.querySelectorAll('textarea')].find(
                    t=>(t.getAttribute('placeholder')||'').includes('描述'));
                if(!ta) return;
                const cm=ta.parentElement ? ta.parentElement.querySelector('.CodeMirror') : null;
                if(cm && cm.CodeMirror && typeof cm.CodeMirror.setValue==='function'){
                    cm.CodeMirror.setValue(text);
                }
            }""", desc)
        else:
            # 兜底：未找到"描述"输入框则填第一个 textarea
            ta = page.locator('textarea').first
            if await ta.count() > 0:
                await ta.fill(desc)
    except Exception:
        pass
    # 上传文件(多文件)
    file_input = page.locator('input[type=file]').first
    if await file_input.count() == 0:
        raise RuntimeError('提交页未找到上传 input[type=file]')
    n = len(file_paths)
    await file_input.set_input_files(file_paths)
    await page.wait_for_timeout(1500)
    done = await _wait_upload_done(page, n)
    if done < n:
        raise RuntimeError(f'上传未全部完成: {done}/{n}')
    # 点击"提交"按钮
    submit_btns = page.locator('button:has-text("提交")')
    await submit_btns.last.click(timeout=8000)
    await page.wait_for_timeout(2500)
    # 处理可能的确认弹窗(antd Modal.confirm 的"确定/提交")
    confirmed = False
    for _ in range(3):
        has_modal = await page.evaluate(
            "() => !!document.querySelector('.ant-modal-confirm .ant-btn-primary, .ant-modal .ant-btn-primary')")
        if has_modal:
            try:
                await page.locator('.ant-modal .ant-btn-primary').last.click(timeout=4000)
                confirmed = True
                await page.wait_for_timeout(2500)
                break
            except Exception:
                pass
        else:
            break
    await page.wait_for_timeout(2500)
    # 结果判断：URL 回到详情(非 /post) 或出现成功提示
    final_url = page.url
    body = ''
    try:
        body = await page.evaluate("() => document.body.innerText")
    except Exception:
        pass
    hint = '提交成功' if ('提交成功' in body or 'success' in body.lower() or '/post' not in final_url) else '已点击提交，请人工核对'
    return True, f'{hint} (final={final_url[:80]}, confirmed={confirmed})'


async def _do_submit(cookie, detail_url, file_paths, description, button_text, timeout_ms):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, **_launch_kwargs())
    try:
        ctx = await browser.new_context(viewport={'width': 1500, 'height': 950})
        await _inject_cookies(ctx, cookie)
        page = await _open_submit_page(ctx, detail_url, button_text, timeout_ms)
        try:
            return await _fill_and_submit(page, file_paths, description, timeout_ms)
        finally:
            try:
                await page.close()
            except Exception:
                pass
    finally:
        await browser.close()


def submit_common_homework(cookie, detail_url, file_paths, description='', button_text='提交作品', timeout_ms=20000):
    """
    一键提交：用给定 cookie 账号，对 detail_url 作业上传 file_paths(多文件) 并提交。
    返回 (ok:bool, msg:str)。
    """
    file_paths = [os.path.abspath(p) for p in file_paths if os.path.isfile(p)]
    if not file_paths:
        return False, '没有可上传的本地文件'
    try:
        ok, msg = asyncio.run(_do_submit(cookie, detail_url, file_paths, description, button_text, timeout_ms))
        return ok, msg
    except Exception as e:
        return False, f'提交失败: {e}'


async def _do_fetch(cookie, edit_url, save_dir, timeout_ms):
    os.makedirs(save_dir, exist_ok=True)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, **_launch_kwargs())
    try:
        ctx = await browser.new_context(viewport={'width': 1500, 'height': 950})
        await _inject_cookies(ctx, cookie)
        page = await ctx.new_page()
        await page.goto(edit_url, wait_until='domcontentloaded', timeout=timeout_ms)
        await page.wait_for_timeout(15000)
        items = await page.evaluate("""
        () => {
          const out = [];
          for (const a of document.querySelectorAll('a.ant-upload-list-item-name')) {
            out.push({name: (a.getAttribute('title')||a.innerText||'').trim(), href: a.getAttribute('href')||''});
          }
          return out;
        }""")
        saved = []
        for it in items:
            href = it['href']
            if not href:
                continue
            # 文件名：取 href 里最后一段或 title
            raw_name = it['name'].split('\u3000')[0].strip()
            base = re.sub(r'[\\/:*?"<>|]', '_', raw_name or 'file')
            path = os.path.join(save_dir, base)
            req = urllib.request.Request(href, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            with open(path, 'wb') as f:
                f.write(data)
            saved.append((base, len(data)))
        return saved
    finally:
        await browser.close()


def fetch_submitted_files(cookie, edit_url, save_dir, timeout_ms=20000):
    """
    拉取：用答案账号 cookie 访问已提交作业的 /edit 页，下载其已提交的所有文件到 save_dir。
    返回 [(文件名, 字节数), ...]。
    """
    try:
        return asyncio.run(_do_fetch(cookie, edit_url, save_dir, timeout_ms))
    except Exception as e:
        return f'拉取失败: {e}'


import re


def _extract_classroom(course_list_url):
    m = re.search(r'/classrooms/([^/]+)/common_homework', course_list_url)
    if m:
        return m.group(1)
    m = re.search(r'/classrooms/([^/]+)', course_list_url)
    return m.group(1) if m else None


def _detail_url(course_list_url, hw_id):
    cid = _extract_classroom(course_list_url)
    return f'https://w.educoder.net/classrooms/{cid}/common_homework/{hw_id}/detail'


async def _do_list(cookie, course_list_url, timeout_ms=20000):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, **_launch_kwargs())
    try:
        ctx = await browser.new_context(viewport={'width': 1500, 'height': 950})
        await _inject_cookies(ctx, cookie)
        page = await ctx.new_page()
        hw = []
        async def on_resp(r):
            if 'homework_commons' in r.url:
                try:
                    body = await r.json()
                    for it in (body.get('homeworks') or []):
                        hw.append((it.get('id'), it.get('name')))
                except Exception:
                    pass
        page.on('response', on_resp)
        await page.goto(course_list_url, wait_until='domcontentloaded', timeout=timeout_ms)
        await page.wait_for_timeout(15000)
        seen = set(); out = []
        for i, n in hw:
            if i not in seen and i:
                seen.add(i); out.append((i, n))
        return out
    finally:
        await browser.close()


def list_homeworks(cookie, course_list_url, timeout_ms=20000):
    """列出课程下全部图文作业 [(homework_id, 作业名), ...]（同步 requests，稳定）。"""
    classroom = _extract_classroom(course_list_url)
    if not classroom:
        return '无法解析课程 classroom id'
    url = (f'https://data.educoder.net/api/courses/{classroom}/homework_commons.json'
           f'?coursesId={classroom}&id={classroom}&limit=20&type=1')
    try:
        resp = requests.get(url, headers=_api_headers(cookie), timeout=25)
        data = resp.json()
        out = []
        seen = set()
        for it in (data.get('homeworks') or []):
            iid = it.get('homework_id') or it.get('id')
            name = it.get('name')
            if iid and iid not in seen:
                seen.add(iid)
                out.append((iid, name))
        return out
    except Exception as e:
        return f'列作业失败: {e}'


def _match_folder(root, hw_name):
    """在 root 的子文件夹里，用作业名做包含匹配，返回匹配到的文件夹路径(或None)。"""
    if not os.path.isdir(root):
        return None
    # 去序号/常用前缀，取核心词
    def norm(s):
        s = re.sub(r'^\d+\s*[、.]?\s*', '', s.strip())
        s = re.sub(r'软件工程导论-', '', s)
        return s.strip()
    core = norm(hw_name)
    try:
        for d in os.listdir(root):
            p = os.path.join(root, d)
            if os.path.isdir(p):
                dc = norm(d)
                if core and (core in d or core in dc or dc in core or d in hw_name):
                    return p
    except Exception:
        pass
    return None


def submit_course(cookie, course_list_url, answers_root, description='', only_ids=None, timeout_ms=20000):
    """
    一键提交（可按需）：列出全部图文作业，仅处理 only_ids 指定的作业(id 集合，None=全部)，
    对每个作业从 answers_root 下匹配子文件夹上传本地文件并提交。返回 [(作业名, ok, msg), ...]。
    """
    hw = list_homeworks(cookie, course_list_url, timeout_ms)
    if isinstance(hw, str):
        return hw
    results = []
    for hw_id, name in hw:
        if only_ids is not None and hw_id not in only_ids:
            results.append((name, False, '未勾选(跳过)'))
            continue
        detail = _detail_url(course_list_url, hw_id)
        folder = _match_folder(answers_root, name)
        if not folder:
            results.append((name, False, '未匹配到本地答案文件夹'))
            continue
        files = []
        for f in sorted(os.listdir(folder)):
            fp = os.path.join(folder, f)
            if os.path.isfile(fp):
                files.append(fp)
        if not files:
            results.append((name, False, '匹配到文件夹但无文件'))
            continue
        ok, msg = submit_common_homework(cookie, detail, files, description, '提交作品', timeout_ms)
        results.append((name, ok, msg))
    return results


async def _do_submit_course_fast(cookie, course_list_url, answers_root, description, only_ids, timeout_ms):
    """复用单个浏览器快速提交：一个 browser+context 串行处理全部作业(免每次启动浏览器)，配合轮询等待提速。"""
    hw = list_homeworks(cookie, course_list_url, timeout_ms)
    if isinstance(hw, str):
        return hw
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, **_launch_kwargs())
    results = []
    try:
        ctx = await browser.new_context(viewport={'width': 1500, 'height': 950})
        await _inject_cookies(ctx, cookie)
        for hw_id, name in hw:
            if only_ids is not None and hw_id not in only_ids:
                results.append((name, False, '未勾选(跳过)'))
                continue
            detail = _detail_url(course_list_url, hw_id)
            folder = _match_folder(answers_root, name)
            if not folder:
                results.append((name, False, '未匹配到本地答案文件夹'))
                continue
            files = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                     if os.path.isfile(os.path.join(folder, f))]
            if not files:
                results.append((name, False, '匹配到文件夹但无文件'))
                continue
            try:
                page = await _open_submit_page(ctx, detail, '提交作品', timeout_ms)
                try:
                    ok, msg = await _fill_and_submit(page, files, description, timeout_ms)
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass
                results.append((name, ok, msg))
            except Exception as e:
                results.append((name, False, str(e)))
        await ctx.close()
        return results
    finally:
        await browser.close()


def submit_course_fast(cookie, course_list_url, answers_root, description='', only_ids=None, timeout_ms=20000):
    """复用单个浏览器快速提交整门课程(免每作业起浏览器 + 轮询等待)。返回 [(作业名, ok, msg), ...]。"""
    try:
        return asyncio.run(_do_submit_course_fast(cookie, course_list_url, answers_root, description, only_ids, timeout_ms))
    except Exception as e:
        return f'快速提交失败: {e}'


async def _do_fetch_course(cookie, course_list_url, save_root, only_ids, timeout_ms):
    os.makedirs(save_root, exist_ok=True)
    hw = list_homeworks(cookie, course_list_url, timeout_ms)
    if isinstance(hw, str):
        return hw
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, **_launch_kwargs())
    try:
        ctx = await browser.new_context(viewport={'width': 1500, 'height': 950})
        await _inject_cookies(ctx, cookie)
        page = await ctx.new_page()
        saved = []
        for hw_id, name in hw:
            if only_ids is not None and hw_id not in only_ids:
                saved.append((name, 0, '未勾选(跳过)'))
                continue
            detail = _detail_url(course_list_url, hw_id)
            await page.goto(detail, wait_until='domcontentloaded', timeout=timeout_ms)
            await page.wait_for_timeout(15000)
            has_modify = await page.evaluate(
                "() => [...document.querySelectorAll('button')].some(x => (x.innerText||'').trim() === '修改作品')")
            if not has_modify:
                saved.append((name, 0, '未提交(跳过)'))
                continue
            await page.evaluate("""
            () => { const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').trim()==='修改作品');
                    if(b) b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window})); }""")
            try:
                pp = await page.wait_for_event('popup', timeout=10000)
            except Exception:
                saved.append((name, 0, '修改作品未弹出编辑页'))
                continue
            try:
                await pp.wait_for_load_state('domcontentloaded', timeout=timeout_ms)
            except Exception:
                pass
            await pp.wait_for_timeout(8000)
            items = await pp.evaluate("""
            () => [...document.querySelectorAll('a.ant-upload-list-item-name')].map(a => ({
                name:(a.getAttribute('title')||a.innerText||'').trim(), href:a.getAttribute('href')||''}))
            """)
            sub = os.path.join(save_root, re.sub(r'[\\/:*?"<>|]', '_', name))
            os.makedirs(sub, exist_ok=True)
            n = 0
            for it in items:
                if not it['href']:
                    continue
                base = re.sub(r'[\\/:*?"<>|]', '_', it['name'].split('\u3000')[0].strip() or 'file')
                path = os.path.join(sub, base)
                try:
                    req = urllib.request.Request(it['href'], headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = resp.read()
                    with open(path, 'wb') as f:
                        f.write(data)
                    n += 1
                except Exception:
                    pass
            try:
                await pp.close()
            except Exception:
                pass
            saved.append((name, n, 'ok'))
        return saved
    finally:
        await browser.close()


def fetch_course(cookie, course_list_url, save_root, only_ids=None, timeout_ms=20000):
    """拉取(可按需)：列出全部图文作业，仅处理 only_ids 指定的作业(id 集合，None=全部)，
    下载其已提交文件到 save_root/作业名/。返回 [(作业名, 文件数, msg)]。"""
    try:
        return asyncio.run(_do_fetch_course(cookie, course_list_url, save_root, only_ids, timeout_ms))
    except Exception as e:
        return f'拉取失败: {e}'


# ============================ 纯 requests 拉取（不依赖 Playwright） ============================
# 逆向确认的签名：AK/SK 需解两层 base64，X-EDU-Signature = md5(base64(f"method={M}&ak&sk&time"))
# 链路：POST works_list.json -> work_id -> GET student_works/{work_id}/edit.json -> attachments[].url -> 下载


def _full_api_headers(cookie_str, method='GET'):
    h = _api_headers(cookie_str, method)
    h['X-Original-Protocol'] = 'https:'
    h['X-Original-Host'] = 'www.educoder.net'
    h['X-Original-Origin'] = 'https://www.educoder.net'
    if method == 'POST':
        h['Content-Type'] = 'application/json'
    return h


def _session_value(cookie_str):
    return _cookie_map(cookie_str).get('_educoder_session', '')


def fetch_course_requests(cookie, username, course_list_url, save_root, only_ids=None, timeout_ms=25000):
    """纯 requests 拉取答案（不启动浏览器）。username=账号登录名(zzud 参数)。
    对每个作业：POST works_list -> work_id -> GET edit.json 拿附件 OSS url -> 下载到 save_root/作业名/。
    返回 [(作业名, 文件数, msg), ...]。"""
    hw = list_homeworks(cookie, course_list_url, timeout_ms)
    if isinstance(hw, str):
        return hw
    classroom = _extract_classroom(course_list_url)
    base = 'https://data.educoder.net/api'
    results = []
    for hw_id, name in hw:
        if only_ids is not None and hw_id not in only_ids:
            results.append((name, 0, '未勾选(跳过)'))
            continue
        try:
            # 1) 拿该作业自己的 work_id
            r = requests.post(f'{base}/homework_commons/{hw_id}/works_list.json?zzud={username}',
                              headers=_full_api_headers(cookie, 'POST'), json={}, timeout=25)
            j = r.json()
            work_id = j.get('work_id')
            if not work_id:
                results.append((name, 0, '未提交或无 work_id'))
                continue
            # 2) 编辑详情 -> 附件列表
            r2 = requests.get(f'{base}/student_works/{work_id}/edit.json'
                              f'?coursesId={classroom}&commonHomeworkId={hw_id}&homeworkId={work_id}&type=3&zzud={username}',
                              headers=_full_api_headers(cookie), timeout=25)
            atts = (r2.json().get('attachments') or [])
            if not atts:
                results.append((name, 0, '无附件'))
                continue
            # 3) 下载
            folder = os.path.join(save_root, name)
            os.makedirs(folder, exist_ok=True)
            n = 0
            for a in atts:
                url, title = a.get('url'), a.get('title') or a.get('id')
                if not url:
                    continue
                safe = re.sub(r'[\\/:*?"<>|]', '_', title)
                path = os.path.join(folder, safe)
                rr = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=120)
                if rr.status_code == 200 and rr.content:
                    with open(path, 'wb') as f:
                        f.write(rr.content)
                    n += 1
            results.append((name, n, 'ok' if n else '下载失败'))
        except Exception as e:
            results.append((name, 0, str(e)))
    return results


if __name__ == '__main__':
    print('common_homework 核心模块加载成功')
    print('函数: submit_common_homework(cookie, detail_url, file_paths, description="")')
    print('      fetch_submitted_files(cookie, edit_url, save_dir)')
    print('      list_homeworks(cookie, course_list_url)')
    print('      submit_course(cookie, course_list_url, answers_root, description="", only_ids=None)')
    print('      fetch_course(cookie, course_list_url, save_root, only_ids=None)')
