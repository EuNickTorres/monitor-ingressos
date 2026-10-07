"""
Persiste os resultados do scraper no MongoDB (backend) sem gerar duplicatas.
Faz upsert de Jogos, Parceiros e Ofertas.
- Jogo/Parceiro: cria se não existir, preserva dados existentes se já houver.
- Oferta: cria ou atualiza itens/status — se preço mudou, sobrescreve.
"""
import os
import re
import unicodedata
from datetime import datetime, timezone

from pymongo import MongoClient, ReturnDocument

# Padrão para nomes genéricos de fallback gerados pelo scraper quando o
# jogo não é encontrado no site do parceiro (ex.: "Ingresso 3", "Ver no site")
_NOME_FALLBACK = re.compile(r"^ingresso\s+\d+$|^ver no site$", re.IGNORECASE)


def _make_slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
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
    db_padrao = os.getenv("MONGO_DB_NAME", "ingressos")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        # O Atlas permite connection strings sem o caminho do banco
        # (…mongodb.net/?retryWrites=…). Nessa situação o PyMongo não tem um
        # database padrão e get_default_database() lança ConfigurationError.
        # Mantém o banco declarado na URI quando houver e usa "ingressos"
        # como fallback seguro quando o caminho estiver ausente.
        db = client.get_default_database(default=db_padrao)
        jogos_col = db["jogos"]
        parceiros_col = db["parceiros"]
        ofertas_col = db["ofertas"]

        total_ofertas = 0

        for nome_jogo, dados_jogo in resultados.items():
            slug_jogo = _make_slug(nome_jogo)

            # Tenta parsear a data real do jogo extraída do Arena Kids
            # Formato esperado: "Domingo 26/04 16h00" ou "26/04 16h00"
            data_jogo_str = dados_jogo.get("data_jogo", "")
            data_parsed = None
            if data_jogo_str:
                agora = datetime.now(timezone.utc).replace(tzinfo=None)
                ano = agora.year
                # Formato completo: dd/mm HHhMM
                m = re.search(r'(\d{2})/(\d{2})\s+(\d{1,2})h(\d{2})', data_jogo_str)
                if m:
                    dia, mes, hora, minuto = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    try:
                        data_parsed = datetime(ano, mes, dia, hora, minuto)
                        # Em novembro/dezembro, eventos de janeiro pertencem ao
                        # ano seguinte. Evita salvar jogos futuros no passado.
                        if data_parsed < agora and (agora - data_parsed).days > 120:
                            data_parsed = data_parsed.replace(year=ano + 1)
                    except ValueError:
                        pass
                # Formato só data: dd/mm
                if not data_parsed:
                    m = re.search(r'(\d{2})/(\d{2})', data_jogo_str)
                    if m:
                        dia, mes = int(m.group(1)), int(m.group(2))
                        try:
                            data_parsed = datetime(ano, mes, dia, 0, 0)
                            if data_parsed < agora and (agora - data_parsed).days > 120:
                                data_parsed = data_parsed.replace(year=ano + 1)
                        except ValueError:
                            pass

            # Upsert Jogo — usa data real do jogo se disponível; senão usa now() só na criação
            set_on_insert = {"nome": nome_jogo, "slug": slug_jogo}
            update_op = {"$setOnInsert": set_on_insert}
            if data_parsed:
                # Atualiza sempre para refletir mudanças de data/hora do jogo
                update_op["$set"] = {"data": data_parsed}
            else:
                set_on_insert["data"] = datetime.now(timezone.utc).replace(tzinfo=None)

            jogo_doc = jogos_col.find_one_and_update(
                {"slug": slug_jogo},
                update_op,
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            jogo_id = jogo_doc["_id"]

            for nome_parceiro, dados_parceiro in dados_jogo.get("parceiros", {}).items():
                slug_parceiro = _make_slug(nome_parceiro)

                # Upsert Parceiro sempre (mesmo em caso de erro)
                parceiro_doc = parceiros_col.find_one_and_update(
                    {"slug": slug_parceiro},
                    {
                        "$setOnInsert": {"nome": nome_parceiro, "slug": slug_parceiro},
                        "$set": {"url": dados_parceiro.get("url_base", "")},
                    },
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                parceiro_id = parceiro_doc["_id"]

                if "erro" in dados_parceiro:
                    # Preserva o ultimo resultado valido, mas marca claramente
                    # que a fonte falhou nesta tentativa.
                    _existente = ofertas_col.find_one(
                        {"parceiro_id": parceiro_id, "jogo_id": jogo_id}, {"itens": 1}
                    )
                    campos_erro = {
                        "ultima_tentativa_em": datetime.now(timezone.utc),
                        "ultimo_erro": _limpar_texto(str(dados_parceiro.get("erro", "Falha na coleta")))[:500],
                        "desatualizado": True,
                    }
                    if not (_existente and _existente.get("itens")):
                        campos_erro.update({"status": "fechado", "itens": []})
                    ofertas_col.update_one(
                        {"parceiro_id": parceiro_id, "jogo_id": jogo_id},
                        {"$set": campos_erro},
                        upsert=True,
                    )
                    total_ofertas += 1
                    continue

                # Upsert Parceiro
                parceiro_doc = parceiros_col.find_one_and_update(
                    {"slug": slug_parceiro},
                    {
                        "$setOnInsert": {"nome": nome_parceiro, "slug": slug_parceiro},
                        "$set": {"url": dados_parceiro.get("url_base", "")},
                    },
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                parceiro_id = parceiro_doc["_id"]

                # Mapeia ingressos → itens (schema do modelo Oferta)
                itens_por_nome = {}
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

                    chave_item = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii").lower()
                    itens_por_nome[chave_item] = {
                        "nome": nome,
                        "preco": preco,
                        "tipo": "individual",
                        "publico": "adulto",
                    }

                itens = list(itens_por_nome.values())

                if itens:
                    agora_coleta = datetime.now(timezone.utc)
                    ofertas_col.update_one(
                        {"parceiro_id": parceiro_id, "jogo_id": jogo_id},
                        {
                            "$set": {
                                "status": "ativo",
                                "itens": itens,
                                "atualizado_em": agora_coleta,
                                "ultima_tentativa_em": agora_coleta,
                                "desatualizado": False,
                            },
                            "$unset": {"ultimo_erro": ""},
                        },
                        upsert=True,
                    )
                else:
                    # Resultado vazio pode ser bloqueio temporario do site.
                    # Mantem dados anteriores, mas nunca os apresenta como atuais.
                    _existente = ofertas_col.find_one(
                        {"parceiro_id": parceiro_id, "jogo_id": jogo_id}, {"itens": 1}
                    )
                    campos_vazios = {
                        "ultima_tentativa_em": datetime.now(timezone.utc),
                        "ultimo_erro": "Nenhum preco valido encontrado na ultima coleta",
                        "desatualizado": True,
                    }
                    if not (_existente and _existente.get("itens")):
                        campos_vazios.update({"status": "fechado", "itens": []})
                    ofertas_col.update_one(
                        {"parceiro_id": parceiro_id, "jogo_id": jogo_id},
                        {"$set": campos_vazios},
                        upsert=True,
                    )
                total_ofertas += 1

        print(
            f"[MongoDB] Upsert concluído — "
            f"{len(resultados)} jogo(s), {total_ofertas} oferta(s) processada(s)"
        )
    finally:
        client.close()
