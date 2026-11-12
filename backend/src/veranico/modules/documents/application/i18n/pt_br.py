"""Brazilian Portuguese catalogue of the term sheet. Same keys and placeholders as `en.py`."""

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    "title": "Cobertura paramétrica de chuva: resumo indicativo de termos",
    # Section titles
    "section.quote": "Cotação",
    "section.cover": "Definição da cobertura",
    "section.backtest": "Backtest histórico",
    "section.simulation": "Simulação",
    "section.premium": "Prêmio indicativo",
    "section.assumptions": "Premissas",
    "section.warnings": "Alertas",
    "section.data": "Dados e atribuição",
    "section.disclaimer": "Aviso legal",
    # Row labels
    "label.quote_id": "Número da cotação",
    "label.created_at": "Criada em",
    "label.location": "Local",
    "label.latitude": "Latitude",
    "label.longitude": "Longitude",
    "label.admin_region": "Região administrativa",
    "label.dataset_id": "Conjunto de dados",
    "label.index_type": "Tipo de índice",
    "label.window": "Janela de cobertura",
    "label.trigger": "Gatilho",
    "label.exit": "Saída",
    "label.limit": "Limite",
    "label.seasons_used": "Safras utilizadas",
    "label.seasons_excluded": "Safras excluídas",
    "label.trigger_frequency": "Frequência de acionamento",
    "label.burn_cost": "Custo histórico médio",
    "label.max_payout": "Pagamento máximo",
    "label.max_payout_season": "Safra do pagamento máximo",
    "label.trend_slope": "Tendência do índice",
    "label.trend_p_value": "Valor-p da tendência",
    "label.method": "Método",
    "label.n": "Safras simuladas",
    "label.seed": "Semente",
    "label.expected_loss": "Perda esperada",
    "label.std_dev": "Desvio padrão do pagamento",
    "label.probability_of_payout": "Probabilidade de pagamento",
    "label.payout_1_in_10": "Pagamento de 1 em 10",
    "label.payout_1_in_100": "Pagamento de 1 em 100",
    "label.gap_to_burn_cost": "Perda esperada menos custo histórico",
    "label.premium": "Prêmio",
    "label.rate_on_line": "Taxa sobre o limite",
    "label.risk_load": "Carregamento de risco",
    "label.expense_load": "Carregamento de despesas",
    # Quantities with their unit
    "unit.mm": "{value} mm",
    "unit.days": "{value} dias",
    "unit.mm_per_decade": "{value} mm por década",
    "unit.days_per_decade": "{value} dias por década",
    "dataset.cube": "Célula da grade do cubo regional (0,1°)",
    "dataset.point": "Histórico do ponto",
    "value.not_available": "Não disponível",
    # Month names
    "month.01": "janeiro",
    "month.02": "fevereiro",
    "month.03": "março",
    "month.04": "abril",
    "month.05": "maio",
    "month.06": "junho",
    "month.07": "julho",
    "month.08": "agosto",
    "month.09": "setembro",
    "month.10": "outubro",
    "month.11": "novembro",
    "month.12": "dezembro",
    # Enumerated parameter values
    "index_type.rainfall_below": "chuva total abaixo do gatilho",
    "index_type.dry_spell_above": "veranico mais longo acima do gatilho",
    "method.gamma_mle": "distribuição gama ajustada por máxima verossimilhança",
    "method.bootstrap": "bootstrap das safras históricas",
    "source.era5-land/cds": (
        "precipitação diária do ERA5-Land (Copernicus Climate Change Service)"
    ),
    "source.era5/open-meteo": (
        "precipitação diária do ERA5 (Copernicus Climate Change Service, por meio do Open-Meteo)"
    ),
    "source.synthetic": "série sintética gerada para demonstração, não é histórico real do clima",
    "direction.increasing": "de alta",
    "direction.decreasing": "de queda",
    # The eight codes of `pricing`
    "warning.trend_significant": (
        "O índice tem uma tendência {direction} estatisticamente significativa"
        " ({slope_per_decade} por década, nível de 5%): o histórico pode subestimar ou"
        " superestimar o risco atual."
    ),
    "warning.seasons_excluded": (
        "Safras com dados incompletos foram excluídas do backtest ({count}): {seasons}."
    ),
    "assumption.index_type": "Índice: {index_type}.",
    "assumption.window": (
        "O índice é medido de {start} a {end}; a safra leva o nome do ano em que começa."
    ),
    "assumption.seasons_used": (
        "Foram utilizadas {seasons_used} safras com dados completos, de {first_season} a"
        " {last_season}."
    ),
    "assumption.simulation_method": ("Simulação: {method}; {n} safras simuladas; semente {seed}."),
    "assumption.loads": (
        "Prêmio = perda esperada + {risk_load_rate} do desvio padrão + {expense_load_rate} da"
        " perda esperada."
    ),
    "assumption.data_source": "Dados meteorológicos: {source}.",
    # Data notice, attribution (SPEC 4.4, ADR 0017) and disclaimer (SPEC 1)
    "notice.synthetic": (
        "Esta cotação foi precificada com dados meteorológicos sintéticos, gerados para"
        " demonstração. Seus valores não descrevem o histórico real do clima."
    ),
    "attribution": (
        "Os cubos regionais usam o ERA5-Land e os históricos de ponto usam o ERA5, ambos"
        " produtos de reanálise do Copernicus Climate Change Service. Os históricos de ponto são"
        " obtidos por meio do Open-Meteo: dados meteorológicos de Open-Meteo.com"
        " (https://open-meteo.com/). Contém informações modificadas do Copernicus Climate Change"
        " Service {year}. Nem a Comissão Europeia nem o ECMWF são responsáveis por qualquer uso"
        " que possa ser feito das informações ou dos dados do Copernicus aqui contidos. Licença:"
        " CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)."
    ),
    "disclaimer": (
        "A precificação é ilustrativa e não constitui aconselhamento atuarial nem de seguros. O"
        " Veranico é uma demonstração sem fins comerciais."
    ),
}
