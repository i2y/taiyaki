
interface LayoutProps {
  children?: any;
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div style="font-family: -apple-system, system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 24px;">
      <nav style="display: flex; align-items: center; gap: 12px; padding: 16px 0; border-bottom: 2px solid #7c3aed; margin-bottom: 32px;">
        <span style="font-size: 24px; font-weight: 800; color: #7c3aed;">Dark</span>
        <span style="color: #666; font-size: 14px;">Batch 2 Demo</span>
      </nav>
      <main>{children}</main>
      <footer style="margin-top: 48px; padding-top: 16px; border-top: 1px solid #eee; color: #999; font-size: 13px;">
        Powered by Dark + Preact SSR + libts
      </footer>
    </div>
  );
}
