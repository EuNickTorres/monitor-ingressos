const mongoose = require("mongoose");

const parceiroSchema = new mongoose.Schema({
  nome: { type: String, required: true },
  slug: { type: String, required: true, unique: true },
});

module.exports = mongoose.model("Parceiro", parceiroSchema);
