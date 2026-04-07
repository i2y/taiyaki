use swc_common::{
    FileName, Mark, SourceMap,
    comments::SingleThreadedComments,
    errors::{HANDLER, Handler},
    sync::Lrc,
};
use swc_ecma_ast::{EsVersion, Program};
use swc_ecma_codegen::text_writer::JsWriter;
use swc_ecma_parser::{Parser, StringInput, Syntax, TsSyntax, lexer::Lexer};
use swc_ecma_transforms_base::{
    fixer::fixer,
    helpers::{HELPERS, Helpers, inject_helpers},
    hygiene::hygiene,
    resolver,
};
use swc_ecma_transforms_typescript::typescript;
use swc_ts_fast_strip::{Mode, Options, operate};

#[derive(Default)]
pub struct Transpiler {
    _priv: (),
}

impl Transpiler {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn strip_types(&self, ts_code: &str) -> Result<String, TranspileError> {
        let cm: Lrc<SourceMap> = Default::default();
        let handler = Handler::with_emitter_writer(Box::new(std::io::sink()), Some(cm.clone()));
        let options = Options {
            mode: Mode::StripOnly,
            ..Default::default()
        };

        let output = HANDLER
            .set(&handler, || {
                operate(&cm, &handler, ts_code.to_string(), options)
            })
            .map_err(|e| TranspileError(e.to_string()))?;

        Ok(output.code)
    }
}

/// Convenience function for one-off usage
pub fn strip_types(ts_code: &str) -> Result<String, TranspileError> {
    Transpiler::new().strip_types(ts_code)
}

/// Options for JSX transformation.
pub struct JsxOptions {
    /// JSX import source for automatic runtime (default: "preact")
    pub import_source: String,
}

impl Default for JsxOptions {
    fn default() -> Self {
        Self {
            import_source: "preact".into(),
        }
    }
}

// ---------------------------------------------------------------------------
// Shared swc pipeline: parse TSX → apply transforms → emit JS
// ---------------------------------------------------------------------------

struct SwcMarks {
    unresolved: Mark,
    top_level: Mark,
}

/// Parse code as TSX, apply caller-provided transforms, emit JavaScript.
/// When `force_module` is true, always parse as ES module (needed for
/// automatic JSX runtime which generates `import` statements).
fn swc_transform_inner(
    code: &str,
    inline_helpers: bool,
    force_module: bool,
    apply: impl FnOnce(&mut Program, &Lrc<SourceMap>, &SingleThreadedComments, &SwcMarks),
) -> Result<String, TranspileError> {
    use swc_common::Globals;

    swc_common::GLOBALS.set(&Globals::new(), || {
        let cm: Lrc<SourceMap> = Default::default();
        let handler = Handler::with_emitter_writer(Box::new(std::io::sink()), Some(cm.clone()));

        let fm = cm.new_source_file(FileName::Anon.into(), code.to_string());
        let comments = SingleThreadedComments::default();

        let lexer = Lexer::new(
            Syntax::Typescript(TsSyntax {
                tsx: true,
                ..Default::default()
            }),
            EsVersion::latest(),
            StringInput::from(&*fm),
            Some(&comments),
        );
        let mut parser = Parser::new_from(lexer);

        let mut program = if force_module {
            parser.parse_module().map(Program::Module)
        } else {
            parser.parse_program()
        }
        .map_err(|e| {
            e.into_diagnostic(&handler).emit();
            TranspileError("parse error".to_string())
        })?;

        for e in parser.take_errors() {
            e.into_diagnostic(&handler).emit();
        }

        let marks = SwcMarks {
            unresolved: Mark::new(),
            top_level: Mark::new(),
        };

        HANDLER.set(&handler, || {
            HELPERS.set(&Helpers::new(inline_helpers), || {
                program.mutate(&mut resolver(marks.unresolved, marks.top_level, true));

                apply(&mut program, &cm, &comments, &marks);

                program.mutate(&mut inject_helpers(marks.unresolved));
                program.mutate(&mut hygiene());
                program.mutate(&mut fixer(Some(&comments)));
            });
        });

        let mut buf = Vec::with_capacity(code.len());
        {
            let mut emitter = swc_ecma_codegen::Emitter {
                cfg: swc_ecma_codegen::Config::default(),
                comments: None,
                cm: cm.clone(),
                wr: JsWriter::new(cm.clone(), "\n", &mut buf, None),
            };
            emitter
                .emit_program(&program)
                .map_err(|e| TranspileError(e.to_string()))?;
        }

        String::from_utf8(buf).map_err(|e| TranspileError(e.to_string()))
    })
}

// ---------------------------------------------------------------------------
// Public transform functions
// ---------------------------------------------------------------------------

/// Transform JSX/TSX code to JavaScript.
pub fn transform_jsx(code: &str, options: &JsxOptions) -> Result<String, TranspileError> {
    swc_transform_inner(code, false, true, |program, cm, comments, marks| {
        // JSX transform BEFORE typescript strip — otherwise TS strip
        // removes JSX-related imports as "unused".
        program.mutate(&mut swc_ecma_transforms_react::jsx(
            cm.clone(),
            Some(comments.clone()),
            swc_ecma_transforms_react::Options {
                runtime: Some(swc_ecma_transforms_react::Runtime::Automatic),
                import_source: Some(options.import_source.clone().into()),
                ..Default::default()
            },
            marks.top_level,
            marks.unresolved,
        ));

        program.mutate(&mut typescript::typescript(
            Default::default(),
            marks.unresolved,
            marks.top_level,
        ));
    })
}

/// Transform ES module source to CommonJS format.
///
/// Converts `import/export` to `require()`/`exports.*` using swc.
pub fn transform_esm_to_cjs(code: &str) -> Result<String, TranspileError> {
    use swc_ecma_transforms_module::common_js;

    swc_transform_inner(code, true, false, |program, _cm, _comments, marks| {
        program.mutate(&mut typescript::typescript(
            Default::default(),
            marks.unresolved,
            marks.top_level,
        ));

        program.mutate(&mut common_js::common_js(
            swc_ecma_transforms_module::path::Resolver::Default,
            marks.unresolved,
            swc_ecma_transforms_module::util::Config {
                no_interop: true,
                ..Default::default()
            },
            common_js::FeatureFlag {
                support_arrow: true,
                support_block_scoping: true,
            },
        ));
    })
}

/// Parse and re-emit code for formatting. Strips types from TS, preserves JS.
pub fn format_code(code: &str, is_ts: bool) -> Result<String, TranspileError> {
    use swc_common::Globals;

    swc_common::GLOBALS.set(&Globals::new(), || {
        let cm: Lrc<SourceMap> = Default::default();
        let handler = Handler::with_emitter_writer(Box::new(std::io::sink()), Some(cm.clone()));

        let fm = cm.new_source_file(FileName::Anon.into(), code.to_string());
        let comments = SingleThreadedComments::default();

        let syntax = if is_ts {
            Syntax::Typescript(TsSyntax {
                tsx: true,
                ..Default::default()
            })
        } else {
            Syntax::Es(swc_ecma_parser::EsSyntax {
                jsx: true,
                ..Default::default()
            })
        };

        let lexer = Lexer::new(
            syntax,
            EsVersion::latest(),
            StringInput::from(&*fm),
            Some(&comments),
        );
        let mut parser = Parser::new_from(lexer);

        let program = parser.parse_program().map_err(|e| {
            e.into_diagnostic(&handler).emit();
            TranspileError("parse error".to_string())
        })?;

        let mut buf = Vec::with_capacity(code.len());
        {
            let mut emitter = swc_ecma_codegen::Emitter {
                cfg: swc_ecma_codegen::Config::default(),
                comments: Some(&comments),
                cm: cm.clone(),
                wr: JsWriter::new(cm.clone(), "\n", &mut buf, None),
            };
            emitter
                .emit_program(&program)
                .map_err(|e| TranspileError(e.to_string()))?;
        }

        String::from_utf8(buf).map_err(|e| TranspileError(e.to_string()))
    })
}

/// Parse code and return diagnostics (errors) without transforming.
pub fn check_syntax(code: &str, is_ts: bool) -> Vec<String> {
    use swc_common::Globals;

    swc_common::GLOBALS.set(&Globals::new(), || {
        let cm: Lrc<SourceMap> = Default::default();
        let handler = Handler::with_emitter_writer(Box::new(std::io::sink()), Some(cm.clone()));

        let fm = cm.new_source_file(FileName::Anon.into(), code.to_string());
        let comments = SingleThreadedComments::default();

        let syntax = if is_ts {
            Syntax::Typescript(TsSyntax {
                tsx: true,
                ..Default::default()
            })
        } else {
            Syntax::Es(swc_ecma_parser::EsSyntax {
                jsx: true,
                ..Default::default()
            })
        };

        let lexer = Lexer::new(
            syntax,
            EsVersion::latest(),
            StringInput::from(&*fm),
            Some(&comments),
        );
        let mut parser = Parser::new_from(lexer);

        let mut errors = Vec::new();

        match parser.parse_program() {
            Ok(_) => {}
            Err(e) => {
                errors.push(format!("{}", e.kind().msg()));
            }
        }

        for e in parser.take_errors() {
            errors.push(format!("{}", e.kind().msg()));
        }

        let _ = handler;
        errors
    })
}

#[derive(Debug, Clone)]
pub struct TranspileError(pub String);

impl std::fmt::Display for TranspileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "TypeScript transpile error: {}", self.0)
    }
}

impl std::error::Error for TranspileError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strip_basic_types() {
        let ts = "const x: number = 42;";
        let js = strip_types(ts).unwrap();
        assert!(!js.contains(": number"), "JS still contains type: {js}");
        assert!(js.contains("42"));
    }

    #[test]
    fn test_strip_interface() {
        let ts = r#"
            interface User { name: string; age: number; }
            const u = { name: "Alice", age: 30 };
        "#;
        let js = strip_types(ts).unwrap();
        assert!(
            !js.contains("interface"),
            "JS still contains interface: {js}"
        );
        assert!(js.contains("Alice"));
    }

    #[test]
    fn test_strip_generics() {
        let ts = "function identity<T>(x: T): T { return x; }";
        let js = strip_types(ts).unwrap();
        assert!(!js.contains("<T>"), "JS still contains <T>: {js}");
        assert!(js.contains("return x"));
    }

    #[test]
    fn test_strip_preserves_js() {
        let js_code = "const x = 42;";
        let result = strip_types(js_code).unwrap();
        assert!(result.contains("const x = 42"));
    }

    #[test]
    fn test_strip_type_alias() {
        let ts = "type ID = string | number;\nconst x = 1;";
        let js = strip_types(ts).unwrap();
        assert!(!js.contains("type ID"), "type alias not stripped: {js}");
        assert!(js.contains("const x = 1"));
    }

    #[test]
    fn test_transpiler_reuse() {
        let t = Transpiler::new();
        let r1 = t.strip_types("const a: number = 1;").unwrap();
        let r2 = t.strip_types("const b: string = 'hi';").unwrap();
        assert!(r1.contains("1"));
        assert!(r2.contains("hi"));
    }

    #[test]
    fn test_jsx_basic_element() {
        let code = r#"const el = <div className="test">Hello</div>;"#;
        let js = transform_jsx(code, &JsxOptions::default()).unwrap();
        // automatic runtime generates _jsx("div", ...) instead of h("div", ...)
        assert!(js.contains("_jsx(\"div\""), "JSX not transformed: {js}");
        assert!(js.contains("Hello"), "Content lost: {js}");
    }

    #[test]
    fn test_jsx_self_closing() {
        let code = r#"const el = <br />;"#;
        let js = transform_jsx(code, &JsxOptions::default()).unwrap();
        assert!(
            js.contains("_jsx(\"br\""),
            "Self-closing not transformed: {js}"
        );
    }

    #[test]
    fn test_jsx_with_props() {
        let code = r#"const el = <input type="text" value={42} />;"#;
        let js = transform_jsx(code, &JsxOptions::default()).unwrap();
        assert!(js.contains("_jsx(\"input\""), "JSX not transformed: {js}");
        assert!(js.contains("42"), "Prop value lost: {js}");
    }

    #[test]
    fn test_jsx_nested() {
        let code = r#"const el = <div><span>inner</span></div>;"#;
        let js = transform_jsx(code, &JsxOptions::default()).unwrap();
        assert!(js.contains("_jsx(\"div\""), "Outer element: {js}");
        assert!(js.contains("_jsx(\"span\""), "Inner element: {js}");
    }

    #[test]
    fn test_jsx_fragment() {
        let code = r#"const el = <>one<br/>two</>;"#;
        let js = transform_jsx(code, &JsxOptions::default()).unwrap();
        assert!(js.contains("Fragment"), "Fragment not used: {js}");
    }

    #[test]
    fn test_jsx_pure_no_types() {
        let code = r#"const App = () => <h1>Hello</h1>;"#;
        let js = transform_jsx(code, &JsxOptions::default()).unwrap();
        assert!(js.contains("_jsx(\"h1\""), "JSX not transformed: {js}");
    }

    #[test]
    fn test_tsx_types_and_jsx() {
        let tsx = r#"
            interface Props { name: string; }
            function Greet(props: Props) { return <p>{props.name}</p>; }
        "#;
        let js = transform_jsx(tsx, &JsxOptions::default()).unwrap();
        assert!(!js.contains("interface"), "Interface not stripped: {js}");
        assert!(
            !js.contains(": Props"),
            "Type annotation not stripped: {js}"
        );
        assert!(js.contains("_jsx(\"p\""), "JSX not transformed: {js}");
    }

    #[test]
    fn test_jsx_component_export() {
        let tsx = r#"
            export function Counter(props: { initial: number }) {
                return <button onClick={() => {}}>{props.initial}</button>;
            }
        "#;
        let js = transform_jsx(tsx, &JsxOptions::default()).unwrap();
        assert!(
            !js.contains(": { initial: number }"),
            "Types not stripped: {js}"
        );
        assert!(js.contains("_jsx(\"button\""), "JSX not transformed: {js}");
        assert!(js.contains("onClick"), "Event handler lost: {js}");
    }

    #[test]
    fn test_esm_to_cjs() {
        let code = r#"import os from 'os'; console.log(os.platform());"#;
        let result = transform_esm_to_cjs(code).unwrap();
        assert!(result.contains("require(\"os\")"));
        assert!(!result.contains("@swc/helpers"));
    }
}
