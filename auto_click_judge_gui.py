"""自动点击评测 v3——遍历大关所有关卡，逐个点击评测按钮，间隔后进入下一关。

只负责点击评测按钮，不轮询/统计结果。用 URL 强制导航保证每关都进入并评测，
整页连续导航不关闭，单关异常不中断整个大关。
"""
import asyncio
import re
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from playwright.async_api import async_playwright

from educoder_reminder.auth import signing_headers
from educoder_reminder.client import open_client
from educoder_reminder.login import verify_identity
from educoder_reminder.submit import walk_prev_to_head

DEFAULT_COOKIE = 'autologin_trustie=c181d23024e3a59b8bcb15fb9adc9be7165c87d5; _educoder_session=ada28f740f9cd26a78cabe54db4c148'


def _token_from_cookie(cookie):
    for part in (cookie or '').split(';'):
        if '=' in part:
            k, _, v = part.strip().partition('=')
            if k == '_educoder_session':
                return v
    return ''


def _identity_headers(token, cookie):
    return {**signing_headers('GET'), 'Accept': 'application/json',
            'Content-Type': 'application/json; charset=utf-8', 'Pc-Authorization': token,
            'Cookie': cookie, 'X-EDU-Type': 'pc', 'Referer': 'https://www.educoder.net/',
            'Origin': 'https://www.educoder.net', 'X-Original-Protocol': 'https:',
            'X-Original-Host': 'www.educoder.net', 'X-Original-Origin': 'https://www.educoder.net'}


async def _resolve_username(token, cookie):
    async with async_playwright() as p:
        ctx = await p.request.new_context(extra_http_headers=_identity_headers(token, cookie), timeout=30000)
        try:
            return await verify_identity(ctx)
        finally:
            await ctx.dispose()


def _parse_task_url(url):
    m = re.search(r'/tasks/([^/]+)/(\d+)/([A-Za-z0-9_-]+)', url or '')
    if not m:
        raise ValueError(f'无法解析任务链接: {url}（需要 /tasks/{code}/{hw}/{gid} 形式）')
    return m.group(1), m.group(2), m.group(3)


def _gid_url(code, hw, gid):
    return f'https://www.educoder.net/tasks/{code}/{hw}/{gid}'


async def _full_chain(client, entry):
    """取整个关卡链：先沿 prev 回退到头，再从入口沿 next 前进补齐后面的关卡。"""
    ordered, cache = await walk_prev_to_head(client, entry)
    seen = set(ordered)
    cursor = str(entry)
    while cursor and cursor not in seen:
        seen.add(cursor)
        d = cache.get(cursor)
        if d is None:
            d = await client.get(f'/api/tasks/{cursor}.json', {}, strict_status=False)
            cache[cursor] = d
        nxt = d.get('next_game')
        cursor = str(nxt) if nxt else ''
        if cursor:
            ordered.append(cursor)
    return ordered, cache


async def run(urls, cookie, interval, log):
    token = _token_from_cookie(cookie)
    username = await _resolve_username(token, cookie)
    log(f'账号 username: {username}')
    wait = int(interval) if interval and interval > 0 else 30
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='msedge', headless=False)
        ctx = await browser.new_context(viewport={'width': 1500, 'height': 950})
        for part in cookie.split(';'):
            if '=' in part:
                k, _, v = part.strip().partition('=')
                await ctx.add_cookies([{'name': k, 'value': v, 'domain': '.educoder.net', 'path': '/'}])
        async with open_client(token=token, cookie=cookie, username=username) as client:
            for idx, url in enumerate(urls, 1):
                code, hw, entry = _parse_task_url(url)
                log(f'\n[{idx}/{len(urls)}] 大关入口: {entry}')
                ordered, cache = await _full_chain(client, entry)
                log(f'  关卡链 {len(ordered)} 个: {ordered}')
                page = await ctx.new_page()
                for i, gid in enumerate(ordered):
                    try:
                        gurl = _gid_url(code, hw, gid)
                        await page.goto(gurl, wait_until='domcontentloaded', timeout=60000)
                        await page.wait_for_timeout(8000)
                        # 启动环境（如需）
                        try:
                            start = page.get_by_role('button', name='启动环境')
                            if await start.count() > 0:
                                await start.first.click(timeout=6000)
                                log('  已点击 启动环境')
                                await page.wait_for_timeout(4000)
                        except Exception:
                            pass
                        # 点击"评测"按钮
                        judge = page.locator('button[title="运行评测"]')
                        if await judge.count() == 0:
                            judge = page.get_by_role('button', name='评测')
                        await judge.first.wait_for(state='visible', timeout=90000)
                        await judge.first.click(timeout=10000)
                        log(f'  → 评测 {gid}: 已点击评测按钮')
                        # 等间隔（平台小关评测间隔）
                        log(f'    等待 {wait}s 间隔后进入下一关…')
                        await page.wait_for_timeout(wait * 1000)
                    except Exception as e:
                        log(f'  ✗ 关 {gid} 异常: {e}（继续下一关）')
                    # 进入下一关（URL 强制导航，保证不漏关）
                    if i < len(ordered) - 1:
                        nxt = ordered[i + 1]
                        try:
                            await page.goto(_gid_url(code, hw, nxt), wait_until='domcontentloaded', timeout=60000)
                            await page.wait_for_timeout(2000)
                            log(f'    已进入下一关 {nxt}')
                        except Exception as e:
                            log(f'  ✗ 进入 {nxt} 失败: {e}')
                await page.close()
        await browser.close()
        log('\n全部完成。')


class ClickJudgeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        root.title('自动点击评测 Auto Click Judge v3')
        root.geometry('820x660')
        self._build_ui()
        self.root.after(100, self._poll)

    def _build_ui(self):
        pad = {'padx': 8, 'pady': 5}
        frm = ttk.LabelFrame(self.root, text='输入信息')
        frm.pack(fill='x', padx=10, pady=(10, 6))

        self.var_cookie = tk.StringVar(value=DEFAULT_COOKIE)
        self.var_interval = tk.StringVar(value='30')

        ttk.Label(frm, text='账号 Cookie').grid(row=0, column=0, sticky='w', **pad)
        ttk.Entry(frm, textvariable=self.var_cookie, width=100).grid(row=0, column=1, sticky='we', **pad)
        ttk.Label(frm, text='大关任务链接（每行一个）').grid(row=1, column=0, sticky='w', **pad)
        self.txt_links = tk.Text(frm, height=6, width=100, wrap='none')
        self.txt_links.grid(row=1, column=1, sticky='we', **pad)
        self.txt_links.insert('1.0', 'https://www.educoder.net/tasks/2i6ng7vp/4231205/fxe39zkc7gij')
        ttk.Label(frm, text='间隔（秒，可填0）').grid(row=2, column=0, sticky='w', **pad)
        ttk.Entry(frm, textvariable=self.var_interval, width=12).grid(row=2, column=1, sticky='w', **pad)
        ttk.Label(frm, text='遍历大关所有关卡，逐个点击评测，间隔后强制进入下一关，不关闭页面。',
                  foreground='#888').grid(row=3, column=0, columnspan=2, sticky='w', **pad)

        frm_btn = ttk.Frame(self.root)
        frm_btn.pack(fill='x', padx=10, pady=6)
        self.btn_run = ttk.Button(frm_btn, text='开始遍历评测', command=self._start)
        self.btn_run.pack(side='left')

        frm_log = ttk.LabelFrame(self.root, text='日志')
        frm_log.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.txt_log = tk.Text(frm_log, height=14, wrap='word', state='disabled')
        slog = ttk.Scrollbar(frm_log, orient='vertical', command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=slog.set)
        self.txt_log.pack(side='left', fill='both', expand=True)
        slog.pack(side='right', fill='y')

    def log(self, msg):
        self.txt_log.configure(state='normal')
        self.txt_log.insert('end', msg + '\n')
        self.txt_log.see('end')
        self.txt_log.configure(state='disabled')

    def _post(self, item):
        self.q.put(item)

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == 'log':
                    self.log(item[1])
                elif item[0] == 'busy':
                    self.busy = True
                    self.btn_run.configure(state='disabled')
                elif item[0] == 'done':
                    self.busy = False
                    self.btn_run.configure(state='normal')
                    self.log(item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _start(self):
        if self.busy:
            return
        cookie = self.var_cookie.get().strip()
        raw = self.txt_links.get('1.0', 'end').strip()
        urls = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        try:
            interval = float(self.var_interval.get().strip() or 0)
        except ValueError:
            interval = 30.0
        if not (cookie and urls):
            messagebox.showwarning('提示', '请填：账号 Cookie 和至少一个大关任务链接。')
            return
        self._post(('busy',))
        self.log('开始遍历评测…')
        threading.Thread(target=self._worker, args=(urls, cookie, interval), daemon=True).start()

    def _worker(self, urls, cookie, interval):
        emit = lambda m: self._post(('log', m))
        try:
            asyncio.run(run(urls, cookie, interval, emit))
            self._post(('done', '执行完成。'))
        except Exception as e:
            self._post(('log', f'✗ 执行失败：{e}'))
            self._post(('done', '执行失败。'))


def main():
    root = tk.Tk()
    ClickJudgeApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
