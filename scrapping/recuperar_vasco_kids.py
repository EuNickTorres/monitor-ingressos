"""
Recupera os preços do Arena Kids para o jogo Corinthians x Vasco
a partir do backup em precos.txt (gerado em 17/04/2026).
"""
import os
from pymongo import MongoClient

ITENS_ARENA_KIDS = [
    {"nome": "Combo 4 Família Cadeira Preta", "preco": 1160.0, "tipo": "individual", "publico": "adulto"},
    {"nome": "Combo 1 Família Terraço em Pé", "preco": 1360.0, "tipo": "individual", "publico": "adulto"},
    {"nome": "Combo 2 Família Terraço em Pé", "preco": 1080.0, "tipo": "individual", "publico": "adulto"},
    {"nome": "Combo 4 Família Terraço em Pé", "preco": 960.0,  "tipo": "individual", "publico": "adulto"},
    {"nome": "Combo 3 Família Terraço em Pé", "preco": 680.0,  "tipo": "individual", "publico": "adulto"},
]

uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/ingressos")
client = MongoClient(uri, serverSelectionTimeoutMS=5000)
db = client.get_default_database()

jogo = db["jogos"].find_one({"slug": "corinthians-x-vasco"})
if not jogo:
    print("ERRO: jogo 'corinthians-x-vasco' não encontrado no banco.")
    client.close()
    exit(1)

parceiro = db["parceiros"].find_one({"slug": "arena-kids"})
if not parceiro:
    print("ERRO: parceiro 'arena-kids' não encontrado no banco.")
    client.close()
    exit(1)

oferta = db["ofertas"].find_one({"jogo_id": jogo["_id"], "parceiro_id": parceiro["_id"]}, {"itens": 1})
itens_salvos = {i["nome"]: i for i in (oferta.get("itens", []) if oferta else [])}

for item in ITENS_ARENA_KIDS:
    itens_salvos[item["nome"]] = item

itens_merged = list(itens_salvos.values())

db["ofertas"].update_one(
    {"jogo_id": jogo["_id"], "parceiro_id": parceiro["_id"]},
    {"$set": {"status": "ativo", "itens": itens_merged}},
    upsert=True,
)

print(f"OK: {len(itens_merged)} item(ns) salvos para Arena Kids — Corinthians x Vasco")
for i in itens_merged:
    print(f"  • {i['nome']:<55} R$ {i['preco']:>8.2f}")

client.close()
