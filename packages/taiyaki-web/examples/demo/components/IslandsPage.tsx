
interface IslandsPageProps {
  counters: string;
}

export default function IslandsPage({ counters }: IslandsPageProps) {
  return (
    <div>
      <taiyaki-head><title>Islands Demo</title></taiyaki-head>
      <h1>Islands Architecture</h1>
      <p style="color: #666; margin-bottom: 24px;">
        Each counter is an interactive island — SSR'd on server, hydrated on client.
      </p>
      <div
        style="display: flex; flex-direction: column; gap: 16px;"
        dangerouslySetInnerHTML={{ __html: counters }}
      />
      <div style="margin-top: 24px; padding: 16px; background: #f0f9ff; border-radius: 8px; font-size: 14px; color: #1e40af;">
        Islands are individually hydrated — the rest of the page stays static HTML.
      </div>
    </div>
  );
}
