
interface IndexProps {
  counter?: string;
  greeting?: string;
}

export default function Index({ counter, greeting }: IndexProps) {
  return (
    <div style="max-width: 600px; margin: 2rem auto; font-family: sans-serif;">
      <taiyaki-head>
        <title>Hello Taiyaki</title>
      </taiyaki-head>
      <h1>Hello Taiyaki!</h1>
      <p>Preact SSR + htmx + Islands</p>
      <hr />
      <h2>Island Component (interactive)</h2>
      <div dangerouslySetInnerHTML={{ __html: counter || "" }} />
      <hr />
      <h2>Static Component (no client JS)</h2>
      <div dangerouslySetInnerHTML={{ __html: greeting || "" }} />
      <hr />
      <h2>htmx Partial</h2>
      <button hx-get="/api/time" hx-target="#time-display" hx-swap="innerHTML">
        Get Server Time
      </button>
      <div id="time-display" style="margin-top: 1rem;" />
    </div>
  );
}
