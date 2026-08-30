"""Bundle tkinterdnd2's Tcl scripts and native TkDnD libraries."""

from PyInstaller.utils.hooks import collect_data_files


datas = collect_data_files("tkinterdnd2")
