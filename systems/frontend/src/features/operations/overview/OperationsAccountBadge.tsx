export function OperationsAccountBadge({ displayName, title }: { displayName: string; title: string }) {
  return <span className="engineer-current-user" role="group" aria-label="로그인 계정">
    <b>{displayName}</b>
    <small>{title}</small>
  </span>;
}
