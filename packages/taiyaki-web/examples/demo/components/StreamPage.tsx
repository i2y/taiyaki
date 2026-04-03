
export default function StreamPage() {
  return (
    <div>
      <taiyaki-head><title>Streaming SSR</title></taiyaki-head>
      <h1>Streaming SSR</h1>
      <p style="color: #666; margin-bottom: 24px;">
        This page is delivered in chunks, split at stream marker boundaries.
      </p>
      <div style="background: #ecfdf5; border: 2px solid #6ee7b7; border-radius: 8px; padding: 20px; margin-bottom: 12px;">
        <h3 style="color: #065f46; margin: 0;">Chunk 1: Header</h3>
        <p style="color: #047857; margin: 4px 0 0;">Sent immediately — browser starts rendering</p>
      </div>
      <taiyaki-stream-marker />
      <div style="background: #eff6ff; border: 2px solid #93c5fd; border-radius: 8px; padding: 20px; margin-bottom: 12px;">
        <h3 style="color: #1e40af; margin: 0;">Chunk 2: Content</h3>
        <p style="color: #1d4ed8; margin: 4px 0 0;">Main content arrives in second chunk</p>
      </div>
      <taiyaki-stream-marker />
      <div style="background: #fef3c7; border: 2px solid #fcd34d; border-radius: 8px; padding: 20px;">
        <h3 style="color: #92400e; margin: 0;">Chunk 3: Footer</h3>
        <p style="color: #b45309; margin: 4px 0 0;">Final chunk with hydration scripts</p>
      </div>
    </div>
  );
}
