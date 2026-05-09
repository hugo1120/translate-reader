# Package Imports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将应用自身包从裸 `src.*` 迁移为 `translate_manga.*`，避免和 `vendor/Saber-Translator/src` 发生导入冲突。

**Architecture:** 采用标准 src-layout：应用代码位于 `src/translate_manga/`，根目录脚本和 `start_cli.bat` 显式把 `src/` 加入 Python 模块搜索路径。Saber 子进程/worker 内部脚本继续使用 vendor 自己的 `src.*` 导入，不在本阶段拆改 Saber 算法。

**Tech Stack:** Python 3.10+、pytest、Windows batch、Saber-Translator vendor。

---

### Task 1: 迁移保护测试

**Files:**
- Create: `tests/test_package_imports.py`
- Modify: `tests/conftest.py`

- [x] **Step 1: 写失败测试**

```python
def test_translate_manga_public_imports_work():
    from translate_manga.cli.service import run_batch_translation
    from translate_manga.core.pipeline.runtime import PipelineRuntime

    assert callable(run_batch_translation)
    assert PipelineRuntime.__name__ == "PipelineRuntime"
```

- [x] **Step 2: 确认 RED**

Run: `.venv310/Scripts/python.exe -m pytest tests/test_package_imports.py -q`

Expected: FAIL，提示 `ModuleNotFoundError: No module named 'translate_manga'`。

### Task 2: 应用包迁移

**Files:**
- Move: `src/cli` -> `src/translate_manga/cli`
- Move: `src/config` -> `src/translate_manga/config`
- Move: `src/core` -> `src/translate_manga/core`
- Move: `src/integrations` -> `src/translate_manga/integrations`
- Move: `src/__init__.py` -> `src/translate_manga/__init__.py`
- Modify: all moved application `.py` files

- [x] **Step 1: 建立新包目录并移动代码**

PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path "src/translate_manga"
Move-Item -LiteralPath "src/cli" -Destination "src/translate_manga/cli"
Move-Item -LiteralPath "src/config" -Destination "src/translate_manga/config"
Move-Item -LiteralPath "src/core" -Destination "src/translate_manga/core"
Move-Item -LiteralPath "src/integrations" -Destination "src/translate_manga/integrations"
Move-Item -LiteralPath "src/__init__.py" -Destination "src/translate_manga/__init__.py"
```

- [x] **Step 2: 更新应用内导入**

将 moved application files 中的宿主应用导入从：

```python
from src.config.settings import load_settings
from src.core.pipeline.runtime import PipelineRuntime
from src.integrations.saber_loader import run_saber_task
```

更新为：

```python
from translate_manga.config.settings import load_settings
from translate_manga.core.pipeline.runtime import PipelineRuntime
from translate_manga.integrations.saber_loader import run_saber_task
```

注意：`translate_manga/integrations/saber_loader.py` 内嵌 `_SCRIPTS` 和 `_WORKER_SCRIPT` 字符串里的 `from src.core...` 属于 vendor Saber 导入，必须保留。

### Task 3: 入口与测试同步

**Files:**
- Modify: `batch_translate.py`
- Modify: `run_batch_background.py`
- Modify: `start_cli.bat`
- Modify: `pytest.ini`
- Modify: `tests/**/*.py`

- [x] **Step 1: 根入口脚本加载 src-layout**

在 `batch_translate.py` 与 `run_batch_background.py` 的应用导入前加入：

```python
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
```

- [x] **Step 2: bat 入口加载 src-layout**

```bat
set "MENU_MODULE=translate_manga.cli.menu"
set "PYTHONPATH=%ROOT_DIR%src;%PYTHONPATH%"
```

- [x] **Step 3: pytest 加载 src-layout**

```ini
[pytest]
testpaths = tests
pythonpath = src .
```

- [x] **Step 4: 测试引用改为新宿主包名**

测试中的宿主应用引用改为 `translate_manga.*`。`tests/test_saber_loader.py` 中用于模拟 vendor Saber 的 `sys.modules["src.core..."]`、`("src.core", SABER_ROOT / "src" / "core")` 保持不变。

### Task 4: 验证

**Files:**
- No production file changes.

- [x] **Step 1: 包导入与入口单测**

Run: `.venv310/Scripts/python.exe -m pytest tests/test_package_imports.py tests/test_batch_translate_entry.py tests/test_run_batch_background.py tests/test_start_cli_bat.py -q`

Expected: PASS。

- [x] **Step 2: 核心流水线回归**

Run: `.venv310/Scripts/python.exe -m pytest tests/test_pipeline_service.py tests/test_inpaint_render_services.py -q`

Expected: PASS。

- [x] **Step 3: Saber loader 回归**

Run: `.venv310/Scripts/python.exe -m pytest tests/test_saber_loader.py -q`

Expected: PASS。

- [x] **Step 4: 真实单页冒烟**

Run: `start_cli.bat --input "smoke/kamui_034_input" --output "smoke/kamui_034_output_phase2" --layout-mode vertical --overwrite-existing`

Expected: `Summary: total=1 ok=1 skip=0 fail=0`，输出 `.translated.png`。

## 自检

- 本阶段不修改 `vendor/Saber-Translator`。
- 本阶段不修改 `D:/github/translate-reader/translate_manga_v2` 以外任何文件。
- 本阶段不执行 git commit/push。
- 本阶段不拆大文件，只先消除最危险的包名冲突。

## 完成记录

- 已新增 `src/translate_manga/` 应用包，并将宿主入口改为 `translate_manga.*`。
- 已保留 `saber_loader.py` 内嵌 vendor 脚本中的 `src.core.*` 导入。
- 已新增 `translate_manga.config.paths.find_project_root()`，避免迁移后继续依赖脆弱的 `parents[n]` 项目根推断。
- 验证命令：
  - `.venv310/Scripts/python.exe -m compileall -q src/translate_manga batch_translate.py run_batch_background.py`
  - 2026-05-09 全量回归已可直接运行：`.venv310/Scripts/python.exe -m pytest -q`，结果 `169 passed`
  - `start_cli.bat --help` 正常
  - fresh smoke：`Kamui#01_034.jpg`，结果 `Summary: total=1 ok=1 skip=0 fail=0`
