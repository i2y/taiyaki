use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use rquickjs::loader::{Loader, Resolver};
use rquickjs::module::Declared;
use rquickjs::{Ctx, Module, Result};

/// Resolver that checks the shared module source store.
pub(crate) struct SharedResolver {
    pub(crate) modules: Rc<RefCell<HashMap<String, String>>>,
}

impl Resolver for SharedResolver {
    fn resolve<'js>(&mut self, _ctx: &Ctx<'js>, _base: &str, name: &str) -> Result<String> {
        let store = self.modules.borrow();
        if store.contains_key(name) {
            Ok(name.to_string())
        } else {
            Err(rquickjs::Error::new_loading(name))
        }
    }
}

/// Loader that reads (clones) source from the shared store.
/// Unlike rquickjs BuiltinLoader, this does NOT remove the module on load,
/// so the same module can be imported multiple times.
pub(crate) struct SharedLoader {
    pub(crate) modules: Rc<RefCell<HashMap<String, String>>>,
}

impl Loader for SharedLoader {
    fn load<'js>(&mut self, ctx: &Ctx<'js>, name: &str) -> Result<Module<'js, Declared>> {
        let store = self.modules.borrow();
        let source = store
            .get(name)
            .ok_or_else(|| rquickjs::Error::new_loading(name))?
            .clone();
        drop(store);
        Module::declare(ctx.clone(), name, source)
    }
}
