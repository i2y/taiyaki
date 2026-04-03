import { useState } from "preact/hooks";

interface CounterProps {
  initial?: number;
  label?: string;
}

export default function Counter({ initial = 0, label = "Count" }: CounterProps) {
  const [count, setCount] = useState(initial);
  return (
    <div style="display: inline-flex; align-items: center; gap: 8px; background: #7c3aed; color: white; padding: 10px 18px; border-radius: 10px;">
      <span style="font-weight: 600;">{label}</span>
      <button
        onClick={() => setCount(count - 1)}
        style="background: rgba(255,255,255,0.2); border: none; color: white; width: 30px; height: 30px; border-radius: 50%; cursor: pointer; font-size: 16px;"
      >
        -
      </button>
      <span style="min-width: 36px; text-align: center; font-size: 22px; font-weight: 700;">
        {count}
      </span>
      <button
        onClick={() => setCount(count + 1)}
        style="background: rgba(255,255,255,0.2); border: none; color: white; width: 30px; height: 30px; border-radius: 50%; cursor: pointer; font-size: 16px;"
      >
        +
      </button>
    </div>
  );
}
