
interface AdminLayoutProps {
  children?: any;
}

export default function AdminLayout({ children }: AdminLayoutProps) {
  return (
    <div style="background: #fefce8; border: 2px solid #fde047; border-radius: 8px; padding: 20px;">
      <div style="font-weight: 700; color: #854d0e; margin-bottom: 12px; font-size: 14px;">
        ADMIN AREA
      </div>
      {children}
    </div>
  );
}
