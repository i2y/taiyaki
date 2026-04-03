import "preact";

declare module "preact" {
  namespace JSX {
    interface IntrinsicElements {
      "taiyaki-head": preact.JSX.HTMLAttributes<HTMLElement>;
      "taiyaki-stream-marker": preact.JSX.HTMLAttributes<HTMLElement>;
      "taiyaki-raw": preact.JSX.HTMLAttributes<HTMLElement>;
    }
  }
}
