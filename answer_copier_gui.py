"""答案搬运器（Answer Copier）——可迁移 GUI 板块。

功能：填 3 项输入（答案账号 cookie、目标账号 cookie、课程链接），点「开始执行」，
自动完成：
  1) 用答案账号导出该课程全部选择题答案（仅凭 cookie，无需密码）
  2) 用目标账号解析其当前关卡链，按关卡标题匹配答案，
     提交所有未通过的选择题关（答错用平台回吐标准答案兜底），使其全部通过
  3) 安全红线：跳过已通过关 / 无答案关 / 已完成实验，不覆盖已完成作业

运行（Windows 本地，需 playwright + 网络可达头歌）：
    C:\\...\\python.exe answer_copier_gui.py
"""
import asyncio
import contextlib
import io
import json
import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from educoder_reminder.auth import signing_headers
from educoder_reminder.client import open_client
from educoder_reminder.errors import CollectionError
from educoder_reminder.export import classroom_display_name, export_experiment
from educoder_reminder.login import verify_identity
from educoder_reminder.submit import (fetch_homework_rows, match_homework,
                                      process_experiment)


def _token_from_cookie(cookie: str) -> str:
    for part in (cookie or '').split(';'):
        if '=' in part:
            k, _, v = part.strip().partition('=')
            if k == '_educoder_session':
                return v
    return ''


def _parse_course_code(url: str) -> str:
    m = re.search(r'/classrooms/([A-Za-z0-9_-]+)', url or '')
    if not m:
        raise CollectionError('无法从课程链接解析课堂 code（需要 /classrooms/{code}/ 形式）。')
    return m.group(1)


def _identity_headers(token: str, cookie: str) -> dict:
    return {**signing_headers('GET'),
            'Accept': 'application/json', 'Content-Type': 'application/json; charset=utf-8',
            'Pc-Authorization': token, 'Cookie': cookie, 'X-EDU-Type': 'pc',
            'Referer': 'https://www.educoder.net/', 'Origin': 'https://www.educoder.net',
            'X-Original-Protocol': 'https:', 'X-Original-Host': 'www.educoder.net',
            'X-Original-Origin': 'https://www.educoder.net'}


async def _resolve_username(token: str, cookie: str) -> str:
    """仅凭 cookie 反查账号 username（login）。"""
    async with async_playwright() as p:
        ctx = await p.request.new_context(extra_http_headers=_identity_headers(token, cookie),
                                          timeout=30000)
        try:
            return await verify_identity(ctx)
        finally:
            await ctx.dispose()


async def run_copy(answer_cookie: str, target_cookie: str, course_url: str,
                   log=lambda m: None):
    """导出答案账号该课程答案 → 自动补全目标账号同课程选择题。返回 stats。"""
    code = _parse_course_code(course_url)
    log(f'课堂 code：{code}')

    # ---- 1) 答案账号导出 ----
    at = _token_from_cookie(answer_cookie)
    au = await _resolve_username(at, answer_cookie)
    log(f'答案账号 username：{au}')
    async with open_client(token=at, cookie=answer_cookie, username=au) as client:
        rows = await fetch_homework_rows(client, code)
        experiments = []
        for hw in rows:
            exp = await export_experiment(client, hw)
            experiments.append(exp)
        n_choice = sum(1 for e in experiments for lv in e['levels'] if lv['kind'] == 'choice')
        n_ans = sum(1 for e in experiments for lv in e['levels']
                    if lv['kind'] == 'choice' and lv.get('answered'))
        log(f'答案账号导出完成：{len(experiments)} 实验，选择题 {n_choice} 关（有答案 {n_ans}）')

    # ---- 2) 目标账号补全 ----
    tt = _token_from_cookie(target_cookie)
    tu = await _resolve_username(tt, target_cookie)
    log(f'目标账号 username：{tu}')
    stats = {'submitted': 0, 'would_submit': 0, 'skipped_passed': 0,
             'skipped_no_answer': 0, 'skipped_error': 0, 'failed': 0, 'processed': 0}
    async with open_client(token=tt, cookie=target_cookie, username=tu) as client:
        rows2 = await fetch_homework_rows(client, code)
        for experiment in experiments:
            name = experiment.get('name') or ''
            hw = match_homework(name, rows2)
            if hw is None:
                log(f'✗ 实验「{name}」未在目标账号课堂找到，跳过。')
                continue
            if hw.get('shixun_finished_status') == 1:
                log(f'- [跳过] 实验已完成：{name}')
                continue
            log(f'▸ 实验：{name}')
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    await process_experiment(client, hw, experiment, True, stats, 90)
                if buf.getvalue():
                    log(buf.getvalue().rstrip())
            except CollectionError as exc:
                log(f'✗ 实验处理失败：{exc}')
    log('===== 补全汇总 =====')
    for k, v in stats.items():
        log(f'  {k}: {v}')
    return stats


class CopierApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        root.title('答案搬运器 Answer Copier')
        root.geometry('760x600')
        self._build_ui()
        self.root.after(100, self._poll)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {'padx': 8, 'pady': 6}
        frm = ttk.LabelFrame(self.root, text='输入信息（3 项）')
        frm.pack(fill='x', padx=10, pady=(10, 6))

        self.var_answer = tk.StringVar()
        self.var_target = tk.StringVar()
        self.var_url = tk.StringVar()

        ttk.Label(frm, text='答案账号 Cookie').grid(row=0, column=0, sticky='w', **pad)
        ttk.Entry(frm, textvariable=self.var_answer, width=100).grid(row=0, column=1, columnspan=2, sticky='we', **pad)
        ttk.Label(frm, text='目标账号 Cookie').grid(row=1, column=0, sticky='w', **pad)
        ttk.Entry(frm, textvariable=self.var_target, width=100).grid(row=1, column=1, columnspan=2, sticky='we', **pad)
        ttk.Label(frm, text='课程链接').grid(row=2, column=0, sticky='w', **pad)
        ttk.Entry(frm, textvariable=self.var_url, width=100).grid(row=2, column=1, columnspan=2, sticky='we', **pad)
        ttk.Label(frm, text='Cookie 填 _educoder_session 所在的那一整段（含 autologin_trustie）', foreground='#888').grid(
            row=3, column=0, columnspan=3, sticky='w', **pad)

        frm_btn = ttk.Frame(self.root)
        frm_btn.pack(fill='x', padx=10, pady=6)
        self.btn_run = ttk.Button(frm_btn, text='开始执行（导出并补全）', command=self._start)
        self.btn_run.pack(side='left')

        frm_log = ttk.LabelFrame(self.root, text='日志')
        frm_log.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.txt_log = tk.Text(frm_log, height=16, wrap='word', state='disabled')
        slog = ttk.Scrollbar(frm_log, orient='vertical', command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=slog.set)
        self.txt_log.pack(side='left', fill='both', expand=True)
        slog.pack(side='right', fill='y')

    def log(self, msg: str):
        self.txt_log.configure(state='normal')
        self.txt_log.insert('end', msg + '\n')
        self.txt_log.see('end')
        self.txt_log.configure(state='disabled')

    # ---------- 队列轮询 ----------
    def _post(self, item):
        self.q.put(item)

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == 'log':
                    self.log(item[1])
                elif kind == 'busy':
                    self.busy = True
                    self.btn_run.configure(state='disabled')
                elif kind == 'done':
                    self.busy = False
                    self.btn_run.configure(state='normal')
                    self.log(item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # ---------- 执行 ----------
    def _start(self):
        if self.busy:
            return
        ac = self.var_answer.get().strip()
        tc = self.var_target.get().strip()
        url = self.var_url.get().strip()
        if not (ac and tc and url):
            messagebox.showwarning('提示', '请填全：答案账号 Cookie、目标账号 Cookie、课程链接。')
            return
        self._post(('busy',))
        self.log('开始执行…')
        threading.Thread(target=self._worker, args=(ac, tc, url), daemon=True).start()

    def _worker(self, ac, tc, url):
        emit = lambda m: self._post(('log', m))
        try:
            asyncio.run(run_copy(ac, tc, url, emit))
            self._post(('done', '执行完成。选择题补全已提交。'))
        except Exception as e:
            self._post(('log', f'✗ 执行失败：{e}'))
            self._post(('done', '执行失败，请检查 Cookie/课程链接/网络。'))


def main():
    root = tk.Tk()
    CopierApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
#（注：内容由AI生成）
