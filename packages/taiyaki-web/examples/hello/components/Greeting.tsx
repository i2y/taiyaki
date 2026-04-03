
interface GreetingProps {
  name: string;
}

export default function Greeting({ name }: GreetingProps) {
  return (
    <div style="padding: 1rem; background: #f0f0f0; border-radius: 8px;">
      <p>Hello <strong>{name}</strong>!</p>
    </div>
  );
}
