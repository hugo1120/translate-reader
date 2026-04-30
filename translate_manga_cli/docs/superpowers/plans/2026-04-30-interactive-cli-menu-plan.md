# Interactive CLI Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留纯命令行参数模式的前提下，为 `start_cli.bat` 增加交互式控制台菜单，支持跨重启记忆输入/输出/样式/覆盖策略，并在 `_debug` 中记录本次运行策略。

**Architecture:** 交互菜单单独放到 `src/cli/menu.py`，只负责收集和保存运行参数，再统一调用现有 `run_batch_translation()`。`batch_translate.py` 继续只处理参数模式，`start_cli.bat` 负责在“无参数进菜单 / 有参数直透传”之间分流。

**Tech Stack:** Python 3.10, pytest, Windows batch, 现有 CLI pipeline

---

### Task 1: 写失败测试锁定菜单与 session 行为

**Files:**
- Modify: `tests/test_batch_translate_entry.py`
- Create: `tests/test_cli_menu.py`

- [ ] **Step 1: 写菜单 reuse/reset 和回主菜单的失败测试**

```python
def test_menu_reuses_saved_session_and_returns_to_main_menu(...):
    ...
```

- [ ] **Step 2: 跑测试确认 red**

Run: `python -m pytest -q tests/test_cli_menu.py tests/test_batch_translate_entry.py`
Expected: FAIL，提示 `src.cli.menu` 缺失或 session 行为不存在

- [ ] **Step 3: 补最小实现所需的断言范围**

```python
assert "Reuse" in output
assert saved["last_layout_mode"] == "vertical"
```

- [ ] **Step 4: 再跑一次确认仍为行为级失败**

Run: `python -m pytest -q tests/test_cli_menu.py tests/test_batch_translate_entry.py`
Expected: FAIL，但不应是语法或导入错误

### Task 2: 恢复 session 读写并新增菜单入口

**Files:**
- Modify: `src/config/settings.py`
- Modify: `src/config/__init__.py`
- Create: `src/cli/menu.py`

- [ ] **Step 1: 恢复 session 读写接口**

```python
def load_session_state(project_root=None):
    ...

def save_session_state(...):
    ...
```

- [ ] **Step 2: 在 `menu.py` 写最小菜单循环**

```python
def run_interactive_menu(input_func=input, output_stream=None):
    ...
```

- [ ] **Step 3: 实现 reuse/reset、样式和 overwrite 选择**

```python
def _prompt_layout_mode(...):
    ...
```

- [ ] **Step 4: 跑菜单相关测试确认 green**

Run: `python -m pytest -q tests/test_cli_menu.py tests/test_batch_translate_entry.py`
Expected: PASS

### Task 3: 调整 `start_cli.bat` 与 `batch_translate.py` 的分流关系

**Files:**
- Modify: `start_cli.bat`
- Modify: `batch_translate.py`
- Modify: `tests/test_start_cli_bat.py`
- Modify: `tests/test_batch_translate_entry.py`

- [ ] **Step 1: 写“无参数进菜单，有参数直透传”的失败测试**

```python
def test_start_cli_bat_without_args_launches_menu(...):
    ...
```

- [ ] **Step 2: 让 `batch_translate.py` 保持参数模式不回退交互**

```python
def main(argv=None):
    ...
```

- [ ] **Step 3: 修改 bat 分流**

```bat
if "%~1"=="" (
  "%PYTHON_EXE%" -m src.cli.menu
) else (
  "%PYTHON_EXE%" "%APP_ENTRY%" %*
)
```

- [ ] **Step 4: 跑入口相关测试**

Run: `python -m pytest -q tests/test_start_cli_bat.py tests/test_batch_translate_entry.py`
Expected: PASS

### Task 4: 在 `_debug` 里记录运行策略

**Files:**
- Modify: `src/cli/debug_artifacts.py`
- Modify: `src/cli/service.py`
- Modify: `tests/test_cli_batch.py`

- [ ] **Step 1: 写失败测试锁定 `summary.json` 的 `runOptions`**

```python
assert summary_payload["runOptions"]["layoutMode"] == "vertical"
assert summary_payload["runOptions"]["launchMode"] == "menu"
```

- [ ] **Step 2: 让 `run_batch_translation()` 接受 `launch_mode`**

```python
def run_batch_translation(..., launch_mode="args"):
    ...
```

- [ ] **Step 3: 在 `debug_writer.finish()` 里写出 `runOptions`**

```python
payload["runOptions"] = run_options
```

- [ ] **Step 4: 跑测试确认 green**

Run: `python -m pytest -q tests/test_cli_batch.py`
Expected: PASS

### Task 5: 补文档

**Files:**
- Create: `start.md`
- Modify: `README.md`

- [ ] **Step 1: 写 `start.md`**

```md
## 交互菜单
## 纯命令行
## 样式说明
```

- [ ] **Step 2: 在 README 里补入口分流说明**

```md
`start_cli.bat` 无参数进菜单，有参数直透传。
```

- [ ] **Step 3: 人工检查文档命令与当前实现一致**

Run: `rg -n "start_cli|layout-mode|Style 1|Style 2|reuse|reset" README.md start.md`
Expected: 命令、样式和行为描述一致

### Task 6: 全量验证与实跑

**Files:**
- Verify only

- [ ] **Step 1: 跑 targeted tests**

Run: `python -m pytest -q tests/test_cli_menu.py tests/test_start_cli_bat.py tests/test_batch_translate_entry.py tests/test_cli_batch.py`
Expected: PASS

- [ ] **Step 2: 跑全量测试**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 3: 用菜单模式验证真实目录**

Run: `start_cli.bat`
Input:
`D:/github/translate-reader/翻译测试日漫/笑面推销员/翻译前`
`D:/github/translate-reader/翻译测试日漫/笑面推销员/翻译后`
Expected: 成功翻译并回主菜单

- [ ] **Step 4: 用参数模式验证真实目录**

Run: `start_cli.bat --input "..." --output "..." --layout-mode vertical --overwrite-existing`
Expected: 成功翻译
