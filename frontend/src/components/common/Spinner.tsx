import "./common.css";

interface SpinnerProps {
  /** With a label the spinner is announced as a status; without one it is decorative. */
  label?: string;
}

export function Spinner({ label }: SpinnerProps) {
  if (label === undefined) {
    return <span className="spin" aria-hidden="true" />;
  }
  return (
    <span role="status">
      <span className="spin" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  );
}
