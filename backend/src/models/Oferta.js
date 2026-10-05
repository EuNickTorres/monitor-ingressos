const mongoose = require("mongoose");

const itemSchema = new mongoose.Schema(
  {
    nome: { type: String, required: true },
    descricao: String,
    preco: { type: Number, required: true },
    tipo: { type: String, enum: ["individual", "combo"], required: true },
    publico: { type: String, enum: ["adulto", "infantil", "misto"], required: true },
    adultos: Number,
    criancas: Number,
  },
  { _id: false }
);

const ofertaSchema = new mongoose.Schema({
  parceiro_id: { type: mongoose.Schema.Types.ObjectId, ref: "Parceiro", required: true },
  jogo_id: { type: mongoose.Schema.Types.ObjectId, ref: "Jogo", required: true },
  status: { type: String, enum: ["ativo", "fechado"], default: "ativo" },
  itens: [itemSchema],
  atualizado_em: Date,
  ultima_tentativa_em: Date,
  ultimo_erro: String,
  desatualizado: { type: Boolean, default: false },
});

module.exports = mongoose.model("Oferta", ofertaSchema);
