
interface Feature {
  icon: string;
  name: string;
  desc: string;
}

interface HomeProps {
  title: string;
  visits: number;
  features: Feature[];
}

export default function Home({ title, visits, features }: HomeProps) {
  return (
    <div>
      <taiyaki-head>
        <title>{title}</title>
        <meta name="description" content="Taiyaki Web Framework Demo" />
      </taiyaki-head>
      <h1 style="font-size: 36px; margin-bottom: 8px;">{title}</h1>
      <p style="color: #666; font-size: 18px; margin-bottom: 24px;">
        Session visits: {visits}
      </p>
      <h2 style="font-size: 20px; margin-bottom: 12px;">Features</h2>
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px;">
        {features.map((f) => (
          <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 16px;">
            <div style="font-size: 24px; margin-bottom: 4px;">{f.icon}</div>
            <div style="font-weight: 600;">{f.name}</div>
            <div style="color: #666; font-size: 13px; margin-top: 4px;">{f.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
