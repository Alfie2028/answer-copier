# -*- coding: utf-8 -*-
"""
头歌(EduCoder) 图文作业一键提交 / 拉取 图形化工具
可迁移板块：填入答案账号cookie、目标账号cookie、课程图文作业链接、本地答案根文件夹，
先"列出作业"（勾选想处理的作业），再按需"拉取答案"或"一键提交"。
提交前会写入作业描述（默认"见附件"，系统要求输入框非空）。
依赖：playwright、requests、tkinter(内置)
"""
import os
import sys
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext

try:
    import common_homework as ch
except ImportError:
    ch = None

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

DEFAULT_COURSE = ''  # 在 GUI 中填入课程图文作业链接，形如 https://w.educoder.net/classrooms/{课堂code}/common_homework


class ScrollableChecklist(tk.Frame):
    """可滚动的多选列表（作业勾选）。"""

    def __init__(self, master, height=9):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=height * 26)
        self.vsb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas)
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.vsb.pack(side='right', fill='y')

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()

    def add(self, text, var):
        cb = tk.Checkbutton(self.inner, text=text, variable=var, anchor='w',
                            justify='left', wraplength=760)
        cb.pack(fill='x', anchor='w')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('头歌图文作业 一键提交/拉取 工具')
        self.geometry('920x760')
        self.q = queue.Queue()
        self.ans_cookie = tk.StringVar()
        self.tar_cookie = tk.StringVar()
        self.course_url = tk.StringVar(value=DEFAULT_COURSE)
        self.answers_root = tk.StringVar()
        self.ans_username = tk.StringVar()
        self.submit_desc = tk.StringVar(value='见附件')
        self.job_vars = {}
        self.job_items = []
        self._busy = False
        self._build_ui()
        self.after(120, self._drain)

    def _build_ui(self):
        pad = {'padx': 10, 'pady': 4}
        top = ttk.Frame(self)
        top.pack(fill='x', **pad)
        ttk.Label(top, text='图文作业一键提交 / 拉取 工具', font=('微软雅黑', 13, 'bold')).pack(side='left')
        ttk.Label(top, text='(答案账号拉取 → 本地修改 → 目标账号一键提交)', foreground='#888').pack(side='right')

        f = ttk.Frame(self)
        f.pack(fill='x', **pad)
        ttk.Label(f, text='答案账号 cookie').grid(row=0, column=0, sticky='w')
        ttk.Entry(f, textvariable=self.ans_cookie, width=110).grid(row=0, column=1, sticky='we', pady=2)
        ttk.Label(f, text='目标账号 cookie').grid(row=1, column=0, sticky='w')
        ttk.Entry(f, textvariable=self.tar_cookie, width=110).grid(row=1, column=1, sticky='we', pady=2)
        ttk.Label(f, text='课程图文作业链接').grid(row=2, column=0, sticky='w')
        ttk.Entry(f, textvariable=self.course_url, width=110).grid(row=2, column=1, sticky='we', pady=2)
        ttk.Label(f, text='本地答案根文件夹').grid(row=3, column=0, sticky='w')
        row3 = ttk.Frame(f)
        row3.grid(row=3, column=1, sticky='we', pady=2)
        ttk.Entry(row3, textvariable=self.answers_root, width=100).pack(side='left', fill='x', expand=True)
        ttk.Button(row3, text='浏览…', command=self._pick_dir).pack(side='left', padx=4)
        ttk.Label(f, text='提交描述').grid(row=4, column=0, sticky='w')
        ttk.Entry(f, textvariable=self.submit_desc, width=110).grid(row=4, column=1, sticky='we', pady=2)
        ttk.Label(f, text='答案账号用户名').grid(row=5, column=0, sticky='w')
        ttk.Entry(f, textvariable=self.ans_username, width=110).grid(row=5, column=1, sticky='we', pady=2)
        f.columnconfigure(1, weight=1)

        hint = ttk.Frame(self)
        hint.pack(fill='x', **pad)
        ttk.Label(hint, foreground='#666', wraplength=880, justify='left',
                  text='步骤：1)点「列出作业」加载本课程全部图文作业并勾选想处理的项（默认全选）；'
                       '2)「拉取答案」用答案账号把勾选作业的文件下载到「根文件夹/作业名/」；'
                       '3)本地改好后「一键提交」用目标账号上传并提交（会先写入"提交描述"，输入框非空）。').pack(anchor='w')

        btns = ttk.Frame(self)
        btns.pack(fill='x', **pad)
        ttk.Button(btns, text='列出作业', command=self.on_list).pack(side='left', padx=4)
        ttk.Button(btns, text='全选', command=self._check_all).pack(side='left', padx=2)
        ttk.Button(btns, text='全不选', command=self._check_none).pack(side='left', padx=2)
        ttk.Button(btns, text='拉取答案', command=self.on_fetch).pack(side='left', padx=4)
        ttk.Button(btns, text='一键提交', command=self.on_submit).pack(side='left', padx=4)

        listf = ttk.LabelFrame(self, text=' 作业列表（勾选要处理的项） ')
        listf.pack(fill='x', **pad)
        self.checklist = ScrollableChecklist(listf, height=7)
        self.checklist.pack(fill='x', padx=6, pady=4)

        logf = ttk.Frame(self)
        logf.pack(fill='both', expand=True, **pad)
        self.log_box = scrolledtext.ScrolledText(logf, height=13, font=('Consolas', 10))
        self.log_box.pack(fill='both', expand=True)

        self.log('工具就绪。填入两个账号 cookie 与课程链接，点「列出作业」后按需勾选，再拉取/提交。')

    def _pick_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.answers_root.set(d)

    def log(self, msg):
        self.log_box.insert('end', str(msg) + '\n')
        self.log_box.see('end')

    def _drain(self):
        try:
            while True:
                self.log(self.q.get_nowait())
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _require(self):
        if ch is None:
            self.q.put('[错误] 缺少 common_homework.py（与本工具同目录）')
            return False
        if not self.ans_cookie.get() and not self.tar_cookie.get():
            self.q.put('[错误] 请至少填答案账号或目标账号 cookie')
            return False
        if not self.course_url.get().strip():
            self.q.put('[错误] 请填课程图文作业链接')
            return False
        return True

    def _selected_ids(self):
        return {i for i, v in self.job_vars.items() if v.get()}

    def _check_all(self):
        for v in self.job_vars.values():
            v.set(True)

    def _check_none(self):
        for v in self.job_vars.values():
            v.set(False)

    def _begin(self):
        if self._busy:
            self.q.put('[提示] 上一项仍在运行（浏览器占用中），请等它完成后再点。')
            return False
        self._busy = True
        return True

    def _end(self):
        self._busy = False

    def on_list(self):
        if not self._require():
            return
        if not self._begin():
            return
        threading.Thread(target=self._list, daemon=True).start()

    def _list(self):
        try:
            self.q.put('[列作业] 加载中…')
            r = ch.list_homeworks(self.tar_cookie.get() or self.ans_cookie.get(), self.course_url.get().strip())
            if isinstance(r, str):
                self.q.put(f'[列作业] {r}')
                return
            self.job_items = r
            self.job_vars = {}
            self.after(0, self._refresh_list)
            self.q.put(f'[列作业] 共 {len(r)} 个图文作业，已全部勾选：')
        finally:
            self._end()

    def _refresh_list(self):
        self.checklist.clear()
        for i, n in self.job_items:
            self.job_vars[i] = tk.BooleanVar(value=True)
            self.checklist.add(f'{n}  (id={i})', self.job_vars[i])

    def on_fetch(self):
        if not self._require():
            return
        if not self.ans_cookie.get():
            self.q.put('[错误] 拉取需要答案账号 cookie')
            return
        if not self.answers_root.get():
            self.q.put('[错误] 请选择本地答案根文件夹')
            return
        sel = self._selected_ids()
        if not sel:
            self.q.put('[错误] 未勾选任何作业')
            return
        if not self._begin():
            return
        threading.Thread(target=self._fetch, args=(sel,), daemon=True).start()

    def _fetch(self, sel):
        try:
            root = self.answers_root.get()
            os.makedirs(root, exist_ok=True)
            self.q.put(f'[拉取] 用答案账号(纯 requests)拉取勾选的 {len(sel)} 个作业…')
            r = ch.fetch_course_requests(self.ans_cookie.get(), self.ans_username.get().strip(),
                                         self.course_url.get().strip(), root, only_ids=sel)
            if isinstance(r, str):
                self.q.put(f'[拉取] {r}')
                return
            for name, n, msg in r:
                self.q.put(f'  · {name}: {msg} (文件数 {n})')
            self.q.put('[拉取] 完成(纯 requests，无浏览器)，文件已存到各作业名子文件夹。')
        finally:
            self._end()

    def on_submit(self):
        if not self._require():
            return
        if not self.tar_cookie.get():
            self.q.put('[错误] 一键提交需要目标账号 cookie')
            return
        if not self.answers_root.get():
            self.q.put('[错误] 请选择本地答案根文件夹')
            return
        sel = self._selected_ids()
        if not sel:
            self.q.put('[错误] 未勾选任何作业')
            return
        if not self._begin():
            return
        threading.Thread(target=self._submit, args=(sel,), daemon=True).start()

    def _submit(self, sel):
        try:
            root = self.answers_root.get()
            desc = self.submit_desc.get().strip() or '见附件'
            self.q.put(f'[提交] 用目标账号快速提交勾选的 {len(sel)} 个作业（描述="{desc}"）…')
            r = ch.submit_course_fast(self.tar_cookie.get(), self.course_url.get().strip(), root,
                                      description=desc, only_ids=sel)
            if isinstance(r, str):
                self.q.put(f'[提交] {r}')
                return
            for name, ok, msg in r:
                self.q.put(f'  · {name}: {"成功" if ok else "失败"} — {msg}')
            self.q.put('[提交] 全部结束，请到平台核对各作业提交状态。')
        finally:
            self._end()


if __name__ == '__main__':
    App().mainloop()
