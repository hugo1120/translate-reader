import argparse
import sys
from pathlib import Path

from src.cli.service import run_batch_translation
from src.config.settings import load_settings, resolve_path_value


def _project_root():
    return Path(__file__).resolve().parent


def _resolve_runtime_path(value):
    resolved = resolve_path_value(value, project_root=_project_root())
    if resolved:
        return Path(resolved)
    return None


def _resolve_default_paths():
    settings = load_settings()
    paths = settings.get("paths") or {}
    return _resolve_runtime_path(paths.get("input_dir")), _resolve_runtime_path(paths.get("output_dir"))


def _build_parser():
    parser = argparse.ArgumentParser(description="批量翻译漫画图片目录。")
    parser.add_argument("input_dir", nargs="?", help="输入图片目录")
    parser.add_argument("output_dir", nargs="?", help="输出目录")
    parser.add_argument("--input", dest="input_dir_option", help="输入图片目录，优先级高于位置参数")
    parser.add_argument("--output", dest="output_dir_option", help="输出目录，优先级高于位置参数")
    parser.add_argument("--layout-mode", choices=["horizontal", "vertical", "auto"], help="排版方向")
    parser.add_argument("--workspace-root", help="临时工作目录根")
    parser.add_argument("--cache-root", help="隐藏 stage cache 根目录")
    parser.add_argument("--model", help="翻译模型名")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL")
    parser.add_argument("--api-key", help="OpenAI-compatible API key")
    parser.add_argument("--overwrite-existing", action="store_true", help="覆盖已存在的输出")
    return parser


def _resolve_input_output(args):
    default_input_dir, default_output_dir = _resolve_default_paths()
    input_dir = args.input_dir_option or args.input_dir or default_input_dir
    output_dir = args.output_dir_option or args.output_dir or default_output_dir
    return input_dir, output_dir


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    input_dir, output_dir = _resolve_input_output(args)
    if input_dir is None or output_dir is None:
        parser.error("input/output 未提供，且 config/local.json 里也没有 paths.input_dir / paths.output_dir。")

    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        parser.error(f"输入目录不存在: {input_dir}")

    settings = load_settings()
    render_settings = settings.get("render") or {}
    layout_mode = str(args.layout_mode or render_settings.get("layout_mode") or "vertical").strip() or "vertical"

    try:
        summary = run_batch_translation(
            input_dir=input_dir,
            output_dir=output_dir,
            workspace_root=args.workspace_root,
            cache_root=args.cache_root,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            overwrite_existing=True if args.overwrite_existing else None,
            layout_mode=layout_mode,
            launch_mode="args",
        )
    except Exception as error:
        print(f"Batch translation failed: {error}", file=sys.stderr)
        return 1

    print(
        "Summary: "
        f"total={summary['total']} "
        f"ok={summary['succeeded']} "
        f"skip={summary['skipped']} "
        f"fail={summary['failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
