import type { Messages } from "./en";

/** Brazilian Portuguese catalogue. Its type forces the same keys as `en.ts`. */
export const ptBR: Messages = {
  // Product
  "app.name": "Veranico",
  "app.disclaimer": "O preço é ilustrativo. Não é cálculo atuarial nem recomendação de seguro.",
  "app.non_commercial": "Demonstração sem fins comerciais.",
  "app.weather_attribution":
    "Clima: Copernicus Climate Change Service. ERA5-Land nos cubos regionais; ERA5 via Open-Meteo em qualquer outro ponto. CC BY 4.0.",
  "app.synthetic":
    "Dados climáticos sintéticos: estes números foram gerados para a demonstração e não são histórico de clima.",

  // Map
  "map.label": "Mapa de {region}",
  "map.label_empty": "Mapa",
  "map.basemap_failed": "O mapa de base não carregou. A camada de risco continua visível.",
  "map.basemap_retry": "Carregar de novo",
  "basemap.label": "Mapa de base",
  "basemap.relief": "Relevo",
  "basemap.satellite": "Satélite",
  "attribution.label": "Fontes e licenças",
  "attribution.basemap": "Mapa de base:",

  // Languages and themes
  "language.label": "Idioma",
  "language.en": "English",
  "language.pt-BR": "Português",
  "theme.label": "Tema",
  "theme.light": "Claro",
  "theme.dark": "Escuro",

  // Regions
  "region.label": "Região",
  "crop.coffee": "Café",
  "crop.soybean": "Soja",
  "crop.sugarcane": "Cana-de-açúcar",

  // Units
  "unit.mm": "{value} mm",
  "unit.day": "{value} dia",
  "unit.days": "{value} dias",
  "unit.km": "{value} km",
  "unit.ms": "{value} ms",

  // The six steps of the flow
  "step.locate": "Localizar",
  "step.history": "Histórico",
  "step.backtest": "Backtest",
  "step.price": "Preço",
  "step.term_sheet": "Term sheet",
  "step.approval": "Aprovação",

  // Tool names, as labels beside the identifier
  "toolname.resolve_location": "Resolver o local",
  "toolname.get_weather_history": "Carregar o histórico de clima",
  "toolname.backtest_index": "Fazer o backtest do índice",
  "toolname.price_cover": "Precificar a cobertura",
  "toolname.find_extreme_seasons": "Buscar as piores safras",
  "toolname.draft_term_sheet": "Gerar o term sheet",
  "toolname.request_submission": "Solicitar a submissão",

  // Index, method, metric and data source names
  "index.rainfall_below": "chuva abaixo de um gatilho",
  "index.dry_spell_above": "veranico acima de um gatilho",
  "method.gamma_mle": "Distribuição gama ajustada aos totais por safra",
  "method.bootstrap": "Bootstrap das safras históricas",
  "direction.increasing": "de alta",
  "direction.decreasing": "de queda",
  "metric.trigger_frequency": "Frequência de gatilho",
  "metric.season_anomaly": "Anomalia da safra",
  "source.era5-land/cds": "ERA5-Land, Copernicus Climate Data Store",
  "source.era5/open-meteo": "ERA5, Open-Meteo",
  "source.synthetic": "cubo sintético (gerado para a demonstração, não é histórico de clima)",

  // Quote, approval and delivery states
  "status.quote.draft": "Rascunho",
  "status.quote.pending_approval": "Aguardando aprovação",
  "status.quote.approved": "Aprovada",
  "status.quote.rejected": "Rejeitada",
  "status.quote.submitted": "Submetida",
  "status.approval.pending": "Pendente",
  "status.approval.approved": "Aprovada",
  "status.approval.rejected": "Rejeitada",
  "status.delivery.not_started": "Não enviada",
  "status.delivery.delivering": "Entregando",
  "status.delivery.delivered": "Entregue",
  "status.delivery.abandoned": "Entrega abandonada",

  // Actors of the audit trail
  "actor.agent": "Agente",
  "actor.human": "Você",
  "actor.api_client": "Cliente da API",
  "actor.system": "Sistema",
  "actor.carrier": "Seguradora",

  // Why the live agent is or is not available
  "admission.ok": "O agente ao vivo está disponível.",
  "admission.visitor_allowance": "A cota de hoje para o agente ao vivo acabou.",
  "admission.day_ceiling": "A demonstração atingiu o teto de gasto de hoje.",
  "admission.month_ceiling": "A demonstração atingiu o teto de gasto deste mês.",

  // How a turn ended
  "stop.end_turn": "O agente concluiu a resposta.",
  "stop.tool_limit":
    "O agente atingiu o limite de chamadas de ferramenta por pedido. Envie uma mensagem para continuar.",
  "stop.budget": "Esta conversa atingiu o orçamento. Recomece para continuar.",
  "stop.error": "A resposta foi interrompida.",

  // Problem codes (RFC 9457 `code`); the API's English prose is never shown
  "problem.not_found": "Não encontrado. Pode ter expirado ou pertencer a outro workspace.",
  "problem.forbidden": "Esta ação não é permitida aqui.",
  "problem.invalid_arguments": "O pedido tem um valor ausente ou inválido.",
  "problem.conflict": "Isso conflita com o estado atual. Recarregue e tente de novo.",
  "problem.rate_limited": "Muitos pedidos. Aguarde um instante e tente de novo.",
  "problem.allowance_exhausted": "A cota de hoje para o agente ao vivo acabou.",
  "problem.spend_ceiling_reached": "A demonstração atingiu o teto de gasto do agente ao vivo.",
  "problem.outside_coverage": "Este ponto está fora da área coberta pelos dados de clima.",
  "problem.location_not_found": "Nenhum lugar no Brasil corresponde a esse nome.",
  "problem.location_ambiguous": "Vários lugares correspondem a esse nome. Escolha um.",
  "problem.weather_source_unavailable":
    "A fonte de dados de clima não respondeu. Tente de novo em instantes.",
  "problem.dataset_not_found": "Ainda não há histórico de clima carregado para este ponto.",
  "problem.invalid_cover":
    "A cobertura não é válida. Confira a janela, o gatilho, a saída e o limite.",
  "problem.insufficient_history": "Há menos de 20 safras completas para esta janela.",
  "problem.invalid_state": "A cotação não está em um estado que permita isso.",
  "problem.idempotency_conflict": "Esta chave de idempotência já foi usada com outro pedido.",
  "problem.unknown_carrier": "Essa seguradora não está no diretório.",
  "problem.delivery_failed": "Não foi possível contatar a seguradora.",
  "problem.model_unavailable": "O agente está indisponível agora. Tente de novo em instantes.",
  "problem.message_too_long": "A mensagem é longa demais. Encurte e envie de novo.",
  "problem.not_implemented": "Esta parte do serviço ainda não está disponível.",
  "problem.shutting_down": "O serviço reiniciou durante a resposta. Envie a mensagem de novo.",
  // Two codes of the interface itself, for a failure that carries no problem document
  "problem.network": "Não foi possível contatar o serviço. Verifique a conexão e tente de novo.",
  "problem.unknown": "O pedido falhou. Tente de novo em instantes.",
  "error.reference": "Referência {trace_id}",

  // Audit actions
  "audit.quote_created": "Cotação criada como rascunho",
  "audit.term_sheet_rendered": "Term sheet gerado ({locale})",
  "audit.term_sheet_rendered.plain": "Term sheet gerado",
  "audit.submission_requested": "Submissão solicitada para {carrier_id}",
  "audit.submission_requested.plain": "Submissão solicitada",
  "audit.approved": "Aprovada",
  "audit.rejected": "Rejeitada",
  "audit.webhook_attempt": "Webhook, tentativa {attempt}: a seguradora respondeu {status_code}",
  "audit.webhook_attempt.alt": "Webhook, tentativa {attempt}, falhou: {error_code}",
  "audit.webhook_attempt.plain": "Tentativa de webhook",
  "audit.receipt_recorded": "Recibo {receipt_id} registrado; cotação submetida",
  "audit.receipt_recorded.plain": "Recibo registrado; cotação submetida",
  "audit.delivery_abandoned": "Entrega abandonada depois de {attempts} tentativas",
  "audit.delivery_abandoned.plain": "Entrega abandonada",
  "audit.redelivery_requested": "Nova entrega solicitada",

  // Tool summaries
  "tool.resolve_location": "{label}",
  "tool.resolve_location.plain": "Local resolvido",
  "tool.resolve_location.candidates": "{count} lugares possíveis",
  "tool.resolve_location.candidates.plain": "Vários lugares possíveis",
  "tool.get_weather_history": "{dataset_id} · {first_year} a {last_year}",
  "tool.get_weather_history.plain": "Histórico carregado",
  "tool.backtest_index": "{seasons_used} safras · paga em {trigger_frequency_rate}",
  "tool.backtest_index.plain": "Backtest concluído",
  "tool.price_cover": "{quote_id} · prêmio de {premium_cents}",
  "tool.price_cover.plain": "Cobertura precificada",
  "tool.find_extreme_seasons": "{count} safras",
  "tool.find_extreme_seasons.plain": "Piores safras encontradas",
  "tool.draft_term_sheet": "Term sheet gerado em inglês e português",
  "tool.request_submission": "{submission_id} · aguardando aprovação",
  "tool.request_submission.plain": "Submissão solicitada; aguardando aprovação",
  "tool.error": "Falhou: {error_code}",
  "tool.error.plain": "Falhou",

  // Pricing warnings and assumptions
  "warning.trend_significant":
    "O índice tem tendência significativa {direction}, de {slope_per_decade} por década. O histórico pode distorcer o risco atual.",
  "warning.trend_significant.plain":
    "O índice tem tendência significativa. O histórico pode distorcer o risco atual.",
  "warning.seasons_excluded": "Safras excluídas por dados incompletos ({count}): {seasons}.",
  "warning.seasons_excluded.plain": "Algumas safras foram excluídas por dados incompletos.",
  "assumption.index_type": "Índice: {index_type}.",
  "assumption.window":
    "Janela de cobertura de {start} a {end}; a safra é rotulada pelo ano de início.",
  "assumption.seasons_used": "{seasons_used} safras usadas, de {first_season} a {last_season}.",
  "assumption.simulation_method": "{method}; {n} safras simuladas; semente {seed}.",
  "assumption.loads":
    "Carga de risco de {risk_load_rate} sobre o desvio padrão; carga de despesas de {expense_load_rate} sobre a perda esperada.",
  "assumption.data_source": "Dados de clima: {source}.",
};
