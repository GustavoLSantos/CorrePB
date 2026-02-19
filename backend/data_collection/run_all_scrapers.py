"""
Runner para executar os scrapers em data_collection.
Descobre arquivos scraper_*.py no mesmo diretório e executa cada um como um subprocesso Python.
Uso: python data_collection/run_all_scrapers.py [--scripts scraper_brasilquecorre.py scraper_smcrono.py] [--parallel] [--no-capture]
"""

import os
import sys
import glob
import subprocess

HERE = os.path.dirname(__file__)
THIS_BASENAME = os.path.basename(__file__)

# Descobre scripts scraper_*.py no diretório, excluindo este runner
_discovered = sorted([os.path.basename(p) for p in glob.glob(os.path.join(HERE, 'scraper_*.py')) if os.path.basename(p) != THIS_BASENAME])
# Lista de scrapers a ignorar explicitamente (não prontos)
_ignored = {'scraper_brasilcorrida.py'}
# Prioriza scrapers conhecidos
_priority = ['scraper_brasilquecorre.py', 'scraper_smcrono.py']
_scripts = []
for p in _priority:
    if p in _discovered and p not in _ignored:
        _scripts.append(p)
        _discovered.remove(p)
# adiciona restantes exceto ignorados
_scripts.extend([p for p in _discovered if p not in _ignored])


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
    to_run = _scripts
    if not to_run:
        print('No scripts to run; exiting.')
        return 2

    results = []
    for s in to_run:
        print(f"\nRunning {s} ...")
        name, code, out, err = run_script(s, capture_output=False)
        results.append((name, code, out, err))

    # summary
    print('\nRun summary:')
    for name, code, out, err in results:
        status = 'OK' if code == 0 else f'FAIL({code})'
        print(f"- {name}: {status}")

    any_fail = any(code != 0 for (_, code, _, _) in results)
    sys.exit(1 if any_fail else 0)


if __name__ == '__main__':
    main()
