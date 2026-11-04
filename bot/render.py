"""Escribe el YAML generado y renderiza el PDF (misma convención que render.ps1),
pero llamando directo al python del venv del proyecto en vez de invocar PowerShell.

El render corre en un directorio temporal propio (no en la raíz del proyecto), así dos
renders simultáneos — p. ej. dos usuarios de la web — no se pisan los archivos intermedios."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bot.config import PROCESADOS_DIR, PROJECT_ROOT, YAML_DIR

# Plantillas que reemplazan a las del tema de rendercv (p. ej. el encabezado con `headline`, que sb2nov no muestra).
_PLANTILLAS = PROJECT_ROOT / "bot" / "templates"

_VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def render_cv(
    yaml_content: str,
    angulo: str,
    empresa: str,
    yaml_dir: Path = YAML_DIR,
    pdf_dir: Path = PROCESADOS_DIR,
    prefijo: str = "Samuel_Prado",
) -> Path:
    """Devuelve la ruta del PDF final en pdf_dir; el YAML renderizado queda en yaml_dir."""
    yaml_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    nombre_base = f"{angulo}_{empresa}"
    nombre_pdf = f"{prefijo}_{empresa}_CV.pdf"
    python_exe = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable

    with tempfile.TemporaryDirectory(prefix="rendercv_") as tmp:
        tmp_dir = Path(tmp)
        shutil.copytree(_PLANTILLAS, tmp_dir, dirs_exist_ok=True)  # rendercv busca primero en el cwd
        yaml_path = tmp_dir / f"{nombre_base}.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")
        pdf_tmp = tmp_dir / nombre_pdf

        resultado = subprocess.run(
            [python_exe, "-m", "rendercv", "render", str(yaml_path), "--pdf-path", str(pdf_tmp)],
            cwd=tmp_dir,
            # En Vercel solo /tmp es escribible: typst/rendercv cachean en el HOME.
            env={**os.environ, "HOME": tempfile.gettempdir(), "XDG_CACHE_HOME": tempfile.gettempdir()} if os.environ.get("VERCEL") else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if not pdf_tmp.exists():
            raise RuntimeError(
                f"rendercv no generó el PDF.\nstdout:\n{resultado.stdout}\nstderr:\n{resultado.stderr}"
            )

        pdf_final = pdf_dir / nombre_pdf
        shutil.move(str(pdf_tmp), pdf_final)
        shutil.move(str(yaml_path), yaml_dir / yaml_path.name)

    return pdf_final
