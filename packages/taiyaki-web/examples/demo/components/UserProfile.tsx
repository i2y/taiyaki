
interface UserProfileProps {
  user: { name: string; email: string; role: string };
  posts: { title: string; date: string }[];
  stats: { followers: number; following: number };
}

export default function UserProfile({ user, posts, stats }: UserProfileProps) {
  return (
    <div>
      <taiyaki-head><title>{user.name}'s Profile</title></taiyaki-head>
      <h1>{user.name}</h1>
      <p style="color: #666;">{user.email} — {user.role}</p>

      <div style="display: flex; gap: 24px; margin: 20px 0;">
        <div style="background: #f3f4f6; border-radius: 8px; padding: 16px; text-align: center; flex: 1;">
          <div style="font-size: 24px; font-weight: 700; color: #7c3aed;">{stats.followers}</div>
          <div style="font-size: 13px; color: #666;">Followers</div>
        </div>
        <div style="background: #f3f4f6; border-radius: 8px; padding: 16px; text-align: center; flex: 1;">
          <div style="font-size: 24px; font-weight: 700; color: #7c3aed;">{stats.following}</div>
          <div style="font-size: 13px; color: #666;">Following</div>
        </div>
      </div>

      <h2 style="font-size: 18px; margin-top: 24px;">Recent Posts</h2>
      <ul style="list-style: none; padding: 0;">
        {posts.map((p) => (
          <li style="padding: 12px 0; border-bottom: 1px solid #eee;">
            <div style="font-weight: 600;">{p.title}</div>
            <div style="font-size: 13px; color: #999;">{p.date}</div>
          </li>
        ))}
      </ul>

      <p style="margin-top: 24px; padding: 12px; background: #f0f9ff; border-radius: 8px; font-size: 13px; color: #1e40af;">
        This page uses <code>loader</code> + <code>loaders</code> to fetch user, posts, and stats concurrently.
      </p>
    </div>
  );
}
