/**
 * English catalogue: the source of the message keys. `pt-BR.ts` must define exactly the same
 * keys, so a missing translation is a type error.
 *
 * `{name}` is a parameter. A key that is an API code (`problem.<code>`, `audit.<action>`,
 * `tool.<name>`, `assumption.<name>`, `warning.<name>`) may have `.alt` and `.plain` variants:
 * `translateCoded` uses the first variant whose parameters are all present.
 */
export const en = {
  // Product
  "app.name": "Veranico",
  "app.disclaimer": "Pricing is illustrative. It is not actuarial or insurance advice.",
  "app.non_commercial": "Non-commercial demo.",
  "app.weather_attribution":
    "Weather: Copernicus Climate Change Service. ERA5-Land for the regional cubes; ERA5 through Open-Meteo for any other point. CC BY 4.0.",
  "app.synthetic":
    "Synthetic weather data: these figures are generated for the demo and are not weather history.",

  // Map
  "map.label": "Map of {region}",
  "map.label_empty": "Map",
  "map.basemap_failed": "The basemap did not load. The risk layer is still shown.",
  "map.basemap_retry": "Load it again",
  "map.farm": "Farm",
  "map.cube": "Weather grid: {count} cells of {step}°",
  "map.smoothing":
    "The colour is smoothed between cell centres for reading only. The data is one value per cell.",
  "map.synthetic": "Synthetic weather data, not weather history",
  "map.outside_showcase":
    "This point is outside the showcase regions. Its own grid cell is outlined; the regional view exists only inside them.",
  "map.cell.frequency": "Pays in {rate} of seasons",
  "map.cell.anomaly": "{anomaly} against its median",
  "map.cell.no_value": "No value for this cell",
  "map.cell.distance": "{distance} from the farm",
  "compass.north": "N",
  "compass.south": "S",
  "compass.east": "E",
  "compass.west": "W",
  "basemap.label": "Basemap",
  "basemap.relief": "Relief",
  "basemap.satellite": "Satellite",
  "attribution.label": "Sources and licences",
  "attribution.basemap": "Basemap:",

  // Languages and themes
  "language.label": "Language",
  "language.en": "English",
  "language.pt-BR": "Português",
  "theme.label": "Theme",
  "theme.light": "Light",
  "theme.dark": "Dark",

  // Regions
  "region.label": "Region",
  "crop.coffee": "Coffee",
  "crop.soybean": "Soybean",
  "crop.sugarcane": "Sugarcane",

  // Units
  "unit.mm": "{value} mm",
  "unit.day": "{value} day",
  "unit.days": "{value} days",
  "unit.km": "{value} km",
  "unit.ms": "{value} ms",

  // The six steps of the flow
  "step.locate": "Locate",
  "step.history": "History",
  "step.backtest": "Backtest",
  "step.price": "Price",
  "step.term_sheet": "Term sheet",
  "step.approval": "Approval",

  // Tool names, as labels beside the identifier
  "toolname.resolve_location": "Resolve the location",
  "toolname.get_weather_history": "Load the weather history",
  "toolname.backtest_index": "Backtest the index",
  "toolname.price_cover": "Price the cover",
  "toolname.find_extreme_seasons": "Find the worst seasons",
  "toolname.draft_term_sheet": "Draft the term sheet",
  "toolname.request_submission": "Request the submission",

  // Index, method, metric and data source names
  "index.rainfall_below": "rainfall below a trigger",
  "index.dry_spell_above": "dry spell above a trigger",
  "method.gamma_mle": "Gamma distribution fitted to the seasonal totals",
  "method.bootstrap": "Bootstrap of the historical seasons",
  "direction.increasing": "rising",
  "direction.decreasing": "falling",
  "metric.trigger_frequency": "Trigger frequency",
  "metric.season_anomaly": "Season anomaly",
  "source.era5-land/cds": "ERA5-Land, Copernicus Climate Data Store",
  "source.era5/open-meteo": "ERA5, Open-Meteo",
  "source.synthetic": "synthetic cube (generated for the demo, not weather history)",

  // Quote, approval and delivery states
  "status.quote.draft": "Draft",
  "status.quote.pending_approval": "Pending approval",
  "status.quote.approved": "Approved",
  "status.quote.rejected": "Rejected",
  "status.quote.submitted": "Submitted",
  "status.approval.pending": "Pending",
  "status.approval.approved": "Approved",
  "status.approval.rejected": "Rejected",
  "status.delivery.not_started": "Not sent",
  "status.delivery.delivering": "Delivering",
  "status.delivery.delivered": "Delivered",
  "status.delivery.abandoned": "Delivery abandoned",

  // Actors of the audit trail
  "actor.agent": "Agent",
  "actor.human": "You",
  "actor.api_client": "API client",
  "actor.system": "System",
  "actor.carrier": "Carrier",

  // Why the live agent is or is not available
  "admission.ok": "The live agent is available.",
  "admission.visitor_allowance": "Today's allowance for the live agent is used.",
  "admission.day_ceiling": "The demo reached its spend ceiling for today.",
  "admission.month_ceiling": "The demo reached its spend ceiling for this month.",

  // How a turn ended
  "stop.end_turn": "The agent finished its answer.",
  "stop.tool_limit":
    "The agent reached the limit of tool calls for one request. Send a message to continue.",
  "stop.budget": "This conversation reached its budget. Start over to continue.",
  "stop.error": "The answer was interrupted.",

  // Problem codes (RFC 9457 `code`); the API's English prose is never shown
  "problem.not_found": "Not found. It may have expired or belong to another workspace.",
  "problem.forbidden": "This action is not allowed here.",
  "problem.invalid_arguments": "The request has a missing or invalid value.",
  "problem.conflict": "This conflicts with the current state. Reload and try again.",
  "problem.rate_limited": "Too many requests. Wait a moment and try again.",
  "problem.allowance_exhausted": "Today's allowance for the live agent is used.",
  "problem.spend_ceiling_reached": "The demo reached its spend ceiling for the live agent.",
  "problem.outside_coverage": "This point is outside the area the weather data covers.",
  "problem.location_not_found": "No place in Brazil matches that name.",
  "problem.location_ambiguous": "Several places match that name. Choose one.",
  "problem.weather_source_unavailable": "The weather source did not answer. Try again in a moment.",
  "problem.dataset_not_found": "There is no weather history loaded for this point yet.",
  "problem.invalid_cover":
    "The cover is not valid. Check the window, the trigger, the exit and the limit.",
  "problem.insufficient_history": "There are fewer than 20 complete seasons for this window.",
  "problem.invalid_state": "The quote is not in a state that allows this.",
  "problem.idempotency_conflict": "This idempotency key was already used with another request.",
  "problem.unknown_carrier": "That carrier is not in the directory.",
  "problem.delivery_failed": "The carrier could not be reached.",
  "problem.model_unavailable": "The agent is unavailable right now. Try again in a moment.",
  "problem.message_too_long": "The message is too long. Shorten it and send again.",
  "problem.not_implemented": "This part of the service is not available yet.",
  "problem.shutting_down": "The service restarted during the answer. Send the message again.",
  // Two codes of the interface itself, for a failure that carries no problem document
  "problem.network": "The service could not be reached. Check the connection and try again.",
  "problem.unknown": "The request failed. Try again in a moment.",
  "error.reference": "Reference {trace_id}",

  // Audit actions
  "audit.quote_created": "Quote created as a draft",
  "audit.term_sheet_rendered": "Term sheet rendered ({locale})",
  "audit.term_sheet_rendered.plain": "Term sheet rendered",
  "audit.submission_requested": "Submission requested for {carrier_id}",
  "audit.submission_requested.plain": "Submission requested",
  "audit.approved": "Approved",
  "audit.rejected": "Rejected",
  "audit.webhook_attempt": "Webhook attempt {attempt}: the carrier answered {status_code}",
  "audit.webhook_attempt.alt": "Webhook attempt {attempt} failed: {error_code}",
  "audit.webhook_attempt.plain": "Webhook attempt",
  "audit.receipt_recorded": "Receipt {receipt_id} recorded; quote submitted",
  "audit.receipt_recorded.plain": "Receipt recorded; quote submitted",
  "audit.delivery_abandoned": "Delivery abandoned after {attempts} attempts",
  "audit.delivery_abandoned.plain": "Delivery abandoned",
  "audit.redelivery_requested": "Redelivery requested",

  // Tool summaries
  "tool.resolve_location": "{label}",
  "tool.resolve_location.plain": "Location resolved",
  "tool.resolve_location.candidates": "{count} possible places",
  "tool.resolve_location.candidates.plain": "Several possible places",
  "tool.get_weather_history": "{dataset_id} · {first_year} to {last_year}",
  "tool.get_weather_history.plain": "History loaded",
  "tool.backtest_index": "{seasons_used} seasons · pays in {trigger_frequency_rate}",
  "tool.backtest_index.plain": "Backtest done",
  "tool.price_cover": "{quote_id} · premium {premium_cents}",
  "tool.price_cover.plain": "Cover priced",
  "tool.find_extreme_seasons": "{count} seasons",
  "tool.find_extreme_seasons.plain": "Worst seasons found",
  "tool.draft_term_sheet": "Term sheet drafted in English and Portuguese",
  "tool.request_submission": "{submission_id} · waiting for approval",
  "tool.request_submission.plain": "Submission requested; waiting for approval",
  "tool.error": "Failed: {error_code}",
  "tool.error.plain": "Failed",

  // Pricing warnings and assumptions
  "warning.trend_significant":
    "The index has a significant {direction} trend of {slope_per_decade} per decade. History may misstate current risk.",
  "warning.trend_significant.plain":
    "The index has a significant trend. History may misstate current risk.",
  "warning.seasons_excluded": "Seasons excluded for incomplete data ({count}): {seasons}.",
  "warning.seasons_excluded.plain": "Some seasons were excluded for incomplete data.",
  "assumption.index_type": "Index: {index_type}.",
  "assumption.window":
    "Coverage window from {start} to {end}; a season is labelled by its start year.",
  "assumption.seasons_used": "{seasons_used} seasons used, {first_season} to {last_season}.",
  "assumption.simulation_method": "{method}; {n} simulated seasons; seed {seed}.",
  "assumption.loads":
    "Risk load of {risk_load_rate} on the standard deviation; expense load of {expense_load_rate} on the expected loss.",
  "assumption.data_source": "Weather data: {source}.",
} as const;

export type MessageKey = keyof typeof en;

/** Every catalogue has exactly the keys of the English one. */
export type Messages = Record<MessageKey, string>;
