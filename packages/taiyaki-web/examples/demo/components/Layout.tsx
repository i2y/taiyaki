
interface LayoutProps {
  children?: any;
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div style="font-family: -apple-system, system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
      <nav style="display: flex; gap: 16px; padding: 16px 0; border-bottom: 2px solid #7c3aed; margin-bottom: 24px; flex-wrap: wrap; align-items: center;">
        <a href="/" style="text-decoration: none; font-weight: 700; font-size: 20px; color: #7c3aed;">Taiyaki</a>
        <a href="/" style="text-decoration: none; color: #666;">Home</a>
        <a href="/islands" style="text-decoration: none; color: #666;">Islands</a>
        <a href="/streaming" style="text-decoration: none; color: #666;">Streaming</a>
        <a href="/cached" style="text-decoration: none; color: #666;">Cache</a>
        <a href="/admin/dashboard" style="text-decoration: none; color: #666;">Admin</a>
        <a href="/form" style="text-decoration: none; color: #666;">Form</a>
        <a href="/user/alice" style="text-decoration: none; color: #666;">Profile</a>
      </nav>
      <main>{children}</main>
      <footer style="margin-top: 40px; padding: 16px 0; border-top: 1px solid #eee; color: #999; font-size: 14px;">
        Powered by Taiyaki — Preact SSR + htmx + Islands
      </footer>
    </div>
  );
}
