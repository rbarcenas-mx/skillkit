#!/usr/bin/env python3
"""ci.execute — Execute a CI integration plan step by step with checkpoint and progress bar."""

import json, subprocess, sys, os, re, time
from datetime import datetime, timezone

sys.stderr.reconfigure(line_buffering=True)

CI_TASKS_FILE = os.environ.get('CI_TASKS_FILE', '')
WORKDIR = os.environ.get('WORKDIR', '.')
PROGRESS_FILE = '/tmp/opencode/ci_execute_progress.json'

os.chdir(WORKDIR)
os.makedirs('/tmp/opencode', exist_ok=True)

if not CI_TASKS_FILE or not os.path.exists(CI_TASKS_FILE):
    print(f"ERROR: Task file not found: {CI_TASKS_FILE}", file=sys.stderr)
    sys.exit(1)


# ── Parse tasks ────────────────────────────────────────────
def parse_tasks(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    header = {}
    for line in content.split('\n'):
        m = re.match(r'- \*\*(\w+)\*\*: (.+)', line)
        if m:
            header[m.group(1)] = m.group(2).strip()

    tasks = []
    pattern = (
        r'## (EX-\d+): (.+?)\n'
        r'- \*\*desc\*\*: (.+?)\n'
        r'- \*\*command\*\*:\n[ \t]*```\n(.*?)```\n'
        r'- \*\*rollback\*\*: (.+?)\n'
        r'- \*\*dangerous\*\*: (\w+)\n'
        r'- \*\*deps\*\*: \[(.*?)\]\n'
        r'- \*\*checkpoint\*\*: (\w+)'
    )
    for m in re.finditer(pattern, content, re.DOTALL):
        deps_raw = m.group(7).strip()
        deps = [d.strip().strip('"').strip("'") for d in deps_raw.split(',') if d.strip()] if deps_raw else []
        tasks.append({
            'id': m.group(1),
            'title': m.group(2).strip(),
            'desc': m.group(3).strip(),
            'command': m.group(4).strip(),
            'rollback': m.group(5).strip(),
            'dangerous': m.group(6).strip().lower() == 'true',
            'deps': deps,
            'checkpoint': m.group(8).strip().lower() == 'true',
        })

    exec_log = []
    log_section = re.search(r'## Execution Log\n(.*?)(?:\n##|\Z)', content, re.DOTALL)
    if log_section:
        for line in log_section.group(1).strip().split('\n'):
            line = line.strip()
            if line and re.match(r'(📌 )?(EX-\d+)', line):
                exec_log.append(line)

    return header, tasks, exec_log, content


header, tasks, exec_log, original_content = parse_tasks(CI_TASKS_FILE)
total = len(tasks)


# ── Checkpoint ──────────────────────────────────────────────
def load_checkpoint():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_checkpoint(state):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(state, f)


# ── Progress bar ───────────────────────────────────────────
def progress_bar(done, total):
    pct = int((done / total) * 100) if total > 0 else 0
    filled = int(30 * done / total) if total > 0 else 0
    _bar = '\u2588' * filled + '\u2591' * (30 - filled)
    sys.stderr.write(f'\r[{_bar}] {pct}% ({done}/{total})   ')
    sys.stderr.flush()


done_count = len([e for e in exec_log if '\u2705' in e or '\u21a9\ufe0f' in e])
progress_bar(done_count, total)


# ── Execution log helpers ──────────────────────────────────
def append_log(entry):
    exec_log.append(entry)
    with open(CI_TASKS_FILE, 'a', encoding='utf-8') as f:
        f.write(entry + '\n')


def log_success(task_id, desc, duration, commit_hash, checkpoint):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    prefix = '\U0001f4cc ' if checkpoint else ''
    entry = f'{prefix}{task_id} {ts} \u2705 `{commit_hash}` {desc}' if commit_hash else f'{prefix}{task_id} {ts} \u2705 {desc}'
    append_log(entry)


def log_failure(task_id, desc, duration, error):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    entry = f'{task_id} {ts} \u274c ({duration:.1f}s) {desc} — {error[:500]}'
    append_log(entry)


def log_skip(task_id, desc):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    entry = f'{task_id} {ts} \u23ed\ufe0f {desc}'
    append_log(entry)


def log_rollback(task_id, desc, rollback_cmd):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    entry = f'{task_id} {ts} \u21a9\ufe0f ROLLBACK {rollback_cmd}'
    append_log(entry)


# ── Git helpers ─────────────────────────────────────────────
def get_commit_hash():
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def get_branch():
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip() if result.returncode == 0 else "main"


def get_tracked_files_count():
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, timeout=10
    )
    return len(result.stdout.strip().split('\n')) if result.returncode == 0 and result.stdout.strip() else 0


def get_all_commit_hashes():
    hashes = []
    for entry in exec_log:
        m = re.search(r'`([a-f0-9]+)`', entry)
        if m and '\u2705' in entry:
            hashes.append(m.group(1))
    return hashes


# ── Gitignore validation ───────────────────────────────────
def validate_gitignore():
    required = ['^.env$', '^.env.', '^node_modules/$', '^dist/$']
    missing = []
    gitignore_path = os.path.join(WORKDIR, '.gitignore')
    if not os.path.exists(gitignore_path):
        return required  # all missing

    with open(gitignore_path, 'r') as f:
        content = f.read()

    for pattern in required:
        found = False
        for line in content.split('\n'):
            line = line.strip()
            if line == pattern.replace('^', '').replace('$', '') or line == pattern:
                found = True
                break
            if pattern == '^.env.' and ('.env.' in line or line.startswith('.env.')):
                found = True
                break
        if not found:
            missing.append(pattern)
    return missing


# ── Main execution loop ────────────────────────────────────
def main():
    failed = 0
    skipped = 0
    completed = done_count

    print(f"\n{'═'*50}", file=sys.stderr)
    print(f"  CI Plan: {os.path.basename(CI_TASKS_FILE)}", file=sys.stderr)
    print(f"  Total tasks: {total}", file=sys.stderr)
    print(f"  Already done: {completed}", file=sys.stderr)
    print(f"{'─'*50}", file=sys.stderr)

    # Validate gitignore
    missing = validate_gitignore()
    if missing:
        print(f"  ⚠️  .gitignore missing patterns: {', '.join(missing)}", file=sys.stderr)
        print(f"  Recommended to add them before continuing.", file=sys.stderr)
        print(f"{'─'*50}", file=sys.stderr)

    cp = load_checkpoint()

    for task in tasks:
        tid = task['id']

        # Check deps
        deps = task.get('deps', [])
        if deps:
            for dep in deps:
                dep_ok = any(dep in e and '\u2705' in e for e in exec_log)
                if not dep_ok:
                    dep_in_plan = any(t['id'] == dep for t in tasks)
                    dep_failed = any(dep in e and '\u274c' in e for e in exec_log)
                    if dep_in_plan and dep_failed:
                        print(f"\n  ⚠️  {tid} depends on {dep} (failed).", file=sys.stderr)
                    elif dep_in_plan:
                        print(f"\n  ⚠️  {tid} depends on {dep} (not yet executed).", file=sys.stderr)
                    else:
                        print(f"\n  ⚠️  {tid} depends on {dep} (outside plan).", file=sys.stderr)
                    continue

        # Already completed
        already_done = any(tid in e and '\u2705' in e for e in exec_log)
        if already_done:
            print(f"\n⏭️  {tid}: {task['desc']} — already done", file=sys.stderr)
            continue

        # Task display
        danger_label = "⚠️ DANGEROUS" if task['dangerous'] else ""
        checkpoint_label = "\U0001f4cc save point" if task['checkpoint'] else "no checkpoint"
        deps_label = f"deps: {task['deps']}" if task['deps'] else "deps: none"
        print(f"\n{'═'*50}", file=sys.stderr)
        print(f"  {tid}: {task['desc']} {danger_label}", file=sys.stderr)
        print(f"  {checkpoint_label}  |  {deps_label}", file=sys.stderr)
        print(f"  Command:", file=sys.stderr)
        for line in task['command'].strip().split('\n'):
            print(f"    {line.strip()}", file=sys.stderr)
        if task['rollback'] and task['rollback'] != 'N/A':
            print(f"  Rollback: {task['rollback']}", file=sys.stderr)
        print(f"{'─'*50}", file=sys.stderr)

        # User confirmation (via stdin, or environment override)
        auto_confirm = os.environ.get('CI_AUTO_CONFIRM', '0') == '1'

        # Mandatory confirmation before git push
        if 'git push' in task['command'] and not auto_confirm:
            print(f"  🚀 This task contains 'git push'.", file=sys.stderr)
            print(f"  Push to remote? (y/N): ", end='', flush=True, file=sys.stderr)
            try:
                answer = sys.stdin.readline().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = 'n'
            if answer != 'y':
                print(f"  ⏭️  Push cancelled by user.", file=sys.stderr)
                log_skip(tid, task['desc'] + ' (push cancelled)')
                skipped += 1
                continue

        if not auto_confirm:
            print(f"  ⏳ Running...", file=sys.stderr)

        t0 = time.time()

        try:
            result = subprocess.run(
                task['command'],
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=WORKDIR
            )
            duration = time.time() - t0

            if result.returncode == 0:
                commit_hash = get_commit_hash() if 'git commit' in task['command'] else ""
                log_success(tid, task['desc'], duration, commit_hash, task['checkpoint'])
                completed += 1
                progress_bar(completed, total)
                save_checkpoint({'last_done': tid, 'completed': completed, 'timestamp': datetime.now(timezone.utc).isoformat()})
                if commit_hash:
                    print(f"  ✅ {tid} → `{commit_hash}` ({duration:.1f}s)", file=sys.stderr)
                else:
                    print(f"  ✅ {tid} ({duration:.1f}s)", file=sys.stderr)
            else:
                error_msg = result.stderr[:300] or result.stdout[:300]
                log_failure(tid, task['desc'], duration, error_msg)
                failed += 1
                print(f"\n  ❌ Failed (exit={result.returncode}): {error_msg[:200]}", file=sys.stderr)
                print(f"  The failure has been logged. Fix the error and re-run ci.execute.", file=sys.stderr)

        except subprocess.TimeoutExpired:
            duration = time.time() - t0
            log_failure(tid, task['desc'], duration, "TIMEOUT")
            failed += 1
            print(f"  ❌ Timeout (>300s)", file=sys.stderr)

    # ── Final summary ──────────────────────────────────────
    print(f"\n{'═'*50}", file=sys.stderr)
    print(f"  Execution summary — {os.path.basename(CI_TASKS_FILE)}", file=sys.stderr)
    print(f"{'─'*50}", file=sys.stderr)
    print(f"  Total tasks:     {total}", file=sys.stderr)
    print(f"  Completed:       {completed}  ✅", file=sys.stderr)
    print(f"  Failed:          {failed}  ❌", file=sys.stderr)
    print(f"  Skipped:         {skipped}  ⏭️", file=sys.stderr)
    print(f"{'─'*50}", file=sys.stderr)
    progress_bar(total, total)
    sys.stderr.write('\n')
    sys.stderr.flush()

    branch = get_branch()
    commits = get_all_commit_hashes()
    commit_chain = ' → '.join(commits) if commits else '(none)'
    file_count = get_tracked_files_count()

    summary = (
        f"\n### Final summary\n\n"
        f"**Status:** {'✅ Completed' if failed == 0 and skipped == 0 else '⚠️ With issues'} — {completed}/{total} tasks succeeded\n"
        f"**Branch:** `{branch}`\n"
        f"**Commits:** {commit_chain}\n"
        f"**Tracked files:** {file_count}\n"
    )
    append_log(summary)
    print(f"  Branch: `{branch}`  |  Commits: {commit_chain}", file=sys.stderr)
    print(f"  Tracked files: {file_count}", file=sys.stderr)
    print(f"{'═'*50}", file=sys.stderr)

    # Final JSON summary to stdout
    result = {
        "status": "ok" if failed == 0 else "partial",
        "plan": os.path.basename(CI_TASKS_FILE),
        "total": total,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "branch": branch,
        "commits": commits,
        "tracked_files": file_count,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
