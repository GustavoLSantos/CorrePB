"""
Runner para executar os scrapers em data_collection.
Descobre arquivos scraper_*.py no mesmo diretório e executa cada um como um subprocesso Python.
Uso: python data_collection/run_all_scrapers.py [--scripts scraper_brasilquecorre.py scraper_smcrono.py] [--parallel] [--no-capture]
"""

import os
import sys
import glob
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(__file__)
THIS_BASENAME = os.path.basename(__file__)

# Descobre scripts scraper_*.py no diretório, excluindo este runner
_discovered = sorted([os.path.basename(p) for p in glob.glob(os.path.join(HERE, 'scraper_*.py')) if os.path.basename(p) != THIS_BASENAME])
# Prioriza scrapers conhecidos
_priority = ['scraper_brasilquecorre.py', 'scraper_smcrono.py']
_scripts = []
for p in _priority:
    if p in _discovered:
        _scripts.append(p)
        _discovered.remove(p)
_scripts.extend(_discovered)


def run_script(script_name, capture_output=True):
    script_path = os.path.join(HERE, script_name)
    if not os.path.exists(script_path):
        return script_name, 127, '', f'Script not found: {script_path}'
    cmd = [sys.executable, script_path]
    try:
        if capture_output:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            return script_name, proc.returncode, proc.stdout or '', proc.stderr or ''
        else:
            proc = subprocess.run(cmd)
            return script_name, proc.returncode, '', ''
    except Exception as e:
        return script_name, 1, '', str(e)


def main():
    parser = argparse.ArgumentParser(description='Run scraper_*.py scripts located in data_collection directory')
    parser.add_argument('--scripts', nargs='*', help='Basename(s) of scraper scripts to run. Defaults to discovered scrapers.')
    parser.add_argument('--parallel', action='store_true', help='Run scrapers in parallel')
    parser.add_argument('--no-capture', dest='capture', action='store_false', help='Do not capture stdout/stderr (streams to console)')
    args = parser.parse_args()

    to_run = args.scripts if args.scripts else _scripts
    norm = []
    for s in to_run:
        if not s.endswith('.py'):
            s = s + '.py'
        if s in _scripts:
            norm.append(s)
        else:
            print(f"[WARN] script {s} not found among discovered scrapers; skipping.")

    if not norm:
        print('No scripts to run; exiting.')
        return 2

    results = []
    if args.parallel:
        max_workers = min(4, len(norm))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(run_script, s, args.capture): s for s in norm}
            for fut in as_completed(futures):
                results.append(fut.result())
    else:
        for s in norm:
            results.append(run_script(s, args.capture))

    # resumo
    print('\nRun summary:')
    for name, code, out, err in results:
        status = 'OK' if code == 0 else f'FAIL({code})'
        print(f"- {name}: {status}")
        if args.capture:
            if out:
                print(f"--- stdout ({name}):\n{out.strip()}")
            if err:
                print(f"--- stderr ({name}):\n{err.strip()}", file=sys.stderr)

    any_fail = any(code != 0 for (_, code, _, _) in results)
    sys.exit(1 if any_fail else 0)


if __name__ == '__main__':
    main()
