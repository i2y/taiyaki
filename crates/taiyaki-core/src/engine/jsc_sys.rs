//! Raw FFI bindings to the JavaScriptCore C API.
//!
//! On macOS, links to the system JavaScriptCore.framework.
//! Only the subset of functions needed by `JscEngine` is declared here.

#![allow(non_camel_case_types, non_upper_case_globals, dead_code)]

use std::ffi::c_char;
use std::os::raw::c_void;

// ---------------------------------------------------------------------------
// Opaque pointer types
// ---------------------------------------------------------------------------
pub(crate) type JSContextGroupRef = *const c_void;
pub(crate) type JSGlobalContextRef = *mut c_void;
pub(crate) type JSContextRef = *const c_void; // JSGlobalContextRef is-a JSContextRef
pub(crate) type JSValueRef = *const c_void;
pub(crate) type JSObjectRef = *mut c_void; // JSObjectRef is also a JSValueRef
pub(crate) type JSStringRef = *mut c_void;
pub(crate) type JSClassRef = *mut c_void;
pub(crate) type JSPropertyNameArrayRef = *mut c_void;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
pub(crate) type JSType = u32;
pub(crate) const kJSTypeUndefined: JSType = 0;
pub(crate) const kJSTypeNull: JSType = 1;
pub(crate) const kJSTypeBoolean: JSType = 2;
pub(crate) const kJSTypeNumber: JSType = 3;
pub(crate) const kJSTypeString: JSType = 4;
pub(crate) const kJSTypeObject: JSType = 5;
pub(crate) const kJSTypeSymbol: JSType = 6;

pub(crate) type JSPropertyAttributes = u32;
pub(crate) const kJSPropertyAttributeNone: JSPropertyAttributes = 0;

pub(crate) type JSClassAttributes = u32;
pub(crate) const kJSClassAttributeNone: JSClassAttributes = 0;

// ---------------------------------------------------------------------------
// Callback types
// ---------------------------------------------------------------------------

/// Callback invoked when a JSC object created with a custom class is called as a function.
pub(crate) type JSObjectCallAsFunctionCallback = unsafe extern "C" fn(
    ctx: JSContextRef,
    function: JSObjectRef,
    this_object: JSObjectRef,
    argument_count: usize,
    arguments: *const JSValueRef,
    exception: *mut JSValueRef,
) -> JSValueRef;

/// Callback invoked when a JSC object is finalized (garbage-collected).
pub(crate) type JSObjectFinalizeCallback = unsafe extern "C" fn(object: JSObjectRef);

// ---------------------------------------------------------------------------
// JSClassDefinition
// ---------------------------------------------------------------------------

/// Matches the C struct layout of JSClassDefinition.
#[repr(C)]
pub(crate) struct JSClassDefinition {
    pub version: i32,
    pub attributes: JSClassAttributes,
    pub class_name: *const c_char,
    pub parent_class: JSClassRef,
    pub static_values: *const c_void,
    pub static_functions: *const c_void,
    pub initialize: *const c_void,
    pub finalize: Option<JSObjectFinalizeCallback>,
    pub has_property: *const c_void,
    pub get_property: *const c_void,
    pub set_property: *const c_void,
    pub delete_property: *const c_void,
    pub get_property_names: *const c_void,
    pub call_as_function: Option<JSObjectCallAsFunctionCallback>,
    pub call_as_constructor: *const c_void,
    pub has_instance: *const c_void,
    pub convert_to_type: *const c_void,
}

impl JSClassDefinition {
    /// Creates a zeroed definition (equivalent to kJSClassDefinitionEmpty).
    pub const fn empty() -> Self {
        Self {
            version: 0,
            attributes: kJSClassAttributeNone,
            class_name: std::ptr::null(),
            parent_class: std::ptr::null_mut(),
            static_values: std::ptr::null(),
            static_functions: std::ptr::null(),
            initialize: std::ptr::null(),
            finalize: None,
            has_property: std::ptr::null(),
            get_property: std::ptr::null(),
            set_property: std::ptr::null(),
            delete_property: std::ptr::null(),
            get_property_names: std::ptr::null(),
            call_as_function: None,
            call_as_constructor: std::ptr::null(),
            has_instance: std::ptr::null(),
            convert_to_type: std::ptr::null(),
        }
    }
}

// ---------------------------------------------------------------------------
// Extern functions
// ---------------------------------------------------------------------------

unsafe extern "C" {
    // --- Context ---
    pub(crate) fn JSGlobalContextCreate(global_object_class: JSClassRef) -> JSGlobalContextRef;
    pub(crate) fn JSGlobalContextRelease(ctx: JSGlobalContextRef);
    pub(crate) fn JSContextGetGlobalObject(ctx: JSContextRef) -> JSObjectRef;
    pub(crate) fn JSContextGetGroup(ctx: JSContextRef) -> JSContextGroupRef;

    // --- Value type checking ---
    pub(crate) fn JSValueGetType(ctx: JSContextRef, value: JSValueRef) -> JSType;
    pub(crate) fn JSValueIsUndefined(ctx: JSContextRef, value: JSValueRef) -> bool;
    pub(crate) fn JSValueIsNull(ctx: JSContextRef, value: JSValueRef) -> bool;
    pub(crate) fn JSValueIsBoolean(ctx: JSContextRef, value: JSValueRef) -> bool;
    pub(crate) fn JSValueIsNumber(ctx: JSContextRef, value: JSValueRef) -> bool;
    pub(crate) fn JSValueIsString(ctx: JSContextRef, value: JSValueRef) -> bool;
    pub(crate) fn JSValueIsObject(ctx: JSContextRef, value: JSValueRef) -> bool;
    pub(crate) fn JSValueIsArray(ctx: JSContextRef, value: JSValueRef) -> bool;

    // --- Value creation ---
    pub(crate) fn JSValueMakeUndefined(ctx: JSContextRef) -> JSValueRef;
    pub(crate) fn JSValueMakeNull(ctx: JSContextRef) -> JSValueRef;
    pub(crate) fn JSValueMakeBoolean(ctx: JSContextRef, value: bool) -> JSValueRef;
    pub(crate) fn JSValueMakeNumber(ctx: JSContextRef, value: f64) -> JSValueRef;
    pub(crate) fn JSValueMakeString(ctx: JSContextRef, string: JSStringRef) -> JSValueRef;

    // --- Value conversion ---
    pub(crate) fn JSValueToBoolean(ctx: JSContextRef, value: JSValueRef) -> bool;
    pub(crate) fn JSValueToNumber(
        ctx: JSContextRef,
        value: JSValueRef,
        exception: *mut JSValueRef,
    ) -> f64;
    pub(crate) fn JSValueToStringCopy(
        ctx: JSContextRef,
        value: JSValueRef,
        exception: *mut JSValueRef,
    ) -> JSStringRef;
    pub(crate) fn JSValueToObject(
        ctx: JSContextRef,
        value: JSValueRef,
        exception: *mut JSValueRef,
    ) -> JSObjectRef;

    // --- Value GC management ---
    pub(crate) fn JSValueProtect(ctx: JSContextRef, value: JSValueRef);
    pub(crate) fn JSValueUnprotect(ctx: JSContextRef, value: JSValueRef);

    // --- JSON ---
    pub(crate) fn JSValueMakeFromJSONString(ctx: JSContextRef, string: JSStringRef) -> JSValueRef;
    pub(crate) fn JSValueCreateJSONString(
        ctx: JSContextRef,
        value: JSValueRef,
        indent: u32,
        exception: *mut JSValueRef,
    ) -> JSStringRef;

    // --- String ---
    pub(crate) fn JSStringCreateWithUTF8CString(string: *const c_char) -> JSStringRef;
    pub(crate) fn JSStringRelease(string: JSStringRef);
    pub(crate) fn JSStringGetMaximumUTF8CStringSize(string: JSStringRef) -> usize;
    pub(crate) fn JSStringGetUTF8CString(
        string: JSStringRef,
        buffer: *mut c_char,
        buffer_size: usize,
    ) -> usize;

    // --- Object ---
    pub(crate) fn JSObjectMake(
        ctx: JSContextRef,
        js_class: JSClassRef,
        data: *mut c_void,
    ) -> JSObjectRef;
    pub(crate) fn JSObjectMakeFunctionWithCallback(
        ctx: JSContextRef,
        name: JSStringRef,
        callback: JSObjectCallAsFunctionCallback,
    ) -> JSObjectRef;
    pub(crate) fn JSObjectMakeArray(
        ctx: JSContextRef,
        argument_count: usize,
        arguments: *const JSValueRef,
        exception: *mut JSValueRef,
    ) -> JSObjectRef;
    pub(crate) fn JSObjectGetProperty(
        ctx: JSContextRef,
        object: JSObjectRef,
        property_name: JSStringRef,
        exception: *mut JSValueRef,
    ) -> JSValueRef;
    pub(crate) fn JSObjectSetProperty(
        ctx: JSContextRef,
        object: JSObjectRef,
        property_name: JSStringRef,
        value: JSValueRef,
        attributes: JSPropertyAttributes,
        exception: *mut JSValueRef,
    );
    pub(crate) fn JSObjectGetPropertyAtIndex(
        ctx: JSContextRef,
        object: JSObjectRef,
        property_index: u32,
        exception: *mut JSValueRef,
    ) -> JSValueRef;
    pub(crate) fn JSObjectSetPropertyAtIndex(
        ctx: JSContextRef,
        object: JSObjectRef,
        property_index: u32,
        value: JSValueRef,
        exception: *mut JSValueRef,
    );
    pub(crate) fn JSObjectCallAsFunction(
        ctx: JSContextRef,
        object: JSObjectRef,
        this_object: JSObjectRef,
        argument_count: usize,
        arguments: *const JSValueRef,
        exception: *mut JSValueRef,
    ) -> JSValueRef;
    pub(crate) fn JSObjectIsFunction(ctx: JSContextRef, object: JSObjectRef) -> bool;
    pub(crate) fn JSObjectGetPrivate(object: JSObjectRef) -> *mut c_void;
    pub(crate) fn JSObjectSetPrivate(object: JSObjectRef, data: *mut c_void) -> bool;

    // --- Class ---
    pub(crate) fn JSClassCreate(definition: *const JSClassDefinition) -> JSClassRef;
    pub(crate) fn JSClassRelease(js_class: JSClassRef);

    // --- Script evaluation ---
    pub(crate) fn JSEvaluateScript(
        ctx: JSContextRef,
        script: JSStringRef,
        this_object: JSObjectRef,
        source_url: JSStringRef,
        starting_line_number: i32,
        exception: *mut JSValueRef,
    ) -> JSValueRef;

    // --- Garbage collection ---
    pub(crate) fn JSGarbageCollect(ctx: JSContextRef);

    // --- Execution time limit (semi-private, available on macOS 10.6+) ---
    pub(crate) fn JSContextGroupSetExecutionTimeLimit(
        group: JSContextGroupRef,
        limit: f64,
        callback: Option<JSShouldTerminateCallback>,
        context: *mut c_void,
    );
    pub(crate) fn JSContextGroupClearExecutionTimeLimit(group: JSContextGroupRef);

    // --- Deferred Promise (macOS 10.15+ / iOS 13+) ---
    pub(crate) fn JSObjectMakeDeferredPromise(
        ctx: JSContextRef,
        resolve: *mut JSObjectRef,
        reject: *mut JSObjectRef,
        exception: *mut JSValueRef,
    ) -> JSObjectRef;
}

/// Callback type for execution time limit.
/// Return `true` to terminate execution, `false` to continue.
pub(crate) type JSShouldTerminateCallback =
    unsafe extern "C" fn(ctx: JSContextRef, context: *mut c_void) -> bool;
