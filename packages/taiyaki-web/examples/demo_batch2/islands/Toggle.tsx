import { useState } from "preact/hooks";

interface ToggleProps {
  label?: string;
}

export default function Toggle({ label = "Dark Mode" }: ToggleProps) {
  const [on, setOn] = useState(false);
  return (
    <button
      onClick={() => setOn(!on)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "8px",
        background: on ? "#1a1a2e" : "#e8e0f0",
        color: on ? "#fff" : "#333",
        border: "none",
        padding: "10px 18px",
        borderRadius: "10px",
        cursor: "pointer",
        fontWeight: 600,
        fontSize: "14px",
        transition: "all 0.2s",
      }}
    >
      <span style="font-size: 18px;">{on ? "\u25CF" : "\u25CB"}</span>
      {label}: {on ? "ON" : "OFF"}
    </button>
  );
}
