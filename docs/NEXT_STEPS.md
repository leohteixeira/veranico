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
* **README section "What I would change".** Deferred by the owner's decision (2026-11-12); the author writes it from real experience after the build, never generated.
* **Commercial tile licence.** Sentinel-2 cloudless imagery after 2016 is CC BY-NC-SA 4.0, so the demo is non-commercial; a commercial use needs another satellite layer or a licence (ADR 0011).

## Found during the build

Each item was noticed while building or reviewing and is outside the locked scope.

Interface:

* **Place names and a label on the cube frame.** The finish review asked for them; the approved direction draws the map without labels.
* **A jump to the conversation in the stacked layout.** At 390 px the conversation sits far below the map; the specification fixes that order.
* **One authored moment of motion on the risk surface.** The review asked for it; the specification asks for none.
* **Map notes on narrow screens.** At 390 px the notes card covers the lower part of the fitted region.
* **Smaller first load.** The main bundle is over 500 kB; the tabs (charts) and the map can be split.
* **Map cells by keyboard.** Cells are reachable through the Risk tab's neighbourhood, not on the map itself.
* **Empty conversation with an exhausted allowance.** The list area is blank; it could explain the replay.
* **A quote opened from the approval queue** does not move the map to its cover.
* **The point chip.** Every map click adds the removable point to the composer.
* **Timeline width.** Between 1100 and 1240 px with a wide tab open the timeline is about 300 px wide.
* **Basemap fallback.** When EOX tiles are rate limited the interface only says the basemap did not load; a tile service with an agreed quota removes the risk.
* **Narration before tool calls.** The model writes a sentence before most tool calls although the prompt asks it not to; withholding the text of a step that ends in a tool call would hide it, and changes what the stream shows.
* **Percentages as display text for the model.** Money reaches the model with a locale display string; rates still arrive as six-decimal fractions, and the model sometimes repeats the fraction in parentheses after the percentage (grounded, cosmetic; seen in one of two English takes after the fix).
* **Markdown in answers.** The prompt asks for plain text; a count of answers with Markdown marks per evaluation run would show whether the model complies.

Backend:

* **A public place-name lookup route.** The agent resolves a place name through `resolve_location`; the public API of SPEC 11 takes coordinates only, which is the one exception to SPEC 3.2 that the tests name.
* **Per-season index values kept between requests.** They are recomputed from the kept cube on each uncached request; the load campaign passes without a second cache.
* **Memory headroom of the API role.** With the three cubes decoded the API peaks at about 958 MiB of its 1 GiB limit under the load campaign. A fourth region needs a larger instance or a smaller cache (`VERANICO_CLIMATE__CUBE_CACHE_SIZE`).
* **Memory figures in the stored load result.** They were read from the containers by hand; the runner does not record them.
* **Retry of a failed audit entry after a document was written.** The entry is not retried today; the document itself is safe.
* **Rendering off the request.** The term sheet renders synchronously; a queue is not justified at this size.
* **Closing the model client at shutdown.** The connection pool of the Anthropic client is not closed; the process ends anyway.
* **Caching the growing message history.** Only the stable prefix (tools and system prompt) is cached; a second breakpoint would save tokens in long tool loops.
* **Plain-language answers from the scripted model client.** `make dev` without a key still writes the source code, the simulation method value and the submission id; only the live model's prompt (v4) was tightened.
* **A provenance label that names the download path.** The frozen source value `era5-land/cds` predates ADR 0019 (cubes from Google Earth Engine); a new value needs a contract change.
* **401 on the internal routes.** A missing or wrong service token still answers 403 `forbidden`; only the public API distinguishes 401 from 403.
* **Grid point coordinates on the term sheet.** The stored quote carries the dataset id but not the grid point, so the term sheet names the dataset kind only; printing the coordinates needs the grid point on `QuoteView` (a contract change).
* **The term sheet in the compose smoke test.** The clean-copy smoke test checks health only; rendering a term sheet would have caught the unwritable data root.

## Not in this list

Open human gates are not omissions and are tracked in the goal contract (`docs/veranico/goal.md` in the workspace repository): the deployment needs the Google Cloud project, and with it the real cubes go to Cloud Storage (README section 8). Human gate H1, the three real cubes and ADR 0016 (chunking), closed on 2026-11-11 with a Cloud project registered for Google Earth Engine (ADR 0019).
