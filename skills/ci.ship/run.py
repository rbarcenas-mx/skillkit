#!/usr/bin/env python3
"""ci.ship executor — pre-flight, push, and CI wait operations.

Usage:
    CI_MODE=preflight python3 run.py
    CI_MODE=push python3 run.py
    CI_MODE=ci-wait CI_TIMEOUT=300 python3 run.py

Environment:
    WORKDIR: project root (default: cwd)
    CI_MODE: preflight | push | ci-wait
    CI_TIMEOUT: max seconds to wait for CI (default: 300)
"""

import os
import subprocess
import sys
import json
import time

WORKDIR = os.environ.get('WORKDIR', os.getcwd())
MODE = os.environ.get('CI_MODE', 'preflight')
CI_TIMEOUT = int(os.environ.get('CI_TIMEOUT', '300'))


def progress_bar(done, total):
    pct = int((done / total) * 100) if total > 0 else 0
    filled = int(30 * done / total) if total > 0 else 0
    bar = chr(9608) * filled + chr(9617) * (30 - filled)
    sys.stderr.write(f'\r[{bar}] {pct}% ({done}/{total})   ')
    sys.stderr.flush()


def run_command(cmd, cwd=None):
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd or WORKDIR
    )
    return {
        'returncode': result.returncode,
        'stdout': result.stdout,
        'stderr': result.stderr,
    }


def run_preflight():
    checks_config = [
        ('lint', 'npm run lint 2>&1'),
        ('build', 'npm run build 2>&1'),
        ('test', 'npm test 2>&1'),
    ]
    total = len(checks_config)
    results = []

    for i, (name, cmd) in enumerate(checks_config):
        progress_bar(i, total)
        sys.stderr.write(f'\n  [{name}] Running...\n')
        sys.stderr.flush()

        out = run_command(cmd)
        passed = out['returncode'] == 0
        stdout_tail = out['stdout'][-600:] if out['stdout'] else ''
        stderr_tail = out['stderr'][-600:] if out['stderr'] else ''

        results.append({
            'name': name,
            'status': 'passed' if passed else 'failed',
            'returncode': out['returncode'],
            'stdout_tail': stdout_tail,
            'stderr_tail': stderr_tail,
        })

        if passed:
            sys.stderr.write(f'  [{name}] PASSED\n')
        else:
            sys.stderr.write(f'  [{name}] FAILED (exit {out["returncode"]})\n')
        sys.stderr.flush()

    progress_bar(total, total)
    sys.stderr.write('\n')
    sys.stderr.flush()

    return {'mode': 'preflight', 'checks': results}


def run_push():
    sys.stderr.write('\n  [push] Executing git push origin main...\n')
    sys.stderr.flush()

    out = run_command('git push origin main 2>&1')
    success = out['returncode'] == 0

    combined = out['stdout'] + out['stderr']

    sys.stderr.write(f'  [push] {"SUCCESS" if success else "FAILED"}\n')
    sys.stderr.flush()

    return {
        'mode': 'push',
        'status': 'success' if success else 'failed',
        'returncode': out['returncode'],
        'output': combined,
    }


def run_ci_wait():
    sys.stderr.write('\n  [ci] Waiting for GitHub Actions to complete...\n')
    sys.stderr.flush()

    start = time.time()
    poll_interval = 15
    elapsed = 0

    while elapsed < CI_TIMEOUT:
        out = run_command(
            'gh run list --limit 1 --json conclusion,status,headBranch,databaseId,createdAt,updatedAt,displayTitle 2>&1',
        )

        if out['returncode'] != 0:
            sys.stderr.write(f'  [ci] gh CLI error: {out["stderr"][:200]}\n')
            sys.stderr.flush()
            time.sleep(poll_interval)
            elapsed = time.time() - start
            continue

        try:
            runs = json.loads(out['stdout'])
        except json.JSONDecodeError:
            sys.stderr.write('  [ci] Could not parse gh output, retrying...\n')
            sys.stderr.flush()
            time.sleep(poll_interval)
            elapsed = time.time() - start
            continue

        if not runs:
            sys.stderr.write('  [ci] No CI runs found, waiting...\n')
            sys.stderr.flush()
            time.sleep(poll_interval)
            elapsed = time.time() - start
            continue

        run_data = runs[0]
        status = run_data.get('status', 'unknown')
        conclusion = run_data.get('conclusion', '')
        elapsed = time.time() - start

        mins = int(elapsed / 60)
        secs = int(elapsed % 60)
        sys.stderr.write(f'\r  [ci] Status: {status} | Conclusion: {conclusion} | Elapsed: {mins}m{secs}s')
        sys.stderr.flush()

        if status == 'completed':
            sys.stderr.write('\n')
            sys.stderr.flush()
            return {
                'mode': 'ci-wait',
                'status': conclusion,
                'elapsed_seconds': elapsed,
                'run_id': run_data.get('databaseId'),
                'title': run_data.get('displayTitle', ''),
            }

        time.sleep(poll_interval)

    sys.stderr.write(f'\n  [ci] TIMEOUT after {CI_TIMEOUT}s\n')
    sys.stderr.flush()
    return {
        'mode': 'ci-wait',
        'status': 'timeout',
        'elapsed_seconds': CI_TIMEOUT,
        'message': f'CI did not complete within {CI_TIMEOUT}s',
    }


def main():
    if MODE == 'preflight':
        result = run_preflight()
    elif MODE == 'push':
        result = run_push()
    elif MODE == 'ci-wait':
        result = run_ci_wait()
    else:
        result = {'error': f'Unknown CI_MODE: {MODE}'}

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
