import { translate, useI18n } from "../../i18n";
import { STEP_COUNT } from "../../state/session";

const STEPS = [
  "step.locate",
  "step.history",
  "step.backtest",
  "step.price",
  "step.term_sheet",
  "step.approval",
] as const;

interface ProgressBarProps {
  /** How many of the six steps are done, as the session counts them from finished tools. */
  step: number;
}

/** The six steps of the flow: one segment each, with the step that comes next named in words. */
export function ProgressBar({ step }: ProgressBarProps) {
  const { locale } = useI18n();
  const next = STEPS[step];
  return (
    <div className="steps">
      <ol className="steps__bar" aria-label={translate(locale, "chat.progress")}>
        {STEPS.map((key, at) => {
          const state = at < step ? "done" : at === step ? "current" : "todo";
          return (
            <li key={key} className="steps__segment" data-state={state}>
              <span className="sr-only">
                {translate(locale, `chat.step.${state}`, { name: translate(locale, key) })}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="steps__label">
        {next === undefined
          ? translate(locale, "chat.steps_done", { count: STEP_COUNT })
          : translate(locale, "chat.step_of", {
              step: step + 1,
              count: STEP_COUNT,
              name: translate(locale, next),
            })}
      </p>
    </div>
  );
}
