"""
Persiste os resultados do scraper no MongoDB (backend) sem gerar duplicatas.
Faz upsert de Jogos, Parceiros e Ofertas.
- Jogo/Parceiro: cria se não existir, preserva dados existentes se já houver.
- Oferta: cria ou atualiza itens/status — se preço mudou, sobrescreve.
"""
import os
import re
from datetime import datetime

from pymongo import MongoClient, ReturnDocument

# Padrão para nomes genéricos de fallback gerados pelo scraper quando o
# jogo não é encontrado no site do parceiro (ex.: "Ingresso 3", "Ver no site")
_NOME_FALLBACK = re.compile(r"^ingresso\s+\d+$|^ver no site$", re.IGNORECASE)


def _make_slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def _limpar_texto(texto: str) -> str:
    """
    Remove artefatos de encoding que o Playwright pode retornar:
    - \ufffd  replacement character (byte inválido na página)
    - \xad    soft hyphen (hífem invisível do Unicode)
    - \xa0    non-breaking space → espaço normal
    Normaliza múltiplos espaços ao final.
    """
    texto = texto.replace("\ufffd", "").replace("\xad", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _parse_preco(preco_str: str) -> float:
    """Converte 'R$ 1.250,00' → 1250.0, tolerando \xa0 e \ufffd."""
    if not preco_str:
        return 0.0
    limpo = _limpar_texto(preco_str)
    m = re.search(r"[\d.]+,\d{2}", limpo)
    if m:
        return float(m.group().replace(".", "").replace(",", "."))
    m = re.search(r"\d+", limpo)
    if m:
        return float(m.group())
    return 0.0


def upsert_resultados(resultados: dict) -> None:
    """
    Recebe o dict completo de resultados do scraper e faz upsert no MongoDB.

    Estrutura esperada:
        {
            "Corinthians x Flamengo": {
                "parceiros": {
                    "Camarote Fielzone": {
                        "ingressos": [{"setor": str, "preco": str}],
                        # "erro": str  ← se presente, a oferta não é atualizada
                    }
                }
            }
        }

    Nomes de fallback genéricos gerados pelo scraper ("Ingresso 1", "Ver no
    site", etc.) são ignorados — apenas ingressos com nome real são salvos.
    Se todos os itens forem descartados, a oferta fica como "fechado".
    """
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/ingressos")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()
        jogos_col = db["jogos"]
        parceiros_col = db["parceiros"]
        ofertas_col = db["ofertas"]

        total_ofertas = 0

        for nome_jogo, dados_jogo in resultados.items():
            slug_jogo = _make_slug(nome_jogo)

            # Upsert Jogo — só preenche 'data' na criação; preserva se já existir
            jogo_doc = jogos_col.find_one_and_update(
                {"slug": slug_jogo},
                {
                    "$setOnInsert": {
                        "nome": nome_jogo,
                        "slug": slug_jogo,
                        "data": datetime.utcnow(),
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            jogo_id = jogo_doc["_id"]

            for nome_parceiro, dados_parceiro in dados_jogo.get("parceiros", {}).items():
                slug_parceiro = _make_slug(nome_parceiro)

                # Upsert Parceiro sempre (mesmo em caso de erro)
                parceiro_doc = parceiros_col.find_one_and_update(
                    {"slug": slug_parceiro},
                    {"$setOnInsert": {"nome": nome_parceiro, "slug": slug_parceiro}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                parceiro_id = parceiro_doc["_id"]

                if "erro" in dados_parceiro:
                    # Cria a oferta como "fechado" se ainda não existir, mas não
                    # sobrescreve dados válidos de execuções anteriores
                    ofertas_col.update_one(
                        {"parceiro_id": parceiro_id, "jogo_id": jogo_id},
                        {"$setOnInsert": {"status": "fechado", "itens": []}},
                        upsert=True,
                    )
                    total_ofertas += 1
                    continue

                # Upsert Parceiro
                parceiro_doc = parceiros_col.find_one_and_update(
                    {"slug": slug_parceiro},
                    {"$setOnInsert": {"nome": nome_parceiro, "slug": slug_parceiro}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                parceiro_id = parceiro_doc["_id"]

                # Mapeia ingressos → itens (schema do modelo Oferta)
                itens = []
                for ing in dados_parceiro.get("ingressos", []):
                    # Limpa e valida o nome
                    nome_raw = ing.get("setor", "")
                    nome = _limpar_texto(nome_raw)

                    # Descarta nomes genéricos de fallback do scraper
                    if not nome or len(nome) < 3 or _NOME_FALLBACK.match(nome):
                        continue

                    # Valida e converte o preço
                    preco = _parse_preco(ing.get("preco", ""))
                    if preco <= 0:
                        continue

                    itens.append(
                        {
                            "nome": nome,
                            "preco": preco,
                            "tipo": "individual",
                            "publico": "adulto",
                        }
                    )

                status = "ativo" if itens else "fechado"

                # Upsert Oferta — cria ou sobrescreve itens/status
                # Se preço mudou, os novos valores substituem os anteriores
                ofertas_col.update_one(
                    {"parceiro_id": parceiro_id, "jogo_id": jogo_id},
                    {"$set": {"status": status, "itens": itens}},
                    upsert=True,
                )
                total_ofertas += 1

        print(
            f"[MongoDB] Upsert concluído — "
            f"{len(resultados)} jogo(s), {total_ofertas} oferta(s) processada(s)"
        )
    finally:
        client.close()
