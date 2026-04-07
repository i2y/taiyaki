"""Main compilation pipeline for Tsuchi."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tsuchi.parser.js_parser import JSParser
from tsuchi.parser.ts_stripper import strip_types, extract_type_hints
from tsuchi.parser.jsx_transformer import transform_jsx
from tsuchi.parser.clay_jsx_transformer import transform_clay_jsx, CLAY_JSX_TAGS
from tsuchi.parser.module_merger import ModuleMerger
from tsuchi.parser.ast_nodes import ImportDeclaration
from tsuchi.parser.ffi_loader import extract_ffi_declarations, FFIInfo
from tsuchi.type_checker.js_inferrer import JSInferrer, TypedModule
from tsuchi.type_checker.dts_parser import DTSParser
from tsuchi.type_checker.types import FunctionType
from tsuchi.hir.builder import HIRBuilder
from tsuchi.hir.optimizer import HIROptimizer
from tsuchi.codegen.llvm_generator import LLVMGenerator
from tsuchi.codegen.backend_base import BackendBase
from tsuchi.diagnostics.diagnostic import DiagnosticCollector


@dataclass
class CompileResult:
    success: bool
    output_path: str | None = None
    diagnostics: str = ""
    llvm_ir: str = ""
    native_funcs: list[str] = field(default_factory=list)
    fallback_funcs: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    success: bool
    diagnostics: str = ""
    typed_module: TypedModule | None = None


class Compiler:
    """Tsuchi compiler: JS source → standalone binary."""

    def __init__(self, verbose: bool = False, backend: str = "quickjs"):
        self.verbose = verbose
        self._backend_name = backend

    def _create_backend(self) -> BackendBase:
        if self._backend_name == "jsc":
            from tsuchi.codegen.jsc_backend import JSCBackend
            return JSCBackend()
        if self._backend_name == "taiyaki":
            from tsuchi.codegen.taiyaki_backend import TaiyakiBackend
            return TaiyakiBackend()
        from tsuchi.codegen.quickjs_backend import QuickJSBackend
        return QuickJSBackend()

    def _load_type_stubs(self, filepath: str) -> dict[str, FunctionType]:
        """Look for a .d.ts file alongside the .js file and parse it."""
        path = Path(filepath)
        dts_path = path.with_suffix(".d.ts")
        if dts_path.exists():
            parser = DTSParser()
            return parser.parse_file(str(dts_path))
        return {}

    def _load_ffi_from_dts(self, filepath: str) -> FFIInfo | None:
        """Look for a .d.ts sidecar file and extract FFI declarations."""
        path = Path(filepath)
        dts_path = path.with_suffix(".d.ts")
        if dts_path.exists():
            dts_source = dts_path.read_text(encoding="utf-8")
            return extract_ffi_declarations(dts_source)
        return None

    def compile_file(self, filepath: str, output_dir: str = ".",
                     extra_link: list[str] | None = None,
                     extra_link_libs: list[str] | None = None,
                     extra_lib_paths: list[str] | None = None,
                     tui: bool = False) -> CompileResult:
        path = Path(filepath)
        source = path.read_text(encoding="utf-8")
        type_stubs = self._load_type_stubs(filepath)
        ffi_info: FFIInfo | None = None

        # Extract FFI declarations from .ts source BEFORE stripping
        if path.suffix in (".ts", ".tsx"):
            ffi_info = extract_ffi_declarations(source)

        # Extract FFI from .d.ts sidecar for .js files
        if path.suffix == ".js":
            ffi_info = self._load_ffi_from_dts(filepath)

        # Merge CLI link options into ffi_info
        if extra_link or extra_link_libs or extra_lib_paths:
            if ffi_info is None:
                ffi_info = FFIInfo()
            for item in (extra_link or []):
                if item.endswith(".c"):
                    ffi_info.c_sources.append(item)
                else:
                    ffi_info.link_libs.append(item)
            for lib in (extra_link_libs or []):
                ffi_info.link_libs.append(f"-l{lib}")
            for lp in (extra_lib_paths or []):
                ffi_info.lib_paths.append(lp)

        # Drop ffi_info if it has nothing
        if ffi_info is not None and not ffi_info.functions and not ffi_info.link_libs and not ffi_info.c_sources and not ffi_info.structs and not ffi_info.opaque_classes:
            ffi_info = None

        # Extract TS type hints before stripping annotations
        if path.suffix in (".ts", ".tsx"):
            ts_hints = extract_type_hints(source)
            for name, ft in ts_hints.items():
                type_stubs.setdefault(name, ft)
            source = strip_types(source, tsx=(path.suffix == ".tsx"))

        # Transform JSX — Clay JSX if any Clay/UI tags present, else generic
        if path.suffix in (".jsx", ".tsx"):
            if any(f"<{t}" in source for t in CLAY_JSX_TAGS):
                source = transform_clay_jsx(source, tui=tui)
            else:
                source = transform_jsx(source)

        module_name = path.stem

        # Check if source has import statements → multi-module compilation
        if self._has_imports(source):
            return self._compile_multi_module(filepath, module_name, output_dir)

        return self.compile_source(source, module_name, output_dir,
                                   filename=str(path), type_stubs=type_stubs,
                                   ffi_info=ffi_info, input_dir=str(path.parent))

    def _has_imports(self, source: str) -> bool:
        """Quick check if source contains import statements."""
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") and "from" in stripped:
                return True
        return False

    def _compile_multi_module(self, entry_file: str, module_name: str,
                               output_dir: str) -> CompileResult:
        """Compile multiple modules by merging them into a single unit."""
        diag = DiagnosticCollector()

        # Read entry source for entry statement extraction (loc references entry file lines)
        entry_source = Path(entry_file).read_text(encoding="utf-8")

        try:
            merger = ModuleMerger()
            merged_module, merged_source, ts_type_hints = merger.merge_modules(entry_file)
        except Exception as e:
            diag.error(f"Module resolution error: {e}")
            return CompileResult(success=False, diagnostics=diag.format_all())

        # Type infer the merged module (with TS type hints from all .ts modules)
        checker = JSInferrer(diagnostics=diag, type_stubs=ts_type_hints or None)
        typed_module = checker.check_module(merged_module, entry_file)

        if diag.has_errors():
            return CompileResult(success=False, diagnostics=diag.render_all(color=False))

        # HIR build — use entry source for stmt extraction (locs reference entry file)
        builder = HIRBuilder()
        hir_module = builder.build(typed_module, entry_source)

        if not hir_module.functions and not hir_module.entry_statements and not hir_module.fallback_sources:
            diag.warning("No compilable functions found")
            return CompileResult(success=False, diagnostics=diag.format_all())

        # HIR optimization
        optimizer = HIROptimizer()
        hir_module = optimizer.optimize_module(hir_module)

        # LLVM codegen
        generator = LLVMGenerator()
        llvm_ir = generator.generate(hir_module)

        if self.verbose:
            print("=== LLVM IR ===")
            print(llvm_ir)

        # QuickJS backend → binary
        backend = self._create_backend()
        try:
            output_path = backend.emit_binary(
                llvm_ir, module_name, hir_module,
                output_dir=output_dir, source=merged_source,
            )
        except Exception as e:
            diag.error(f"Backend error: {e}")
            return CompileResult(success=False, diagnostics=diag.format_all(), llvm_ir=llvm_ir)

        native = [f.name for f in typed_module.functions if f.is_compilable]
        fallback = [f.name for f in typed_module.functions if not f.is_compilable]

        return CompileResult(
            success=True,
            output_path=output_path,
            diagnostics=diag.format_all() if diag.diagnostics else "",
            llvm_ir=llvm_ir,
            native_funcs=native,
            fallback_funcs=fallback,
        )

    def compile_source(
        self, source: str, module_name: str,
        output_dir: str = ".", filename: str = "<input>",
        type_stubs: dict[str, FunctionType] | None = None,
        ffi_info: FFIInfo | None = None,
        input_dir: str = ".",
    ) -> CompileResult:
        diag = DiagnosticCollector()

        # Phase 1: Parse
        parser = JSParser()
        try:
            js_module = parser.parse(source, filename)
        except Exception as e:
            diag.error(f"Parse error: {e}")
            return CompileResult(success=False, diagnostics=diag.format_all())

        # Phase 2+3: Type infer
        checker = JSInferrer(diagnostics=diag, type_stubs=type_stubs, ffi_info=ffi_info)
        typed_module = checker.check_module(js_module, filename)

        if diag.has_errors():
            return CompileResult(success=False, diagnostics=diag.render_all(color=False))

        # Phase 4: HIR build
        builder = HIRBuilder()
        hir_module = builder.build(typed_module, source, ffi_info=ffi_info)

        if not hir_module.functions and not hir_module.entry_statements and not hir_module.fallback_sources:
            diag.warning("No compilable functions found")
            return CompileResult(success=False, diagnostics=diag.format_all())

        # Phase 4.5: HIR optimization
        optimizer = HIROptimizer()
        hir_module = optimizer.optimize_module(hir_module)

        # Phase 5: LLVM codegen
        generator = LLVMGenerator()
        llvm_ir = generator.generate(hir_module)

        if self.verbose:
            print("=== LLVM IR ===")
            print(llvm_ir)

        # Phase 6: QuickJS backend → binary
        backend = self._create_backend()
        try:
            output_path = backend.emit_binary(
                llvm_ir, module_name, hir_module,
                output_dir=output_dir, source=source,
                input_dir=input_dir,
            )
        except Exception as e:
            diag.error(f"Backend error: {e}")
            return CompileResult(success=False, diagnostics=diag.format_all(), llvm_ir=llvm_ir)

        native = [f.name for f in typed_module.functions if f.is_compilable]
        fallback = [f.name for f in typed_module.functions if not f.is_compilable]

        return CompileResult(
            success=True,
            output_path=output_path,
            diagnostics=diag.format_all() if diag.diagnostics else "",
            llvm_ir=llvm_ir,
            native_funcs=native,
            fallback_funcs=fallback,
        )

    def check_file(self, filepath: str) -> CheckResult:
        path = Path(filepath)
        source = path.read_text(encoding="utf-8")
        type_stubs = self._load_type_stubs(filepath)
        if path.suffix in (".ts", ".tsx"):
            ts_hints = extract_type_hints(source)
            for name, ft in ts_hints.items():
                type_stubs.setdefault(name, ft)
            source = strip_types(source, tsx=(path.suffix == ".tsx"))
        if path.suffix in (".jsx", ".tsx"):
            if any(f"<{t}" in source for t in CLAY_JSX_TAGS):
                source = transform_clay_jsx(source)
            else:
                source = transform_jsx(source)
        return self.check_source(source, filename=str(path), type_stubs=type_stubs)

    def check_source(self, source: str, filename: str = "<input>",
                     type_stubs: dict[str, FunctionType] | None = None) -> CheckResult:
        diag = DiagnosticCollector()

        parser = JSParser()
        try:
            js_module = parser.parse(source, filename)
        except Exception as e:
            diag.error(f"Parse error: {e}")
            return CheckResult(success=False, diagnostics=diag.format_all())

        checker = JSInferrer(diagnostics=diag, type_stubs=type_stubs)
        typed_module = checker.check_module(js_module, filename)

        return CheckResult(
            success=not diag.has_errors(),
            diagnostics=diag.render_all(color=False) if diag.diagnostics else "",
            typed_module=typed_module,
        )
