"""Build distribution archives for the DCC bridge plugins.

Outputs (in this directory):
  * splatpipe_bridge.zip  — Blender addon (Edit > Preferences > Add-ons > Install)
  * splatpipe_bridge.mzp  — 3ds Max installer (drag into a Max viewport)

Both are pure-stdlib — run from any Python interpreter.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

MZP_RUN = '''-- Splatpipe Bridge installer (drag this .mzp into a Max viewport)
local scriptsDir = (getDir #userScripts) + "/python/"
makeDir scriptsDir all:true
local pyDest = scriptsDir + "splatpipe_bridge.py"
copyFile (mzpPath + "/splatpipe_bridge.py") pyDest
python.execute "import sys, importlib; sys.path.insert(0, r'" + scriptsDir + "'); import splatpipe_bridge; importlib.reload(splatpipe_bridge); splatpipe_bridge.register_max_macro(); splatpipe_bridge.open_dialog()"
messageBox "Splatpipe Bridge installed!\\n\\nA dialog has opened, and a Splatpipe Bridge macro has been registered.\\nFind it in Customize > Toolbars > Category 'Splatpipe' to add a button." title:"Splatpipe Bridge"
'''


def build_blender_zip() -> Path:
    out = HERE / "splatpipe_bridge.zip"
    if out.exists():
        out.unlink()
    src = HERE / "blender" / "__init__.py"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src, arcname="splatpipe_bridge/__init__.py")
    return out


def build_max_mzp() -> Path:
    out = HERE / "splatpipe_bridge.mzp"
    if out.exists():
        out.unlink()
    src = HERE / "max" / "splatpipe_bridge.py"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src, arcname="splatpipe_bridge.py")
        zf.writestr("mzp.run", MZP_RUN)
    return out


if __name__ == "__main__":
    zip_path = build_blender_zip()
    mzp_path = build_max_mzp()
    print(f"built: {zip_path}  ({os.path.getsize(zip_path)} bytes)")
    print(f"built: {mzp_path}  ({os.path.getsize(mzp_path)} bytes)")
