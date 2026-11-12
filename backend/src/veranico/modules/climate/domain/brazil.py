"""Brazil as the product sees it: a coverage box and the 27 federative units (SPEC 4.3)."""

import unicodedata

COUNTRY_CODE = "BR"

# A box around mainland Brazil, in degrees. It also holds parts of the neighbours: it only
# refuses points that cannot be in Brazil, and the oceanic islands are left out.
SOUTH, WEST, NORTH, EAST = -34.0, -74.0, 5.5, -34.0

# The 26 states and the Federal District, by abbreviation.
STATES: dict[str, str] = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AP": "Amapá",
    "AM": "Amazonas",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais",
    "PA": "Pará",
    "PB": "Paraíba",
    "PR": "Paraná",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul",
    "RO": "Rondônia",
    "RR": "Roraima",
    "SC": "Santa Catarina",
    "SP": "São Paulo",
    "SE": "Sergipe",
    "TO": "Tocantins",
}

_COUNTRY_WORDS = frozenset({"br", "brasil", "brazil"})


def in_brazil_box(lat: float, lon: float) -> bool:
    return SOUTH <= lat <= NORTH and WEST <= lon <= EAST


def fold(text: str) -> str:
    """Lower case without accents or outer spaces, for comparing names people type."""
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


_BY_FOLDED: dict[str, str] = {fold(abbr): abbr for abbr in STATES} | {
    fold(name): abbr for abbr, name in STATES.items()
}


def state_abbreviation(text: str) -> str | None:
    """The abbreviation of a state given by name or abbreviation, in any case or accents."""
    return _BY_FOLDED.get(fold(text))


def names_the_country(text: str) -> bool:
    return fold(text) in _COUNTRY_WORDS
