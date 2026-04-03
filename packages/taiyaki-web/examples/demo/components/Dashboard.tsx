
interface Stat {
  label: string;
  value: string;
}

interface DashboardProps {
  user: string;
  stats: Stat[];
}

export default function Dashboard({ user, stats }: DashboardProps) {
  return (
    <div>
      <taiyaki-head><title>Admin Dashboard</title></taiyaki-head>
      <h1>Admin Dashboard</h1>
      <p>Welcome back, <strong>{user}</strong>!</p>
      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 16px;">
        {stats.map((s) => (
          <div style="background: white; border-radius: 8px; padding: 16px; text-align: center;">
            <div style="font-size: 28px; font-weight: 700; color: #7c3aed;">{s.value}</div>
            <div style="font-size: 13px; color: #666;">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
