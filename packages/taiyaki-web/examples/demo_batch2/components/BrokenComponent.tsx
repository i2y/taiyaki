
interface BrokenProps {
  message?: string;
}

export default function BrokenComponent({ message }: BrokenProps) {
  // Intentional error on line 9 — source maps should point here
  throw new Error(message || "Intentional error for source map demo");
  return <div>This never renders</div>;
}
