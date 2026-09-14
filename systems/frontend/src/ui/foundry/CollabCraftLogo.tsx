export function CollabCraftLogo({ className = "" }: { className?: string }) {
  return (
    <img
      className={`collabcraft-logo ${className}`.trim()}
      src={`${import.meta.env.BASE_URL}collabcraft-logo.png`}
      alt="CollabCraft"
      draggable={false}
    />
  );
}
