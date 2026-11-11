"""Two hand-built quotes for the term sheet tests, with the strings each page must show.

Every figure is written by hand and, inside one quote, every monetary value is distinct, so a
figure found on the page can only be the right one. The expected strings are literals: they
are not produced by the formatters under test. Each one is a row of the page, label then
value, as text extraction returns it.
"""

from datetime import UTC, datetime

from veranico.modules.pricing.contracts import (
    BacktestResult,
    CoverDefinition,
    IndexDefinition,
    Premium,
    PricedCover,
    SeasonResult,
    SimulationResult,
    Trend,
    Window,
)
from veranico.modules.quoting.contracts import AuditEntry, QuoteLocation, QuoteView
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import DatasetId, Locale, QuoteId, WorkspaceId
from veranico.shared.kernel.money import Money


def _seasons(
    excluded: set[int], paying: int, payout_cents: int, value: float
) -> list[SeasonResult]:
    """Seasons 1950 to 2024 without the excluded ones; only `paying` has a payout."""
    return [
        SeasonResult(
            season=season,
            index_value=value,
            payout=Money(amount_cents=payout_cents if season == paying else 0),
        )
        for season in range(1950, 2025)
        if season not in excluded
    ]


def _assumptions(
    index: IndexDefinition, seasons_used: int, method: str, n: int, seed: int, source: str
) -> list[Coded]:
    return [
        Coded(code="assumption.index_type", params={"index_type": index.index_type}),
        Coded(
            code="assumption.window", params={"start": index.window.start, "end": index.window.end}
        ),
        Coded(
            code="assumption.seasons_used",
            params={"seasons_used": seasons_used, "first_season": 1950, "last_season": 2024},
        ),
        Coded(code="assumption.simulation_method", params={"method": method, "n": n, "seed": seed}),
        Coded(
            code="assumption.loads",
            params={"risk_load_rate": "0.300000", "expense_load_rate": "0.150000"},
        ),
        Coded(code="assumption.data_source", params={"source": source}),
    ]


def rainfall_quote() -> QuoteView:
    """`rainfall_below` on a real point history, with both warnings."""
    dataset_id = DatasetId("point:86a8100c7ffffff")
    index = IndexDefinition(
        index_type="rainfall_below",
        window=Window(start="11-15", end="02-15"),  # crosses the year end
        trigger=350.0,
        exit=142.5,
    )
    cover = CoverDefinition(index=index, limit=Money(amount_cents=30000000))
    backtest = BacktestResult(
        dataset_id=dataset_id,
        cover=cover,
        seasons=_seasons({1951, 1962}, paying=1963, payout_cents=21050025, value=189.2),
        seasons_used=73,
        seasons_excluded=[1951, 1962],
        trigger_frequency="0.083200",
        burn_cost=Money(amount_cents=1234567),
        max_payout=Money(amount_cents=21050025),
        max_payout_season=1963,
        trend=Trend(slope_per_decade=-12.5, p_value="0.031200", significant=True),
        warnings=[
            Coded(
                code="warning.trend_significant",
                params={"slope_per_decade": -12.5, "direction": "decreasing"},
            ),
            Coded(code="warning.seasons_excluded", params={"count": 2, "seasons": "1951, 1962"}),
        ],
    )
    simulation = SimulationResult(
        method="gamma_mle",
        n=100000,
        seed=42,
        expected_loss=Money(amount_cents=1345678),
        std_dev=Money(amount_cents=4567890),
        probability_of_payout="0.091500",
        payout_1_in_10=Money(amount_cents=5000001),
        payout_1_in_100=Money(amount_cents=19876543),
        gap_to_burn_cost=Money(amount_cents=111111),
    )
    premium = Premium(
        premium=Money(amount_cents=2917896),
        rate_on_line="0.097263",
        risk_load="0.300000",
        expense_load="0.150000",
    )
    created_at = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)
    return QuoteView(
        quote_id=QuoteId("Q-7K2M9P"),
        workspace_id=WorkspaceId("ws-rain"),
        created_at=created_at,
        status="draft",
        location=QuoteLocation(
            label="Fazenda Boa Vista, Varginha",
            lat=-21.55,
            lon=-45.43,
            h3_cell="86a8100c7ffffff",
            admin_region="Minas Gerais",
        ),
        dataset_id=dataset_id,
        cover=cover,
        priced=PricedCover(
            backtest=backtest,
            simulation=simulation,
            premium=premium,
            assumptions=_assumptions(index, 73, "gamma_mle", 100000, 42, "era5/open-meteo"),
        ),
        submission=None,
        audit=[AuditEntry(at=created_at, actor="agent", action=Coded(code="audit.quote_created"))],
    )


def dry_spell_quote() -> QuoteView:
    """`dry_spell_above` on a synthetic cube: no warning, a negative gap, markup in the label."""
    dataset_id = DatasetId("cube:sorriso:5:2")
    index = IndexDefinition(
        index_type="dry_spell_above",
        window=Window(start="01-10", end="03-20"),
        trigger=12.0,
        exit=25.0,
    )
    cover = CoverDefinition(index=index, limit=Money(amount_cents=7550000))
    backtest = BacktestResult(
        dataset_id=dataset_id,
        cover=cover,
        seasons=_seasons(set(), paying=1986, payout_cents=5226923, value=9.0),
        seasons_used=75,
        seasons_excluded=[],
        trigger_frequency="0.120000",
        burn_cost=Money(amount_cents=906000),
        max_payout=Money(amount_cents=5226923),
        max_payout_season=1986,
        trend=Trend(slope_per_decade=0.3, p_value="0.412345", significant=False),
        warnings=[],
    )
    simulation = SimulationResult(
        method="bootstrap",
        n=50000,
        seed=7,
        expected_loss=Money(amount_cents=897755),
        std_dev=Money(amount_cents=1811322),
        probability_of_payout="0.119800",
        payout_1_in_10=Money(amount_cents=2903846),
        payout_1_in_100=Money(amount_cents=4936538),
        gap_to_burn_cost=Money(amount_cents=-8245),
    )
    premium = Premium(
        premium=Money(amount_cents=1575815),
        rate_on_line="0.208717",
        risk_load="0.300000",
        expense_load="0.150000",
    )
    created_at = datetime(2027, 1, 2, 9, 0, tzinfo=UTC)
    return QuoteView(
        quote_id=QuoteId("Q-3F8H2D"),
        workspace_id=WorkspaceId("ws-dry"),
        created_at=created_at,
        status="draft",
        location=QuoteLocation(
            label="Talhão 7 <b>norte</b> & sul",
            lat=-12.55,
            lon=-55.75,
            h3_cell="868a4a807ffffff",
            admin_region=None,
        ),
        dataset_id=dataset_id,
        cover=cover,
        priced=PricedCover(
            backtest=backtest,
            simulation=simulation,
            premium=premium,
            assumptions=_assumptions(index, 75, "bootstrap", 50000, 7, "synthetic"),
        ),
        submission=None,
        audit=[
            AuditEntry(at=created_at, actor="api_client", action=Coded(code="audit.quote_created"))
        ],
    )


RAINFALL_ROWS: dict[Locale, tuple[str, ...]] = {
    "en": (
        "Quote number Q-7K2M9P",
        "Created on 10 November 2026",
        "Location Fazenda Boa Vista, Varginha",
        "Latitude -21.55",
        "Longitude -45.43",
        "Administrative region Minas Gerais",
        "Dataset point:86a8100c7ffffff",
        "Index type total rainfall below the trigger",
        "Coverage window 15 November to 15 February",
        "Trigger 350.0 mm",
        "Exit 142.5 mm",
        "Limit R$ 300,000.00",
        "Premium R$ 29,178.96",
        "Rate on line 9.7263%",
        "Risk load 30.0000%",
        "Expense load 15.0000%",
        "Seasons used 73",
        "Seasons excluded 2",
        "Trigger frequency 8.3200%",
        "Burn cost R$ 12,345.67",
        "Maximum payout R$ 210,500.25",
        "Season of the maximum payout 1963",
        "Index trend -12.5 mm per decade",
        "Trend p-value 0.031200",
        "Method gamma distribution fitted by maximum likelihood",
        "Simulated seasons 100000",
        "Seed 42",
        "Expected loss R$ 13,456.78",
        "Standard deviation of the payout R$ 45,678.90",
        "Probability of payout 9.1500%",
        "1-in-10 payout R$ 50,000.01",
        "1-in-100 payout R$ 198,765.43",
        "Expected loss minus burn cost R$ 1,111.11",
    ),
    "pt-BR": (
        "Número da cotação Q-7K2M9P",
        "Criada em 10 de novembro de 2026",
        "Local Fazenda Boa Vista, Varginha",
        "Latitude -21,55",
        "Longitude -45,43",
        "Região administrativa Minas Gerais",
        "Conjunto de dados point:86a8100c7ffffff",
        "Tipo de índice chuva total abaixo do gatilho",
        "Janela de cobertura 15 de novembro a 15 de fevereiro",
        "Gatilho 350,0 mm",
        "Saída 142,5 mm",
        "Limite R$ 300.000,00",
        "Prêmio R$ 29.178,96",
        "Taxa sobre o limite 9,7263%",
        "Carregamento de risco 30,0000%",
        "Carregamento de despesas 15,0000%",
        "Safras utilizadas 73",
        "Safras excluídas 2",
        "Frequência de acionamento 8,3200%",
        "Custo histórico médio R$ 12.345,67",
        "Pagamento máximo R$ 210.500,25",
        "Safra do pagamento máximo 1963",
        "Tendência do índice -12,5 mm por década",
        "Valor-p da tendência 0,031200",
        "Método distribuição gama ajustada por máxima verossimilhança",
        "Safras simuladas 100000",
        "Semente 42",
        "Perda esperada R$ 13.456,78",
        "Desvio padrão do pagamento R$ 45.678,90",
        "Probabilidade de pagamento 9,1500%",
        "Pagamento de 1 em 10 R$ 50.000,01",
        "Pagamento de 1 em 100 R$ 198.765,43",
        "Perda esperada menos custo histórico R$ 1.111,11",
    ),
}

RAINFALL_TEXTS: dict[Locale, tuple[str, ...]] = {
    "en": (
        "Index: total rainfall below the trigger.",
        "The index is measured from 15 November to 15 February; a season is named after the"
        " year it starts in.",
        "73 seasons with complete data were used, from 1950 to 2024.",
        "Simulation: gamma distribution fitted by maximum likelihood; 100000 simulated seasons;"
        " seed 42.",
        "Premium = expected loss + 30.0000% of the standard deviation + 15.0000% of the"
        " expected loss.",
        "Weather data: ERA5 daily precipitation (Copernicus Climate Change Service, through"
        " Open-Meteo).",
        "Contains modified Copernicus Climate Change Service information 2026.",
    ),
    "pt-BR": (
        "Índice: chuva total abaixo do gatilho.",
        "O índice é medido de 15 de novembro a 15 de fevereiro; a safra leva o nome do ano em"
        " que começa.",
        "Foram utilizadas 73 safras com dados completos, de 1950 a 2024.",
        "Simulação: distribuição gama ajustada por máxima verossimilhança; 100000 safras"
        " simuladas; semente 42.",
        "Prêmio = perda esperada + 30,0000% do desvio padrão + 15,0000% da perda esperada.",
        "Dados meteorológicos: precipitação diária do ERA5 (Copernicus Climate Change Service,"
        " por meio do Open-Meteo).",
        "Contém informações modificadas do Copernicus Climate Change Service 2026.",
    ),
}

RAINFALL_WARNINGS: dict[Locale, tuple[str, ...]] = {
    "en": (
        "Warnings",
        "The index has a statistically significant downward trend (-12.5 per decade, 5% level):"
        " history may understate or overstate the current risk.",
        "Seasons with incomplete data were excluded from the backtest (2): 1951, 1962.",
    ),
    "pt-BR": (
        "Alertas",
        "O índice tem uma tendência de queda estatisticamente significativa (-12,5 por década,"
        " nível de 5%): o histórico pode subestimar ou superestimar o risco atual.",
        "Safras com dados incompletos foram excluídas do backtest (2): 1951, 1962.",
    ),
}

DRY_SPELL_ROWS: dict[Locale, tuple[str, ...]] = {
    "en": (
        "Quote number Q-3F8H2D",
        "Created on 2 January 2027",
        "Location Talhão 7 <b>norte</b> & sul",
        "Latitude -12.55",
        "Longitude -55.75",
        "Administrative region Not available",
        "Dataset cube:sorriso:5:2",
        "Index type longest dry spell above the trigger",
        "Coverage window 10 January to 20 March",
        "Trigger 12.0 days",
        "Exit 25.0 days",
        "Limit R$ 75,500.00",
        "Premium R$ 15,758.15",
        "Rate on line 20.8717%",
        "Risk load 30.0000%",
        "Expense load 15.0000%",
        "Seasons used 75",
        "Seasons excluded 0",
        "Trigger frequency 12.0000%",
        "Burn cost R$ 9,060.00",
        "Maximum payout R$ 52,269.23",
        "Season of the maximum payout 1986",
        "Index trend 0.3 days per decade",
        "Trend p-value 0.412345",
        "Method bootstrap of the historical seasons",
        "Simulated seasons 50000",
        "Seed 7",
        "Expected loss R$ 8,977.55",
        "Standard deviation of the payout R$ 18,113.22",
        "Probability of payout 11.9800%",
        "1-in-10 payout R$ 29,038.46",
        "1-in-100 payout R$ 49,365.38",
        "Expected loss minus burn cost -R$ 82.45",
    ),
    "pt-BR": (
        "Número da cotação Q-3F8H2D",
        "Criada em 2 de janeiro de 2027",
        "Local Talhão 7 <b>norte</b> & sul",
        "Latitude -12,55",
        "Longitude -55,75",
        "Região administrativa Não disponível",
        "Conjunto de dados cube:sorriso:5:2",
        "Tipo de índice veranico mais longo acima do gatilho",
        "Janela de cobertura 10 de janeiro a 20 de março",
        "Gatilho 12,0 dias",
        "Saída 25,0 dias",
        "Limite R$ 75.500,00",
        "Prêmio R$ 15.758,15",
        "Taxa sobre o limite 20,8717%",
        "Carregamento de risco 30,0000%",
        "Carregamento de despesas 15,0000%",
        "Safras utilizadas 75",
        "Safras excluídas 0",
        "Frequência de acionamento 12,0000%",
        "Custo histórico médio R$ 9.060,00",
        "Pagamento máximo R$ 52.269,23",
        "Safra do pagamento máximo 1986",
        "Tendência do índice 0,3 dias por década",
        "Valor-p da tendência 0,412345",
        "Método bootstrap das safras históricas",
        "Safras simuladas 50000",
        "Semente 7",
        "Perda esperada R$ 8.977,55",
        "Desvio padrão do pagamento R$ 18.113,22",
        "Probabilidade de pagamento 11,9800%",
        "Pagamento de 1 em 10 R$ 29.038,46",
        "Pagamento de 1 em 100 R$ 49.365,38",
        "Perda esperada menos custo histórico -R$ 82,45",
    ),
}

DRY_SPELL_TEXTS: dict[Locale, tuple[str, ...]] = {
    "en": (
        "This quote was priced on synthetic weather data generated for demonstration. Its"
        " figures do not describe real weather history.",
        "Index: longest dry spell above the trigger.",
        "The index is measured from 10 January to 20 March; a season is named after the year it"
        " starts in.",
        "75 seasons with complete data were used, from 1950 to 2024.",
        "Simulation: bootstrap of the historical seasons; 50000 simulated seasons; seed 7.",
        "Weather data: synthetic series generated for demonstration, not real weather history.",
        "Contains modified Copernicus Climate Change Service information 2027.",
    ),
    "pt-BR": (
        "Esta cotação foi precificada com dados meteorológicos sintéticos, gerados para"
        " demonstração. Seus valores não descrevem o histórico real do clima.",
        "Índice: veranico mais longo acima do gatilho.",
        "O índice é medido de 10 de janeiro a 20 de março; a safra leva o nome do ano em que"
        " começa.",
        "Foram utilizadas 75 safras com dados completos, de 1950 a 2024.",
        "Simulação: bootstrap das safras históricas; 50000 safras simuladas; semente 7.",
        "Dados meteorológicos: série sintética gerada para demonstração, não é histórico real"
        " do clima.",
        "Contém informações modificadas do Copernicus Climate Change Service 2027.",
    ),
}

DISCLAIMER: dict[Locale, str] = {
    "en": (
        "Pricing is illustrative and is not actuarial or insurance advice. Veranico is a"
        " non-commercial demonstration."
    ),
    "pt-BR": (
        "A precificação é ilustrativa e não constitui aconselhamento atuarial nem de seguros. O"
        " Veranico é uma demonstração sem fins comerciais."
    ),
}

ATTRIBUTION: dict[Locale, tuple[str, ...]] = {
    "en": (
        "Regional cubes use ERA5-Land and point histories use ERA5, both reanalysis products of"
        " the Copernicus Climate Change Service.",
        "weather data by Open-Meteo.com (https://open-meteo.com/).",
        "Neither the European Commission nor ECMWF is responsible for any use that may be made"
        " of the Copernicus information or data it contains.",
        "Licence: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).",
    ),
    "pt-BR": (
        "Os cubos regionais usam o ERA5-Land e os históricos de ponto usam o ERA5, ambos"
        " produtos de reanálise do Copernicus Climate Change Service.",
        "dados meteorológicos de Open-Meteo.com (https://open-meteo.com/).",
        "Nem a Comissão Europeia nem o ECMWF são responsáveis por qualquer uso que possa ser"
        " feito das informações ou dos dados do Copernicus aqui contidos.",
        "Licença: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).",
    ),
}
