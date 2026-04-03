import { h, Fragment } from "/_taiyaki/preact-client.bundle.js";
export { Fragment };
export function jsx(type, props) {
  const { children, ...rest } = props || {};
  return h(type, rest, children);
}
export { jsx as jsxs, jsx as jsxDEV };
