# PyInstaller spec for tradingbot-core (bot + HTTP API in one executable).
# Build from the repository root:  pyinstaller packaging/tradingbot-core.spec
# Output: dist/tradingbot-core/ (one-folder build: starts faster than --onefile
# and is what the desktop installer copies into its resources).
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("api")
    + collect_submodules("execution")
    + ["main", "bot_engine", "config", "exchange_client", "logging_setup", "performance",
       "risk_manager", "state_manager", "strategy"]
)

a = Analysis(
    ["core_entry.py"],
    pathex=[".."],
    datas=collect_data_files("ccxt"),
    hiddenimports=hiddenimports,
    # The desktop app replaces the Streamlit dashboard; leaving it out saves ~150 MB.
    excludes=["streamlit", "plotly", "pyarrow", "pytest", "tkinter", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tradingbot-core",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="tradingbot-core", upx=False)
