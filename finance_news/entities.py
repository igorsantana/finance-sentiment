"""NER + currency/country dictionaries for extracting entities from PT-BR text."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

log = logging.getLogger(__name__)

# --- Countries (PT-BR) --------------------------------------------------------
COUNTRIES_PT = {
    "Afeganistão", "África do Sul", "Albânia", "Alemanha", "Andorra", "Angola",
    "Arábia Saudita", "Argélia", "Argentina", "Armênia", "Austrália", "Áustria",
    "Azerbaijão", "Bahamas", "Bahrein", "Bangladesh", "Barbados", "Bélgica",
    "Belize", "Benin", "Bolívia", "Bósnia e Herzegovina", "Botsuana", "Brasil",
    "Brunei", "Bulgária", "Burkina Faso", "Burundi", "Butão", "Cabo Verde",
    "Camarões", "Camboja", "Canadá", "Catar", "Cazaquistão", "Chade", "Chile",
    "China", "Chipre", "Cingapura", "Colômbia", "Congo", "Coreia do Norte",
    "Coreia do Sul", "Costa do Marfim", "Costa Rica", "Croácia", "Cuba",
    "Dinamarca", "Djibuti", "Dominica", "Egito", "El Salvador", "Emirados Árabes Unidos",
    "Equador", "Eritreia", "Escócia", "Eslováquia", "Eslovênia", "Espanha",
    "Estados Unidos", "Estônia", "Eswatini", "Etiópia", "Fiji", "Filipinas",
    "Finlândia", "França", "Gabão", "Gâmbia", "Gana", "Geórgia", "Granada",
    "Grécia", "Guatemala", "Guiana", "Guiné", "Guiné Equatorial", "Guiné-Bissau",
    "Haiti", "Holanda", "Honduras", "Hong Kong", "Hungria", "Iêmen",
    "Ilhas Marshall", "Ilhas Salomão", "Índia", "Indonésia", "Inglaterra",
    "Irã", "Iraque", "Irlanda", "Islândia", "Israel", "Itália", "Jamaica",
    "Japão", "Jordânia", "Kiribati", "Kuwait", "Laos", "Lesoto", "Letônia",
    "Líbano", "Libéria", "Líbia", "Liechtenstein", "Lituânia", "Luxemburgo",
    "Macedônia do Norte", "Madagascar", "Malásia", "Malauí", "Maldivas", "Mali",
    "Malta", "Marrocos", "Maurício", "Mauritânia", "México", "Mianmar",
    "Micronésia", "Moçambique", "Moldávia", "Mônaco", "Mongólia", "Montenegro",
    "Namíbia", "Nauru", "Nepal", "Nicarágua", "Níger", "Nigéria", "Noruega",
    "Nova Zelândia", "Omã", "Países Baixos", "Palau", "Palestina", "Panamá",
    "Papua-Nova Guiné", "Paquistão", "Paraguai", "Peru", "Polônia", "Portugal",
    "Quênia", "Quirguistão", "Reino Unido", "República Centro-Africana",
    "República Dominicana", "República Tcheca", "Romênia", "Ruanda", "Rússia",
    "Samoa", "San Marino", "Santa Lúcia", "São Cristóvão e Neves", "São Tomé e Príncipe",
    "São Vicente e Granadinas", "Senegal", "Serra Leoa", "Sérvia", "Seychelles",
    "Síria", "Somália", "Sri Lanka", "Sudão", "Sudão do Sul", "Suécia", "Suíça",
    "Suriname", "Tadjiquistão", "Tailândia", "Taiwan", "Tanzânia", "Timor-Leste",
    "Togo", "Tonga", "Trinidad e Tobago", "Tunísia", "Turcomenistão", "Turquia",
    "Tuvalu", "Ucrânia", "Uganda", "União Europeia", "Uruguai", "Uzbequistão",
    "Vanuatu", "Vaticano", "Venezuela", "Vietnã", "Zâmbia", "Zimbábue",
    # common informal synonyms we will normalize TO
    "EUA", "UE",
}

# Normalize informal → canonical form
COUNTRY_ALIASES = {
    "estados unidos da américa": "Estados Unidos",
    "eua": "Estados Unidos",
    "uk": "Reino Unido",
    "grã-bretanha": "Reino Unido",
    "ue": "União Europeia",
    "holanda": "Países Baixos",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


COUNTRIES_NORM = {_norm(c): c for c in COUNTRIES_PT}
for alias, canon in COUNTRY_ALIASES.items():
    COUNTRIES_NORM[_norm(alias)] = canon


# --- Currencies ---------------------------------------------------------------
CURRENCY_NAME_TO_ISO = {
    "real": "BRL", "reais": "BRL",
    "dólar": "USD", "dolar": "USD", "dólares": "USD", "dolares": "USD",
    "euro": "EUR", "euros": "EUR",
    "libra": "GBP", "libras": "GBP", "libra esterlina": "GBP",
    "iene": "JPY", "ienes": "JPY",
    "yuan": "CNY", "renminbi": "CNY",
    "peso argentino": "ARS",
    "peso mexicano": "MXN",
    "peso chileno": "CLP",
    "franco suíço": "CHF", "franco suico": "CHF",
    "dólar canadense": "CAD", "dolar canadense": "CAD",
    "dólar australiano": "AUD", "dolar australiano": "AUD",
    "bitcoin": "BTC", "ether": "ETH", "ethereum": "ETH",
}

ISO_RE = re.compile(
    r"\b(BRL|USD|EUR|GBP|JPY|CNY|ARS|CHF|CAD|AUD|MXN|CLP|BTC|ETH)\b"
)
# Symbols only count if adjacent to a number (avoids generic "R$" in navigation)
SYMBOL_RE = re.compile(
    r"(R\$|US\$|U\$S|US\s*\$|€|£|¥)\s*\d|\d\s*(€|£|¥)"
)
SYMBOL_TO_ISO = {
    "R$": "BRL", "US$": "USD", "U$S": "USD", "US $": "USD",
    "€": "EUR", "£": "GBP", "¥": "JPY",
}

# sort longest first so multi-word names win
_CURRENCY_NAME_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(k) for k in sorted(CURRENCY_NAME_TO_ISO, key=len, reverse=True)
    ) + r")\b",
    re.IGNORECASE,
)


def extract_currencies(text: str) -> list[str]:
    found: set[str] = set()
    for m in ISO_RE.finditer(text):
        found.add(m.group(1))
    for m in _CURRENCY_NAME_RE.finditer(text):
        found.add(CURRENCY_NAME_TO_ISO[m.group(1).lower()])
    for m in SYMBOL_RE.finditer(text):
        chunk = m.group(0)
        for sym, iso in SYMBOL_TO_ISO.items():
            if sym in chunk:
                found.add(iso)
                break
    return sorted(found)


def extract_countries(spacy_doc, text: str) -> list[str]:
    found: set[str] = set()
    # From NER (LOC / GPE / MISC that matches our list)
    for ent in spacy_doc.ents:
        if ent.label_ not in ("LOC", "GPE", "MISC"):
            continue
        key = _norm(ent.text)
        canon = COUNTRIES_NORM.get(key)
        if canon:
            found.add(canon)
    # Raw text scan catches mentions NER missed (common for "Estados Unidos")
    low = _norm(text)
    for key, canon in COUNTRIES_NORM.items():
        if len(key) < 4:
            continue
        # word-boundary-ish check on normalized text
        if re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", low):
            found.add(canon)
    return sorted(found)


# --- Companies ----------------------------------------------------------------
STOPWORD_ORGS = {
    # Source publications themselves
    "valor econômico", "valor", "exame", "infomoney", "brazil journal",
    "suno notícias", "suno", "investnews", "money times", "e-investidor",
    "estadão", "me poupe!", "me poupe", "investidor sardinha",
    "clube do valor", "quero ficar rico", "agência brasil", "gustavo cerbasi",
    "andré bona",
    # Government / regulators (typically not "companies")
    "banco central", "bc", "bcb", "receita federal", "cvm", "bndes",
    "ministério da fazenda", "ministério da economia", "tesouro nacional",
    "senado", "câmara", "câmara dos deputados", "stf", "tcu", "anvisa",
    "ibge", "ipea", "caixa econômica federal",
    "governo federal", "governo", "congresso", "palácio do planalto",
    "ibovespa", "b3", "bovespa", "s&p 500", "dow jones", "nasdaq", "nyse",
    "fmi", "bird", "ocde", "opep", "onu", "otan", "fed", "federal reserve",
    "bce", "banco central europeu",
    "reuters", "bloomberg", "ap", "afp", "folha", "g1", "uol", "cnn",
}

COMPANY_ALIASES = {
    "petrobrás": "Petrobras",
    "petrobras s.a.": "Petrobras",
    "itaú unibanco": "Itaú",
    "itau unibanco": "Itaú",
    "itaú": "Itaú",
    "banco do brasil s.a.": "Banco do Brasil",
    "vale s.a.": "Vale",
    "bradesco s.a.": "Bradesco",
}


def extract_companies(spacy_doc) -> list[str]:
    seen: dict[str, str] = {}  # canonical lowercased → display form
    for ent in spacy_doc.ents:
        if ent.label_ != "ORG":
            continue
        raw = ent.text.strip().strip("\"'“”‘’ ")
        if len(raw) < 2:
            continue
        low = raw.lower()
        if low in STOPWORD_ORGS:
            continue
        display = COMPANY_ALIASES.get(low, raw)
        key = display.lower()
        if key not in seen:
            seen[key] = display
    return sorted(seen.values())


def extract_persons(spacy_doc) -> list[str]:
    """Distinct PER entities, preserving first-seen surface form."""
    seen: dict[str, str] = {}
    for ent in spacy_doc.ents:
        if ent.label_ not in ("PER", "PERSON"):
            continue
        raw = ent.text.strip().strip("\"'“”‘’ ")
        if len(raw) < 3 or " " not in raw:
            continue  # require at least two tokens — cuts noise
        key = raw.lower()
        if key not in seen:
            seen[key] = raw
    return sorted(seen.values())


# --- spaCy loader -------------------------------------------------------------
_NLP = None


def get_nlp():
    global _NLP
    if _NLP is not None:
        return _NLP
    import spacy

    for model in ("pt_core_news_lg", "pt_core_news_md", "pt_core_news_sm"):
        try:
            _NLP = spacy.load(model, disable=["lemmatizer"])
            log.info("loaded spaCy model: %s", model)
            return _NLP
        except OSError:
            continue
    raise RuntimeError(
        "No Portuguese spaCy model found. Run: "
        "python -m spacy download pt_core_news_lg"
    )


def analyze(text: str) -> dict:
    nlp = get_nlp()
    # spaCy has a default 1M char limit; truncate defensively
    doc = nlp(text[:200_000])
    return {
        "companies": extract_companies(doc),
        "persons": extract_persons(doc),
        "countries": extract_countries(doc, text),
        "currencies": extract_currencies(text),
        "doc": doc,  # raw doc so downstream consumers can do salience ranking
    }
