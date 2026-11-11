import type { Messages } from "./en";

/** Brazilian Portuguese catalogue. Its type forces the same keys as `en.ts`. */
export const ptBR: Messages = {
  // Product
  "app.name": "Veranico",
  "app.disclaimer": "O preço é ilustrativo. Não é cálculo atuarial nem recomendação de seguro.",
  "app.non_commercial": "Demonstração sem fins comerciais.",
  "app.weather_attribution":
    "Clima: Copernicus Climate Change Service. ERA5-Land nos cubos regionais; ERA5 via Open-Meteo em qualquer outro ponto. CC BY 4.0.",
  "app.weather_attribution_synthetic":
    "Clima: a superfície desta região é sintética, gerada para a demonstração; não é histórico de clima. Um ponto fora das regiões de demonstração usa o ERA5 via Open-Meteo (Copernicus Climate Change Service, CC BY 4.0).",
  "app.synthetic":
    "Dados climáticos sintéticos: estes números foram gerados para a demonstração e não são histórico de clima.",

  // Map
  "map.label": "Mapa de {region}",
  "map.label_empty": "Mapa",
  "map.basemap_failed": "O mapa de base não carregou. A camada de risco continua visível.",
  "map.basemap_retry": "Carregar de novo",
  "map.farm": "Fazenda",
  "map.cube": "Grade de clima: {count} células de {step}°",
  "map.smoothing":
    "A cor é suavizada entre os centros das células só para leitura. O dado é um valor por célula.",
  "map.synthetic": "Dados de clima sintéticos, não são histórico",
  "map.outside_showcase":
    "Este ponto fica fora das regiões de demonstração, então não há visão regional. A cotação usa o ponto de grade do ERA5 devolvido pela fonte de clima; o contorno só mostra o tamanho de uma célula de 0,25°.",
  "map.cell.frequency": "Paga em {rate} das safras",
  "map.cell.anomaly": "{anomaly} contra a mediana",
  "map.cell.no_value": "Sem valor para esta célula",
  "map.cell.distance": "{distance} da fazenda",
  "compass.north": "N",
  "compass.south": "S",
  "compass.east": "L",
  "compass.west": "O",

  // Season timeline
  "timeline.label": "Safras",
  "timeline.range_label": "Safra",
  "timeline.hint": "Arraste para ver uma safra no mapa",
  "timeline.season_view": "Mostrar uma safra",
  "timeline.all_seasons": "Todas as safras",
  "timeline.season": "{season}: {value}",
  "timeline.season_payout": "{season}: {value}, pagamento de {payout}",
  "timeline.legend_payout": "Safra com pagamento",
  "timeline.legend_trigger": "Gatilho {value}",
  "timeline.loading": "Carregando as safras",
  "timeline.failed": "As safras não carregaram.",
  "action.retry": "Tentar de novo",
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
  "region.option": "{name} · {crop}",
  "region.outside": "Fora das regiões de demonstração",
  "render.label": "Camada de risco",
  "render.surface": "Superfície",
  "render.cells": "Células",
  "top.label": "Opções de visualização",
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

  // Tabs
  "tab.risk": "Risco",
  "tab.history": "Histórico",
  "tab.quote": "Cotação",
  "tab.approvals": "Aprovações",

  "tabs.label": "Detalhes",
  "state.loading": "Carregando",
  "state.failed": "Isto não carregou.",

  // Risk tab
  "risk.empty": "Escolha uma região para ver a superfície de risco.",
  "risk.no_cell": "O ponto segurado está fora da grade de clima desta região.",
  "risk.cell": "Célula segurada",
  "risk.cell.no_value": "sem valor",
  "risk.neighbours": "Células vizinhas",
  "risk.range": "{min} a {max}",
  "risk.reading.frequency":
    "Na célula segurada, esta cobertura teria pago em {rate} das {seasons} safras. As vizinhas vão de {min} a {max}.",
  "risk.reading.season":
    "Em {season}, o índice na célula segurada ficou {anomaly} em relação à mediana. {paying} das {cells} células da região teriam pago.",
  "risk.reading.season_plain":
    "Em {season}, o índice na célula segurada ficou {anomaly} em relação à mediana.",
  "risk.legend.frequency": "Parcela das safras que pagam",
  "risk.legend.anomaly": "Índice em relação à mediana da célula, de seco a úmido",
  "risk.legend.class": "{low} a {high}",
  "risk.neighbourhood": "A célula segurada e suas vizinhas, com o norte no alto",
  "risk.neighbourhood.insured": "célula segurada",
  "risk.neighbourhood.outside": "fora da grade",

  // History tab
  "history.empty":
    "Ainda não há backtest. Descreva uma exposição na conversa e o agente reproduz o índice em todas as safras.",
  "history.index_title.rainfall_below": "Chuva na janela, por safra",
  "history.index_title.dry_spell_above": "Maior período seco na janela, por safra",
  "history.payout_title": "Pagamento por safra",
  "history.trigger_line": "Gatilho {value}",
  "history.exit_line": "Saída {value}",
  "history.range_label": "Safra",
  "history.hint": "Selecione uma barra, ou use as setas, para pôr essa safra no mapa.",
  "history.tip.index": "Índice",
  "history.tip.payout": "Pagamento",
  "history.no_payout": "Sem pagamento",
  "history.aggregates": "Agregados",
  "history.seasons_used": "Safras usadas",
  "history.trigger_frequency": "Frequência do gatilho",
  "history.burn_cost": "Burn cost (pagamento médio)",
  "history.max_payout": "Maior pagamento",
  "history.max_payout_in": "{value} em {season}",
  "history.seasons_excluded": "Safras excluídas",
  "history.table.show": "Mostrar todas as safras em tabela",
  "history.table.hide": "Ocultar a tabela",
  "history.table.caption": "Todas as safras",
  "history.table.season": "Safra",
  "history.table.index": "Índice",
  "history.table.payout": "Pagamento",

  // Quote tab
  "quote.empty":
    "Ainda não há cotação. Quando o agente precificar uma cobertura, ela aparece aqui.",
  "quote.recording":
    "Gravação. Esta cotação foi precificada quando a conversa foi gravada. Ela não existe no seu workspace, então não há downloads nem nada para aprovar.",
  "quote.premium": "Prêmio indicativo",
  "quote.rate_on_line": "Taxa sobre o limite",
  "quote.simulation": "Simulação",
  "quote.expected_loss": "Perda esperada",
  "quote.std_dev": "Desvio padrão",
  "quote.probability_of_payout": "Probabilidade de pagamento",
  "quote.payout_1_in_10": "Pagamento, 1 safra em 10",
  "quote.payout_1_in_100": "Pagamento, 1 safra em 100",
  "quote.gap_to_burn_cost": "Perda esperada menos burn cost",
  "quote.cover": "Cobertura",
  "quote.location": "Local",
  "quote.dataset": "Conjunto de dados",
  "quote.index": "Índice",
  "quote.window": "Janela",
  "quote.trigger": "Gatilho",
  "quote.exit": "Saída",
  "quote.limit": "Limite",
  "quote.assumptions": "Premissas",
  "quote.downloads": "Downloads",
  "quote.term_sheet": "Term sheet, {language} (PDF)",
  "quote.evidence": "Evidência (NetCDF)",
  "quote.term_sheet_pending": "O term sheet fica disponível depois que o agente o gerar.",
  "quote.audit": "Trilha de auditoria",
  "quote.audit.note": "Nota: {note}",
  "quote.api.title": "Usar a API",
  "quote.api.body":
    "Crie uma chave para este workspace e precifique a mesma cobertura pela API pública. A chave é mostrada uma vez e não fica guardada neste navegador.",
  "quote.api.create": "Criar uma chave de API",
  "quote.api.creating": "Criando a chave",
  "quote.api.secret": "Chave de API",
  "quote.api.once": "Copie agora. Ela é mostrada só esta vez e não pode ser mostrada de novo.",
  "quote.api.expires": "Expira em {date}",
  "quote.api.copy": "Copiar a chave",
  "quote.api.copy_example": "Copiar a requisição",
  "quote.api.copied": "Copiado",
  "quote.api.example": "Requisição de exemplo",
  "quote.api.hide": "Pronto, ocultar a chave",

  // Approvals tab
  "tabs.badge.one": "{count} pendente",
  "tabs.badge.other": "{count} pendentes",
  "approvals.empty":
    "Nada para aprovar. Quando o agente solicitar uma submissão, ela aguarda aqui a sua decisão.",
  "approvals.open_quote": "{quote_id}: abrir a cotação",
  "approvals.carrier": "Seguradora",
  "approvals.premium": "Prêmio",
  "approvals.requested": "Solicitada",
  "approvals.you_decide":
    "O agente solicitou esta submissão e não pode aprová-la. A decisão é sua.",
  "approvals.note": "Nota (opcional)",
  "approvals.note_count": "{count} de {max} caracteres",
  "approvals.note_too_long": "A nota tem mais de {max} caracteres. Encurte.",
  "approvals.approve": "Aprovar",
  "approvals.reject": "Rejeitar",
  "approvals.delivering": "Aprovada. Entregando à seguradora.",
  "approvals.attempts.one": "{count} tentativa até agora.",
  "approvals.attempts.other": "{count} tentativas até agora.",
  "approvals.last_error": "Último erro: {code}.",
  "approvals.delivered": "Entregue. O recibo da seguradora é {receipt_id}.",
  "approvals.rejected": "Rejeitada. Nada foi enviado à seguradora.",
  "approvals.abandoned": "A entrega foi abandonada após {count} tentativas.",
  "approvals.redeliver": "Entregar de novo",

  // Conversation card
  "chat.title": "Conversa",
  "chat.restart": "Recomeçar",
  "chat.progress": "Progresso",
  "chat.step_of": "Passo {step} de {count}: {name}",
  "chat.steps_done": "Os {count} passos foram concluídos",
  "chat.step.done": "{name}: concluído",
  "chat.step.current": "{name}: próximo",
  "chat.step.todo": "{name}: não iniciado",
  "chat.meter.one": "{count} mensagem restante hoje",
  "chat.meter.other": "{count} mensagens restantes hoje",
  "chat.messages": "Mensagens",
  "chat.you": "Você",
  "chat.working": "O agente está trabalhando",
  "chat.no_answer": "O agente encerrou o turno sem resposta.",
  "chat.first.title": "Descreva uma exposição ou comece por um destes exemplos",
  "chat.first.body":
    "O agente pergunta o que for essencial e estiver faltando; depois faz o backtest e precifica a cobertura com as ferramentas listadas em cada passo.",
  "chat.example.rainfall_below":
    "Fazenda perto de {label}. O cliente teme pouca chuva de {start} a {end}. Pagar quando a chuva ficar abaixo de {trigger}, integral em {exit}. Limite de {limit}.",
  "chat.example.dry_spell_above":
    "Fazenda perto de {label}. O cliente teme um veranico de {start} a {end}. Pagar quando o maior período seco passar de {trigger}, integral em {exit}. Limite de {limit}.",
  "chat.input": "Mensagem para o agente",
  "chat.placeholder": "Cultura, local, risco, janela de cobertura, limite",
  "chat.send": "Enviar",
  "chat.hint": "Enter envia. Shift+Enter abre uma nova linha.",
  "chat.map_point": "Ponto do mapa: {lat}, {lon}",
  "chat.map_point_remove": "Remover o ponto",
  "chat.map_point_request":
    "Precifique uma cobertura para o ponto que marquei no mapa ({lat}, {lon}).",
  "chat.tool.running": "em execução",
  "chat.tool.ok": "concluída",
  "chat.tool.failed": "falhou",
  "chat.tool.not_run": "não executada",
  "chat.tool.arguments": "Argumentos",
  "chat.figure.open": "{value}: mostrar a origem na aba {tab}",
  "chat.figure.flagged": "não encontrado em nenhuma saída de ferramenta",
  "chat.flagged.one":
    "1 número desta resposta não foi encontrado em nenhuma saída de ferramenta. Trate-o como não verificado.",
  "chat.flagged.other":
    "{count} números desta resposta não foram encontrados em nenhuma saída de ferramenta. Trate-os como não verificados.",
  "chat.interrupted": "A conexão caiu antes de a resposta terminar.",
  "chat.completed": "Concluído antes da interrupção: {tools}.",
  "chat.completed_none": "Nenhuma ferramenta havia concluído.",
  "chat.approval": "Uma pessoa decide esta submissão na aba Aprovações.",
  "chat.open_approvals": "Abrir aprovações",
  "chat.replay.offer":
    "Você ainda pode assistir a uma conversa gravada. O mapa, o histórico e a API pública continuam funcionando.",
  "chat.replay.play": "Reproduzir a conversa gravada",
  "chat.replay.again": "Reproduzir de novo",
  "chat.replay.loading": "Carregando a gravação",
  "chat.replay.failed": "A gravação não carregou.",
  "chat.replay.banner": "Gravação. Esta conversa foi gravada antes; nada aqui é criado ou enviado.",
  "chat.replay.ended": "A gravação terminou.",

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
  // A tool call the agent asked for beyond the limit, or after the tool had failed twice
  "problem.tool_not_executed":
    "Esta chamada não foi executada: o agente já havia usado as chamadas ou tentativas deste pedido.",
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
