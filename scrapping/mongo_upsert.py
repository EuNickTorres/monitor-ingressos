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


def _make_slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def _parse_preco(preco_str: str) -> float:
    """Converte 'R$ 1.250,00' → 1250.0"""
    if not preco_str:
        return 0.0
    m = re.search(r"[\d.]+,\d{2}", preco_str)
    if m:
        return float(m.group().replace(".", "").replace(",", "."))
    m = re.search(r"\d+", preco_str)
    if m:
        return float(m.group())
    return 0.0


def upsert_resultados(resultados: dict) -> None:
    """
    Recebe o dict completo de resultados do scraper e faz upsert no MongoDB.

    Estrutura esperada:
        {
            "Corinthians x Coritiba": {
                "parceiros": {
                    "Camarote Fielzone": {
                        "ingressos": [{"setor": str, "preco": str}],
                        # "erro": str  ← se presente, a oferta não é atualizada
                    }
                }
            }
        }
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
                # Pula parceiros cujo scraping falhou — não apaga dados anteriores
                if "erro" in dados_parceiro:
                    continue

                slug_parceiro = _make_slug(nome_parceiro)

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
                    preco = _parse_preco(ing.get("preco", ""))
                    if preco > 0:
                        itens.append(
                            {
                                "nome": ing["setor"],
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
