
interface HomeProps {
  counterHtml?: string;
  toggleHtml?: string;
}

export default function Home({ counterHtml, toggleHtml }: HomeProps) {
  return (
    <div>
      <taiyaki-head>
        <title>Dark Batch 2 Demo</title>
        <meta name="description" content="Showcasing taiyaki-head, polyfills, source maps, middleware, and island bundling" />
        <style>{`
          .feature-card {
            background: #f8f5ff;
            border: 1px solid #e8e0f0;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
          }
          .feature-card h3 { color: #7c3aed; margin: 0 0 8px; }
          .feature-card p { color: #555; margin: 0; line-height: 1.6; }
        `}</style>
      </taiyaki-head>

      <h1 style="font-size: 32px; color: #1a1a2e;">Batch 2 Features</h1>
      <p style="color: #666; margin-bottom: 32px;">
        5 new features + JSC backend support. All demonstrated below.
      </p>

      <div class="feature-card">
        <h3>1. &lt;taiyaki-head&gt; Extraction</h3>
        <p>
          This page uses <code>&lt;taiyaki-head&gt;</code> to inject a custom title,
          meta description, and component-scoped CSS into the document head.
          Check the page source to see it in action.
        </p>
      </div>

      <div class="feature-card">
        <h3>2. Island Hydration (with content hashing)</h3>
        <p>Interactive islands below are served with hashed URLs and modulepreload hints.</p>
        <div style="display: flex; gap: 16px; margin-top: 12px; flex-wrap: wrap;"
             dangerouslySetInnerHTML={{ __html: (counterHtml || '') + (toggleHtml || '') }} />
      </div>

      <div class="feature-card">
        <h3>3. React Polyfills</h3>
        <p>
          TextEncoder, TextDecoder, queueMicrotask, and MessageChannel are
          polyfilled in the SSR runtime for React compatibility.
        </p>
      </div>

      <div class="feature-card">
        <h3>4. Logger Middleware</h3>
        <p>Every request is logged with method, path, status, and duration. Check the terminal.</p>
      </div>

      <div class="feature-card">
        <h3>5. Source Maps</h3>
        <p>
          JS errors in components are mapped back to original TSX line numbers
          in the dev overlay.
        </p>
      </div>
    </div>
  );
}
