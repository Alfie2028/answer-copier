"""把头歌课堂的已作答答案导出为 class-answers 格式（与 answers.json 一致）。

用法（在本项目目录、Windows 用 venv python）：
    .\.venv\Scripts\python.exe -m educoder_reminder.export --classroom 2i6ng7vp
    .\.venv\Scripts\python.exe -m educoder_reminder.export --classroom HCEAP94S --output out.json

说明：
- 选择题：从平台任务详情 choose_test_cases.test_sets[].actual_output 读取已提交答案，
  多选题（如 'ACD'）还原为 selected 数组。kind=choice，source=platform。
- 代码题：代码存储在远程 git 工作区，任务详情不含代码文本；当前无法从 API 可靠读取，
  导出为 kind=code、answered=false（answer 为空），需另行补充。
- 只读导出，不会提交或修改任何作业。
"""
import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .client import open_client
from .errors import CollectionError
from .submit import fetch_homework_rows, resolve_entry, walk_prev_to_head

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'answers_export.json'


def split_selected(raw):
    """把平台答案（'ACD' 或 'A,C,D'）还原成 selected 数组。"""
    s = str(raw or '').replace(' ', '').upper()
    if not s:
        return []
    if ',' in s:
        return [x for x in s.split(',') if x]
    return [x for x in list(s) if re.fullmatch(r'[A-Z]', x)]


async def export_experiment(client, hw):
    """导出一个实验（作业行）的全部关卡答案。"""
    shixun_id = hw.get('shixun_identifier')
    hw_id = hw.get('homework_id')
    name = hw.get('name') or ''
    entry = await resolve_entry(client, shixun_id, hw_id)
    if not entry:
        return {'name': name, 'levels': []}
    ordered, _ = await walk_prev_to_head(client, entry)
    levels = []
    for i, gid in enumerate(ordered):
        detail = await client.get(f'/api/tasks/{gid}.json', {}, strict_status=False)
        challenge = detail.get('challenge') or {}
        subject = (challenge.get('subject') or '').strip() or f'关卡{i + 1}'
        ctc = detail.get('choose_test_cases') or {}
        has_chooses = bool(detail.get('chooses')) or bool(ctc.get('challenge_chooses_count'))
        base = {'level_id': f'L{i + 1:03d}', 'position': i + 1, 'title': subject,
                'identifiers': [gid]}
        if has_chooses:
            rows = ctc.get('test_sets') or []
            outs = [t.get('actual_output') for t in rows if isinstance(t, dict)]
            if outs:
                answer = [{'number': n, 'selected': split_selected(o)} for n, o in enumerate(outs, 1)]
                levels.append({**base, 'kind': 'choice', 'answered': True,
                               'answer': answer, 'source': 'platform'})
            else:
                levels.append({**base, 'kind': 'choice', 'answered': False,
                               'answer': [], 'source': 'unknown'})
        else:
            # 代码题：任务详情不含代码文本，标记未读取，待补充。
            levels.append({**base, 'kind': 'code', 'answered': False,
                           'answer': {}, 'source': 'unknown'})
    return {'name': name, 'levels': levels}


def classroom_display_name(classroom):
    """优先用现有 answers.json 里的课堂名，否则退回 code。"""
    ref = ROOT / 'answers.json'
    if ref.exists():
        try:
            data = json.loads(ref.read_text(encoding='utf-8'))
            for c in data.get('classrooms', []):
                if c.get('code') == classroom:
                    return c.get('name') or classroom
        except (OSError, ValueError):
            pass
    return classroom


async def run(classroom, output):
    async with open_client() as client:
        rows = await fetch_homework_rows(client, classroom)
        experiments = []
        for hw in rows:
            try:
                exp = await export_experiment(client, hw)
            except CollectionError as exc:
                print(f'  ✗ 实验「{hw.get("name")}」导出失败：{exc}')
                continue
            experiments.append(exp)
            total = len(exp['levels'])
            choices = sum(1 for lv in exp['levels'] if lv['kind'] == 'choice')
            print(f'  ▸ {exp["name"]}: {total} 关（选择题 {choices}）')
        payload = {
            'version': 2,
            'kind': 'class-answers',
            'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'class': {'grade': '', 'name': '本机导出'},
            'classrooms': [{'name': classroom_display_name(classroom), 'code': classroom,
                            'experiments': experiments}],
        }
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        n_levels = sum(len(e['levels']) for e in experiments)
        n_choice = sum(1 for e in experiments for lv in e['levels'] if lv['kind'] == 'choice')
        n_ans = sum(1 for e in experiments for lv in e['levels']
                    if lv.get('kind') == 'choice' and lv.get('answered'))
        print(f'\n导出完成：{len(experiments)} 实验 / {n_levels} 关 '
              f'（选择题 {n_choice}，其中已读答案 {n_ans}）')
        print(f'输出：{output}')
        return payload


def main():
    parser = argparse.ArgumentParser(description='导出头歌课堂答案为 class-answers 格式（只读）')
    parser.add_argument('--classroom', required=True, help='课堂 code，如 2i6ng7vp')
    parser.add_argument('--output', default=str(DEFAULT_OUT), help='输出 JSON 路径')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.classroom, Path(args.output)))
    except CollectionError as exc:
        # 数据写入后，退出时会话校验异常不影响已生成的导出文件。
        out = Path(args.output)
        if out.exists() and out.stat().st_size > 0:
            print(f'警告：{exc}（导出文件已生成：{out}）')
        else:
            raise SystemExit(str(exc)) from None


if __name__ == '__main__':
    main()
