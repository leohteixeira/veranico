export interface Field {
  /** The key a figure link uses to point at this field. */
  field: string;
  label: string;
  /** Already formatted from the API's value. */
  value: string;
}

interface FieldListProps {
  fields: readonly Field[];
  /** The field a figure link asked the tab to highlight. */
  highlight?: string | null;
  label?: string;
}

/** Labelled values of the API, one per row; a figure link can highlight one of them. */
export function FieldList({ fields, highlight = null, label }: FieldListProps) {
  return (
    <dl className="fields" aria-label={label}>
      {fields.map((item) => (
        <div
          key={item.field}
          className="fields__row"
          data-field={item.field}
          data-highlight={highlight === item.field ? "true" : undefined}
        >
          <dt>{item.label}</dt>
          <dd className="num">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
