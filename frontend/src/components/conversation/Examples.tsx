import { translate, useI18n } from "../../i18n";
import type { ExampleRequest } from "./exampleRequests";

interface ExamplesProps {
  examples: readonly ExampleRequest[];
  onPick: (text: string) => void;
  disabled?: boolean;
}

/** The first run: what to write, and example requests that are sent with one click. */
export function Examples({ examples, onPick, disabled = false }: ExamplesProps) {
  const { locale } = useI18n();
  return (
    <div className="first">
      <h3 className="first__title">{translate(locale, "chat.first.title")}</h3>
      <p className="first__body">{translate(locale, "chat.first.body")}</p>
      <ul className="first__examples">
        {examples.map((example) => (
          <li key={example.id}>
            <button
              type="button"
              className="first__example"
              disabled={disabled}
              onClick={() => {
                onPick(example.text);
              }}
            >
              <b>{example.title}</b>
              {example.text}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
