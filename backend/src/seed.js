require("dotenv").config();

const mongoose = require("mongoose");
const connectDB = require("./db");
const Jogo = require("./models/Jogo");
const Parceiro = require("./models/Parceiro");
const Oferta = require("./models/Oferta");

async function seed() {
  await connectDB();

  await Promise.all([Jogo.deleteMany(), Parceiro.deleteMany(), Oferta.deleteMany()]);
  console.log("Collections limpas.");

  // ── Jogos ─────────────────────────────────────────────────────
  const [jogo1, jogo2] = await Jogo.insertMany([
    { nome: "Corinthians x São Paulo",  data: new Date("2025-04-10"), slug: "corinthians-x-sao-paulo-10-04" },
    { nome: "Palmeiras x Flamengo",     data: new Date("2025-04-20"), slug: "palmeiras-x-flamengo-20-04"   },
  ]);

  // ── Parceiros ─────────────────────────────────────────────────
  const [p1, p2, p3] = await Parceiro.insertMany([
    { nome: "Bar do Zeca",      slug: "bar-do-zeca"      },
    { nome: "Ingressos VIP",    slug: "ingressos-vip"    },
    { nome: "Casa do Torcedor", slug: "casa-do-torcedor" },
  ]);

  // ── Ofertas ───────────────────────────────────────────────────
  await Oferta.insertMany([
    {
      parceiro_id: p1._id,
      jogo_id:     jogo1._id,
      status:      "ativo",
      itens: [
        { nome: "Cadeira + Experiência", preco: 400.00, tipo: "individual", publico: "adulto" },
        { nome: "Meia-Entrada",          preco: 200.00, tipo: "individual", publico: "infantil" },
        { nome: "Combo Família",         preco: 950.00, tipo: "combo",      publico: "misto", adultos: 2, criancas: 1,
          descricao: "2 adultos + 1 criança" },
      ],
    },
    {
      parceiro_id: p2._id,
      jogo_id:     jogo1._id,
      status:      "ativo",
      itens: [
        { nome: "Camarote Premium",   preco: 850.00,  tipo: "individual", publico: "adulto" },
        { nome: "Combo VIP Duplo",    preco: 1650.00, tipo: "combo",      publico: "adulto", adultos: 2,
          descricao: "2 ingressos camarote + open bar" },
      ],
    },
    {
      parceiro_id: p3._id,
      jogo_id:     jogo1._id,
      status:      "fechado",
      itens: [
        { nome: "Arquibancada", preco: 150.00, tipo: "individual", publico: "adulto" },
      ],
    },
    {
      parceiro_id: p1._id,
      jogo_id:     jogo2._id,
      status:      "ativo",
      itens: [
        { nome: "Cadeira Coberta",  preco: 320.00, tipo: "individual", publico: "adulto" },
        { nome: "Combo Trio",       preco: 870.00, tipo: "combo",      publico: "misto", adultos: 2, criancas: 1,
          descricao: "2 adultos + 1 criança" },
      ],
    },
    {
      parceiro_id: p2._id,
      jogo_id:     jogo2._id,
      status:      "ativo",
      itens: [
        { nome: "Setor Leste",  preco: 280.00, tipo: "individual", publico: "adulto"   },
        { nome: "Setor Norte",  preco: 180.00, tipo: "individual", publico: "adulto"   },
        { nome: "Meia-Entrada", preco:  90.00, tipo: "individual", publico: "infantil" },
      ],
    },
  ]);

  console.log(`Seed concluído:
  - ${await Jogo.countDocuments()} jogos
  - ${await Parceiro.countDocuments()} parceiros
  - ${await Oferta.countDocuments()} ofertas`);

  await mongoose.disconnect();
}

seed().catch(err => {
  console.error("Erro no seed:", err.message);
  process.exit(1);
});
