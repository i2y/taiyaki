
interface CachedPageProps {
  rendered_at: string;
  render_count: string;
}

export default function CachedPage({ rendered_at, render_count }: CachedPageProps) {
  return (
    <div>
      <taiyaki-head><title>Cache Demo</title></taiyaki-head>
      <h1>LRU Cache + ETag</h1>
      <p style="color: #666; margin-bottom: 24px;">
        This page is cached. Reload to see the same render_count.
      </p>
      <div style="background: #faf5ff; border: 2px solid #c084fc; border-radius: 8px; padding: 20px;">
        <p><strong>Rendered at: </strong>{rendered_at}</p>
        <p><strong>Render count: </strong>{render_count}</p>
        <p style="color: #7c3aed; font-size: 14px; margin-top: 12px;">
          The loader only runs once. Subsequent requests hit the cache. Check the ETag header!
        </p>
      </div>
    </div>
  );
}
