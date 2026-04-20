"""
Exporta todos os preços do MongoDB para um arquivo TXT legível.
Uso: python exportar_precos.py [--output precos.txt]
"""
import os
import argparse
from datetime import datetime
from pymongo import MongoClient


def exportar(output_path: str) -> None:
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/ingressos")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()

        jogos = {j["_id"]: j for j in db["jogos"].find().sort("data", 1)}
        parceiros = {p["_id"]: p for p in db["parceiros"].find()}
        ofertas = list(db["ofertas"].find())

        linhas = []
        linhas.append("=" * 60)
        linhas.append("  MONITOR DE INGRESSOS — PREÇOS")
        linhas.append(f"  Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        linhas.append("=" * 60)

        for jogo_id, jogo in jogos.items():
            data_str = jogo.get("data", "").strftime("%d/%m/%Y %H:%M") if jogo.get("data") else "—"
            linhas.append(f"\n{'=' * 60}")
            linhas.append(f"JOGO: {jogo['nome']}")
            linhas.append(f"Data: {data_str}")
            linhas.append("=" * 60)

            ofertas_jogo = [o for o in ofertas if o["jogo_id"] == jogo_id]

            if not ofertas_jogo:
                linhas.append("  (sem ofertas cadastradas)")
                continue

            for oferta in sorted(ofertas_jogo, key=lambda o: parceiros.get(o["parceiro_id"], {}).get("nome", "")):
                parceiro = parceiros.get(oferta["parceiro_id"], {})
                nome_parceiro = parceiro.get("nome", "Desconhecido")
                status = oferta.get("status", "—")
                itens = oferta.get("itens", [])

                linhas.append(f"\n  Parceiro: {nome_parceiro}  [{status.upper()}]")

                if itens:
                    for item in itens:
                        preco = item.get("preco", 0)
                        nome_item = item.get("nome", "—")
                        linhas.append(f"    • {nome_item:<40} R$ {preco:>10.2f}".replace(".", ","))
                else:
                    linhas.append("    (sem preços disponíveis)")

        linhas.append(f"\n{'=' * 60}")
        linhas.append(f"Total de jogos: {len(jogos)} | Total de ofertas: {len(ofertas)}")
        linhas.append("=" * 60)

        conteudo = "\n".join(linhas)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(conteudo)

        print(f"Exportado: {output_path}")
        print(f"  {len(jogos)} jogo(s) | {len(ofertas)} oferta(s)")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="precos.txt", help="Arquivo de saída (default: precos.txt)")
    args = parser.parse_args()
    exportar(args.output)
