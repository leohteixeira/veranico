# Next steps

What was deliberately left out of Veranico, with the reason. The scope is locked in `docs/SPEC.md`; anything not in the spec is listed here instead of going into code. Ideas that come up during the build are added to this file, each with one line of reason.

## Non-goals of the specification (SPEC section 1)

* **Real actuarial pricing.** The pricing is illustrative and is not actuarial or insurance advice; the interface, the term sheet and the README say so.
* **Real carriers.** The carrier directory is a fixed list of mock carriers; the mock carrier exists to prove signed, retried delivery (ADR 0013), not to integrate with a market.
* **User accounts.** Creating an account is friction for an evaluator with a few minutes; an anonymous workspace per browser gives the isolation that is needed (ADR 0007).
* **Multi-tenancy.** There are no organisations or shared workspaces; isolation stops at the anonymous browser workspace (ADR 0007).
* **Forecasting.** The product backtests and prices from ERA5-Land history; it makes no statement about future weather.
* **More perils and index types.** The scope is rainfall deficit (`rainfall_below`) and dry spells (`dry_spell_above`); every index added needs its own pure functions, hand-computed tests and mutants.
* **Retrieval over documents (RAG).** There is no document corpus; every fact the agent states comes from a tool result (ADR 0004).
* **Paid alerting.** Operations are limited to what is free: an uptime check on `/healthz` and a billing budget with email alerts (SPEC section 15).

## Rejected for now or left for later

* **Reference evapotranspiration.** The brief ingested it next to precipitation; neither index uses it, so it is not ingested. It comes back with an index that needs it (for example a water-balance index).
* **Custom domain mapping.** The address is the Cloud Run URL first; `veranico.leohteixeira.com` is an optional later mapping (SPEC section 17).
* **Mobile-first layout.** The layout is laptop first; on narrow screens the same pieces stack and mobile is best effort (SPEC section 12.1).
* **Commercial tile licence.** Sentinel-2 cloudless imagery after 2016 is CC BY-NC-SA 4.0, so the demo is non-commercial; a commercial use needs another satellite layer or a licence (ADR 0011).

## Not in this list

Open human gates are not omissions and are tracked in the goal contract (`docs/veranico/goal.md` in the workspace repository): the three real cubes and ADR 0016 (chunking) need a Copernicus CDS account; the deployment needs a Google Cloud project.
