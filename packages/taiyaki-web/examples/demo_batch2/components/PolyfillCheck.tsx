
export default function PolyfillCheck() {
  const checks = [
    { name: "TextEncoder", ok: typeof TextEncoder !== "undefined" },
    { name: "TextDecoder", ok: typeof TextDecoder !== "undefined" },
    { name: "queueMicrotask", ok: typeof queueMicrotask !== "undefined" },
    { name: "MessageChannel", ok: typeof MessageChannel !== "undefined" },
  ];

  // Verify TextEncoder actually works
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  const roundtrip = decoder.decode(encoder.encode("dark-python"));

  return (
    <div>
      <taiyaki-head>
        <title>Polyfill Check</title>
      </taiyaki-head>
      <h2>SSR Polyfill Status</h2>
      <table style="border-collapse: collapse; width: 100%;">
        <thead>
          <tr style="border-bottom: 2px solid #7c3aed;">
            <th style="text-align: left; padding: 8px;">API</th>
            <th style="text-align: left; padding: 8px;">Status</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => (
            <tr style="border-bottom: 1px solid #eee;">
              <td style="padding: 8px; font-family: monospace;">{c.name}</td>
              <td style="padding: 8px;">{c.ok ? "Available" : "Missing"}</td>
            </tr>
          ))}
          <tr style="border-bottom: 1px solid #eee;">
            <td style="padding: 8px; font-family: monospace;">TextEncoder roundtrip</td>
            <td style="padding: 8px;">{roundtrip === "dark-python" ? "OK" : "FAIL"}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
