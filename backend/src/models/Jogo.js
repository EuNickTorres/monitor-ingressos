const mongoose = require("mongoose");

const jogoSchema = new mongoose.Schema({
  nome: { type: String, required: true },
  data: { type: Date, required: true },
  slug: { type: String, required: true, unique: true },
});

module.exports = mongoose.model("Jogo", jogoSchema);
