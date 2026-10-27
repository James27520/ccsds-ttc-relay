"""Portable tool discovery: explicit directory, environment, then PATH."""
import os, shutil
from pathlib import Path

def tool_directory(explicit, env_name, executable):
    value=explicit or os.environ.get(env_name)
    if value:
        directory=Path(value).expanduser().resolve()
        if not (directory/executable).is_file():
            raise SystemExit(f'{executable} not found in {directory}')
        return directory
    found=shutil.which(executable)
    if found:return Path(found).resolve().parent
    raise SystemExit(f'Supply the tool bin directory explicitly or set {env_name}; {executable} is not on PATH')
